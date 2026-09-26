"""试剂耗材业务规则：状态流转、字段校验与筛选口径都收在这里。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.store import store

MODULE = "reagent"
LEDGER_MODULE = "reagent_ledger"
REQUIRED_FIELDS = ["物料编号", "物料名称", "规格纯度"]
STATUS_ORDER = ["正常可用", "临近有效期", "已冻结", "已耗尽"]
ACTION_RULES = {"冻结物料": "已冻结", "解冻物料": "正常可用", "登记耗尽": "已耗尽"}
NEGATIVE_ACTIONS = []

USABLE_STATUS = "正常可用"
NEAR_EXPIRY_STATUS = "临近有效期"
FROZEN_STATUS = "已冻结"
DEPLETED_STATUS = "已耗尽"
NEAR_EXPIRY_DAYS = 30

# 整批导入出入库单据的列口径：六列必填，出入类型缺省按入库处理
IMPORT_REQUIRED_FIELDS = ["物料编号", "规格纯度", "批号", "出入数量", "有效期至", "单据时间"]
DIRECTION_SIGNS = {"入库": 1, "出库": -1}
DEFAULT_DIRECTION = "入库"


def _parse_date(raw: Any) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _parse_quantity(raw: Any) -> float | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)):
        return float(raw)
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _normalize_qty(value: float) -> int | float:
    return int(value) if float(value).is_integer() else value


class ReagentService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("物料编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["物料状态"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"试剂物料 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于试剂耗材可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["物料状态"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        return entry, f"试剂物料已{action}"

    def recalc_status(self, entry: dict[str, Any], today: date) -> None:
        """按结存数量与有效期至重算物料状态；已冻结的物料保持冻结，不参与重算。"""
        if entry.get("status") == FROZEN_STATUS:
            return
        balance = _parse_quantity(entry.get("结存数量")) or 0.0
        if balance <= 0:
            target = DEPLETED_STATUS
        else:
            expiry = _parse_date(entry.get("有效期至"))
            if expiry is not None and (expiry - today).days <= NEAR_EXPIRY_DAYS:
                target = NEAR_EXPIRY_STATUS
            else:
                target = USABLE_STATUS
        entry["status"] = target
        entry["物料状态"] = target
        entry["pending"] = target != DEPLETED_STATUS

    def import_documents(
        self,
        rows: list[dict[str, Any]],
        *,
        today: date | None = None,
    ) -> dict[str, Any]:
        """整批导入出入库单据：逐行校验后入账，重复单据只入账一次。

        返回汇总结构，posted/duplicated/errors 三段分别对应入账、幂等跳过与拒绝的行，
        调用方失败重试时已入账的行会被幂等键拦下，不会重复扣减结存。
        """
        today = today or date.today()
        ledger = store.rows(LEDGER_MODULE)
        posted_keys = {
            (
                str(record.get("物料编号", "")),
                str(record.get("批号", "")),
                str(record.get("单据时间", "")),
            )
            for record in ledger
        }
        posted: list[dict[str, Any]] = []
        duplicated: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        touched: dict[int, dict[str, Any]] = {}

        for index, raw in enumerate(rows, start=1):
            values = raw if isinstance(raw, dict) else {}
            reasons = self._validate_row(values)
            if reasons:
                errors.append({"row": index, "reasons": reasons, "values": values})
                continue
            code = str(values.get("物料编号")).strip()
            entry = self._find_by_code(code)
            assert entry is not None  # 校验通过即已确认台账存在
            direction = str(values.get("出入类型") or DEFAULT_DIRECTION).strip()
            sign = DIRECTION_SIGNS[direction]
            quantity = _parse_quantity(values.get("出入数量")) or 0.0
            doc_date = _parse_date(values.get("单据时间"))
            assert doc_date is not None
            key = (code, str(values.get("批号")).strip(), doc_date.isoformat())
            if key in posted_keys:
                duplicated.append({"row": index, "values": values})
                continue

            balance = _parse_quantity(entry.get("结存数量")) or 0.0
            balance += sign * quantity
            entry["结存数量"] = _normalize_qty(balance)
            if sign > 0:
                entry["批号"] = str(values.get("批号")).strip()
                entry["有效期至"] = str(values.get("有效期至")).strip()
            entry["最近入账时间"] = doc_date.isoformat()
            ledger.append({
                "id": max((int(record.get("id", 0)) for record in ledger), default=0) + 1,
                "物料编号": code,
                "批号": key[1],
                "出入类型": direction,
                "出入数量": _normalize_qty(quantity),
                "单据时间": key[2],
                "入账时间": datetime.now().isoformat(timespec="seconds"),
                "结存数量": entry["结存数量"],
            })
            posted_keys.add(key)
            self.recalc_status(entry, today)
            touched[int(entry.get("id", 0))] = entry
            posted.append({"row": index, "values": values})

        rejected = len(errors)
        total = len(rows)
        ok = rejected == 0
        message = (
            f"导入完成：入账 {len(posted)} 条，重复跳过 {len(duplicated)} 条，拒绝 {rejected} 条"
            if total
            else "导入文件为空，没有可处理的出入库单据"
        )
        return {
            "ok": ok and total > 0,
            "message": message,
            "total": total,
            "posted": len(posted),
            "duplicated": len(duplicated),
            "rejected": rejected,
            "errors": errors,
            "entries": list(touched.values()),
        }

    def _find_by_code(self, code: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("物料编号", "")) == code:
                return row
        return None

    def _validate_row(self, values: dict[str, Any]) -> list[str]:
        """逐行校验导入单据，返回全部拒绝原因；空列表表示可以入账。"""
        reasons: list[str] = []
        missing = [field for field in IMPORT_REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            reasons.append(f"缺少必填列：{'、'.join(missing)}")
            return reasons

        code = str(values.get("物料编号")).strip()
        entry = self._find_by_code(code)
        if entry is None:
            reasons.append(f"物料编号 {code} 在试剂台账中不存在")
        elif entry.get("status") == FROZEN_STATUS:
            reasons.append(f"物料 {code} 已冻结，不允许导入更新")
        elif str(values.get("规格纯度")).strip() != str(entry.get("规格纯度", "")).strip():
            reasons.append(
                f"规格纯度「{str(values.get('规格纯度')).strip()}」与既有台账"
                f"「{str(entry.get('规格纯度', '')).strip()}」不一致"
            )

        quantity = _parse_quantity(values.get("出入数量"))
        if quantity is None:
            reasons.append("出入数量不是有效数字")
        elif quantity < 0:
            reasons.append("出入数量为负，出入库方向请用出入类型列表达")

        doc_date = _parse_date(values.get("单据时间"))
        if doc_date is None:
            reasons.append(f"单据时间「{values.get('单据时间')}」不是有效日期")
        if _parse_date(values.get("有效期至")) is None:
            reasons.append(f"有效期至「{values.get('有效期至')}」不是有效日期")

        direction = str(values.get("出入类型") or DEFAULT_DIRECTION).strip()
        if direction not in DIRECTION_SIGNS:
            reasons.append(f"出入类型「{direction}」只能是入库或出库")

        if reasons or entry is None or doc_date is None or quantity is None:
            return reasons

        last_posted = _parse_date(entry.get("最近入账时间"))
        if last_posted is not None and doc_date < last_posted:
            reasons.append(
                f"单据时间 {doc_date.isoformat()} 早于上一次结存 {last_posted.isoformat()}"
            )
        if direction == "出库":
            balance = _parse_quantity(entry.get("结存数量")) or 0.0
            if quantity > balance:
                reasons.append(f"出库数量 {_normalize_qty(quantity)} 超过当前结存 {_normalize_qty(balance)}")
        return reasons
