"""试剂物料出入库单据整批导入的验收测试。

覆盖：按单据重算结存、同批号同时间幂等、逐条拒绝原因、临期/耗尽状态重算、
列表/明细/临期筛选三处结存一致、已冻结物料拒绝更新、失败重试不重复扣减。
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

TODAY = date.today()
FAR_FUTURE = (TODAY + timedelta(days=200)).isoformat()
NEAR_FUTURE = (TODAY + timedelta(days=10)).isoformat()
DOC_TIME = (TODAY + timedelta(days=1)).isoformat()


def make_row(**overrides) -> dict:
    row = {
        "物料编号": "REAG-0001",
        "规格纯度": "分析纯 AR",
        "批号": "LOT-2026-101",
        "出入数量": 5,
        "有效期至": FAR_FUTURE,
        "单据时间": DOC_TIME,
        "出入类型": "入库",
    }
    row.update(overrides)
    return row


def import_rows(rows: list[dict]) -> dict:
    response = client.post("/api/reagent/import", json={"rows": rows})
    assert response.status_code == 200
    return response.json()


def balance_of(code: str) -> float:
    for item in client.get("/api/reagent", params={"size": 200}).json()["items"]:
        if item["物料编号"] == code:
            return item["结存数量"]
    raise AssertionError(f"台账里找不到 {code}")


def test_inbound_recalculates_balance_and_expiry():
    result = import_rows([make_row()])
    assert result["ok"] is True
    assert result["posted"] == 1
    assert balance_of("REAG-0001") == 15
    detail = client.get("/api/reagent/1").json()
    assert detail["结存数量"] == 15
    assert detail["批号"] == "LOT-2026-101"
    assert detail["有效期至"] == FAR_FUTURE
    assert detail["最近入账时间"] == DOC_TIME


def test_outbound_recalculates_balance():
    result = import_rows([make_row(出入类型="出库", 出入数量=4)])
    assert result["posted"] == 1
    assert balance_of("REAG-0001") == 6


def test_duplicate_batch_and_time_posted_only_once():
    first = import_rows([make_row()])
    assert first["posted"] == 1
    second = import_rows([make_row()])
    assert second["posted"] == 0
    assert second["duplicated"] == 1
    assert balance_of("REAG-0001") == 15


def test_duplicate_rows_within_one_file_posted_once():
    result = import_rows([make_row(), make_row()])
    assert result["posted"] == 1
    assert result["duplicated"] == 1
    assert balance_of("REAG-0001") == 15


def test_same_batch_at_different_time_is_allowed():
    later = (TODAY + timedelta(days=2)).isoformat()
    result = import_rows([make_row(), make_row(单据时间=later)])
    assert result["posted"] == 2
    assert balance_of("REAG-0001") == 20


def test_spec_mismatch_rejected_with_reason():
    result = import_rows([make_row(规格纯度="优级纯 GR")])
    assert result["ok"] is False
    assert result["rejected"] == 1
    assert any("规格纯度" in reason for reason in result["errors"][0]["reasons"])
    assert balance_of("REAG-0001") == 10


def test_negative_quantity_rejected_with_reason():
    result = import_rows([make_row(出入数量=-3)])
    assert result["rejected"] == 1
    assert any("出入数量为负" in reason for reason in result["errors"][0]["reasons"])
    assert balance_of("REAG-0001") == 10


def test_doc_time_before_last_posting_rejected():
    result = import_rows([make_row(单据时间="2026-08-01")])
    assert result["rejected"] == 1
    assert any("早于上一次结存" in reason for reason in result["errors"][0]["reasons"])
    assert balance_of("REAG-0001") == 10


def test_frozen_reagent_rejected():
    result = import_rows([
        make_row(物料编号="REAG-0003", 规格纯度="优级纯 GR", 批号="LOT-2026-301"),
    ])
    assert result["rejected"] == 1
    assert any("已冻结" in reason for reason in result["errors"][0]["reasons"])
    assert balance_of("REAG-0003") == 30


def test_unknown_material_rejected():
    result = import_rows([make_row(物料编号="REAG-9999")])
    assert result["rejected"] == 1
    assert any("不存在" in reason for reason in result["errors"][0]["reasons"])


def test_outbound_beyond_balance_rejected():
    result = import_rows([make_row(出入类型="出库", 出入数量=99)])
    assert result["rejected"] == 1
    assert any("超过当前结存" in reason for reason in result["errors"][0]["reasons"])
    assert balance_of("REAG-0001") == 10


def test_missing_columns_rejected():
    row = make_row()
    del row["批号"]
    result = import_rows([row])
    assert result["rejected"] == 1
    assert any("批号" in reason for reason in result["errors"][0]["reasons"])


def test_status_recalculated_to_near_expiry():
    result = import_rows([make_row(有效期至=NEAR_FUTURE)])
    assert result["posted"] == 1
    detail = client.get("/api/reagent/1").json()
    assert detail["status"] == "临近有效期"
    assert detail["物料状态"] == "临近有效期"


def test_status_recalculated_to_depleted_when_balance_zero():
    result = import_rows([make_row(出入类型="出库", 出入数量=10)])
    assert result["posted"] == 1
    detail = client.get("/api/reagent/1").json()
    assert detail["结存数量"] == 0
    assert detail["status"] == "已耗尽"


def test_balance_consistent_across_list_detail_and_status_filter():
    import_rows([make_row(有效期至=NEAR_FUTURE)])
    listed = balance_of("REAG-0001")
    detail = client.get("/api/reagent/1").json()["结存数量"]
    filtered = client.get("/api/reagent", params={"status": "临近有效期"}).json()["items"]
    assert listed == 15 == detail
    assert len(filtered) >= 1
    assert all(item["物料状态"] == "临近有效期" for item in filtered)
    reag = next(item for item in filtered if item["物料编号"] == "REAG-0001")
    assert reag["结存数量"] == 15


def test_retry_after_partial_failure_never_double_deducts():
    bad = make_row(批号="LOT-2026-102", 出入数量=-2)
    good = make_row(批号="LOT-2026-103", 出入数量=3)
    first = import_rows([bad, good])
    assert first["posted"] == 1
    assert first["rejected"] == 1
    assert balance_of("REAG-0001") == 13

    fixed = make_row(批号="LOT-2026-102", 出入数量=2)
    retry = import_rows([fixed, good])
    assert retry["posted"] == 1
    assert retry["duplicated"] == 1
    assert balance_of("REAG-0001") == 15


def test_empty_import_rejected():
    response = client.post("/api/reagent/import", json={"rows": []})
    assert response.status_code == 200
    assert response.json()["ok"] is False
