"""试剂耗材业务规则：状态流转、字段校验、出入库单据整批导入与结存重算都收在这里。"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from app.store import store

MODULE = "reagent"
VOUCHER_MODULE = "reagent_voucher"
REQUIRED_FIELDS = ["物料编号", "物料名称", "规格纯度"]
STATUS_ORDER = ["正常可用", "临近有效期", "已冻结", "已耗尽"]
ACTION_RULES = {"冻结物料": "已冻结", "解冻物料": "正常可用", "登记耗尽": "已耗尽"}
NEGATIVE_ACTIONS = []

# 单据文件表头：物料编号、规格纯度、批号、出入数量与有效期至为必带列，单据时间用于过账时序与幂等
IMPORT_REQUIRED_COLUMNS = ["物料编号", "规格纯度", "批号", "出入数量", "有效期至", "单据时间"]
IMPORT_OPTIONAL_COLUMNS = ["物料名称", "出入库类型", "保管人员"]
# 有效期剩余天数不超过该阈值即视为临期
NEAR_EXPIRY_DAYS = 30
# 出/入库类型列的取值归一化
OUTBOUND_MARKS = {"出库", "出", "领用", "消耗", "out", "-"}
INBOUND_MARKS = {"入库", "入", "进", "采购", "in", "+"}


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

    def stats(self) -> dict[str, int]:
        """临期/耗尽等计数与列表同源于台账 status，保证三处结存与状态口径一致。"""
        rows = store.rows(MODULE)
        return {
            "正常可用": sum(1 for row in rows if row.get("status") == "正常可用"),
            "临近有效期": sum(1 for row in rows if row.get("status") == "临近有效期"),
            "已冻结": sum(1 for row in rows if row.get("status") == "已冻结"),
            "已耗尽": sum(1 for row in rows if row.get("status") == "已耗尽"),
        }

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        entry["status"] = STATUS_ORDER[0]
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

    # ------------------------------------------------------------------
    # 出入库单据整批导入
    # ------------------------------------------------------------------
    def import_documents(
        self, records: list[dict[str, Any]], *, today: date | None = None
    ) -> dict[str, Any]:
        """按单据批量过账。

        流程：逐行解析校验 -> 全部通过才写入（任一行失败则整批拒写）->
        按单据重算结存 -> 按有效期/结存重算临期与耗尽状态。
        同一物料批号在同一单据时间只入账一次，重试时已入账行自动跳过，不重复扣减。
        """
        today = today or date.today()
        if not records:
            raise ValueError("导入文件没有可解析的数据行，请确认表头后重试")

        rows = store.rows(MODULE)
        vouchers = store.rows(VOUCHER_MODULE)
        posted_keys = {
            (str(v.get("物料编号", "")), str(v.get("批号", "")), str(v.get("单据时间", "")))
            for v in vouchers
        }

        parsed: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        skipped = 0
        seen_in_file: set[tuple[str, str, str]] = set()

        for line_no, raw in enumerate(records, start=2):  # 第 1 行是表头
            code = str(raw.get("物料编号") or "").strip()
            spec = str(raw.get("规格纯度") or "").strip()
            batch = str(raw.get("批号") or "").strip()
            key = (code, batch, str(raw.get("单据时间") or "").strip())

            reason = self._validate_row(raw, rows, seen_in_file, posted_keys, key)
            if reason is not None:
                # 已入账行在重试时跳过，不算失败；同一文件内重复行仍逐条拒绝
                if reason == "__posted__":
                    skipped += 1
                    continue
                failures.append({"行号": line_no, "物料编号": code, "批号": batch, "原因": reason})
                continue

            seen_in_file.add(key)
            parsed.append(
                {
                    "line_no": line_no,
                    "物料编号": code,
                    "物料名称": str(raw.get("物料名称") or "").strip(),
                    "规格纯度": spec,
                    "批号": batch,
                    "数量": self._parse_quantity(raw.get("出入数量")),
                    "出库": self._is_outbound(raw.get("出入库类型")),
                    "有效期至": self._parse_date(raw.get("有效期至")).isoformat(),
                    "单据时间": self._parse_date(raw.get("单据时间")),
                    "保管人员": str(raw.get("保管人员") or "").strip(),
                }
            )

        if failures:
            return {
                "ok": False,
                "message": f"{len(failures)} 行校验未通过，整批未写入，修正后可重试",
                "posted": 0,
                "skipped": skipped,
                "failures": failures,
                "entries": [],
            }

        if not parsed:
            return {
                "ok": True,
                "message": "文件中的单据此前均已入账，本次没有重复扣减" if skipped else "没有可入账的新单据",
                "posted": 0,
                "skipped": skipped,
                "failures": [],
                "entries": [],
            }

        # 全部校验通过，按物料批号分组、按单据时间顺序过账，逐笔重算结存
        affected: set[int] = set()
        next_voucher_id = max((int(v.get("id", 0)) for v in vouchers), default=0)
        for doc in sorted(parsed, key=lambda item: (item["物料编号"], item["批号"], item["单据时间"])):
            ledger = self._find_ledger(rows, doc["物料编号"], doc["批号"])
            if ledger is None:
                ledger = self._create_ledger(rows, doc)
            delta = -doc["数量"] if doc["出库"] else doc["数量"]
            ledger["结存数量"] = self._quantity_value(Decimal(str(ledger["结存数量"])) + delta)
            ledger["有效期至"] = doc["有效期至"]
            ledger["上次结存时间"] = doc["单据时间"].isoformat()
            if doc["保管人员"]:
                ledger["保管人员"] = doc["保管人员"]
            affected.add(int(ledger["id"]))

            next_voucher_id += 1
            vouchers.append(
                {
                    "id": next_voucher_id,
                    "物料编号": doc["物料编号"],
                    "规格纯度": doc["规格纯度"],
                    "批号": doc["批号"],
                    "出入数量": self._quantity_value(doc["数量"]),
                    "出入库类型": "出库" if doc["出库"] else "入库",
                    "有效期至": doc["有效期至"],
                    "单据时间": doc["单据时间"].isoformat(),
                    "台账行": int(ledger["id"]),
                }
            )

        # 导入后统一按有效期与结存重算临期/耗尽（已冻结物料保持冻结，不被导入改写状态）
        for row in rows:
            self._refresh_status(row, today)

        entries = [store.find(MODULE, entry_id) for entry_id in sorted(affected)]
        return {
            "ok": True,
            "message": f"成功入账 {len(parsed)} 张单据"
            + (f"，跳过 {skipped} 张已入账单据" if skipped else ""),
            "posted": len(parsed),
            "skipped": skipped,
            "failures": [],
            "entries": entries,
        }

    # ------------------------------------------------------------------
    # 校验与辅助方法
    # ------------------------------------------------------------------
    def _validate_row(
        self,
        raw: dict[str, Any],
        rows: list[dict[str, Any]],
        seen_in_file: set[tuple[str, str, str]],
        posted_keys: set[tuple[str, str, str]],
        key: tuple[str, str, str],
    ) -> str | None:
        """返回 None 表示通过；返回 '__posted__' 表示此前已入账，调用方按跳过处理。"""
        code = key[0]
        spec = str(raw.get("规格纯度") or "").strip()
        batch = key[1]
        for column in IMPORT_REQUIRED_COLUMNS:
            if not str(raw.get(column) or "").strip():
                return f"必填列「{column}」为空"

        if key in seen_in_file:
            return "同一批号在同一单据时间在本文件中重复出现，只能入账一次"
        if key in posted_keys:
            return "__posted__"

        try:
            quantity = self._parse_quantity(raw.get("出入数量"))
        except ValueError as exc:
            return str(exc)
        if quantity <= 0:
            return "出入数量必须为正数，出库请在「出入库类型」列标注出库"

        try:
            doc_date = self._parse_date(raw.get("单据时间"))
            expiry = self._parse_date(raw.get("有效期至"))
        except ValueError as exc:
            return str(exc)

        material_rows = [row for row in rows if str(row.get("物料编号", "")) == code]
        if not material_rows:
            return f"物料编号 {code} 不在试剂台账中，请先登记物料"

        if any(row.get("status") == "已冻结" for row in material_rows):
            return f"物料编号 {code} 已冻结，不允许导入更新"

        ledger = self._find_ledger(rows, code, batch)
        material_spec = str(material_rows[0].get("规格纯度") or "").strip()
        expected_spec = str(ledger.get("规格纯度") or "").strip() if ledger else material_spec
        if spec != expected_spec:
            return f"规格纯度「{spec}」与既有台账「{expected_spec}」不一致"

        is_outbound = self._is_outbound(raw.get("出入库类型"))
        if ledger is None and is_outbound:
            return f"批号 {batch} 在台账中不存在，不能对其做出库"

        last_time_text = str(ledger.get("上次结存时间") or "").strip() if ledger else ""
        if last_time_text:
            last_time = self._parse_date(last_time_text)
            if doc_date < last_time:
                return f"单据时间 {doc_date.isoformat()} 早于上一次结存时间 {last_time.isoformat()}"

        if is_outbound and ledger is not None:
            balance = Decimal(str(ledger.get("结存数量", 0)))
            if quantity > balance:
                return f"出库数量 {self._quantity_value(quantity)} 超过当前结存 {self._quantity_value(balance)}"

        if expiry < doc_date:
            return f"有效期至 {expiry.isoformat()} 早于单据时间 {doc_date.isoformat()}"
        return None

    @staticmethod
    def _find_ledger(rows: list[dict[str, Any]], code: str, batch: str) -> dict[str, Any] | None:
        for row in rows:
            if str(row.get("物料编号", "")) == code and str(row.get("批号", "")) == batch:
                return row
        return None

    @staticmethod
    def _create_ledger(rows: list[dict[str, Any]], doc: dict[str, Any]) -> dict[str, Any]:
        template = next(row for row in rows if str(row.get("物料编号", "")) == doc["物料编号"])
        ledger = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        ledger["物料编号"] = doc["物料编号"]
        ledger["物料名称"] = doc["物料名称"] or template.get("物料名称", "")
        ledger["规格纯度"] = doc["规格纯度"]
        ledger["批号"] = doc["批号"]
        ledger["结存数量"] = 0
        ledger["有效期至"] = doc["有效期至"]
        ledger["保管人员"] = doc["保管人员"] or template.get("保管人员", "")
        ledger["status"] = "正常可用"
        ledger["物料状态"] = "正常可用"
        ledger["pending"] = True
        ledger["abnormal"] = False
        rows.append(ledger)
        return ledger

    def _refresh_status(self, row: dict[str, Any], today: date) -> None:
        """按有效期与结存统一推导状态；已冻结物料保持冻结。"""
        if row.get("status") == "已冻结":
            row["物料状态"] = "已冻结"
            row["pending"] = False
            return
        balance = Decimal(str(row.get("结存数量", 0)))
        if balance <= 0:
            status = "已耗尽"
        else:
            status = "正常可用"
            expiry_text = str(row.get("有效期至") or "").strip()
            if expiry_text:
                try:
                    expiry = self._parse_date(expiry_text)
                    if expiry <= today + timedelta(days=NEAR_EXPIRY_DAYS):
                        status = "临近有效期"
                except ValueError:
                    pass
        row["status"] = status
        row["物料状态"] = status
        row["pending"] = status != "已耗尽"
        row["abnormal"] = status == "临近有效期"

    @staticmethod
    def _parse_date(value: Any) -> date:
        text = str(value or "").strip().replace("/", "-").replace(".", "-")
        if not text:
            raise ValueError("日期为空")
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
        raise ValueError(f"日期「{str(value).strip()}」格式不正确，应为 YYYY-MM-DD")

    @staticmethod
    def _parse_quantity(value: Any) -> Decimal:
        text = str(value if value is not None else "").strip()
        try:
            return Decimal(text)
        except (InvalidOperation, ValueError):
            raise ValueError(f"出入数量「{text}」不是合法数字")

    @staticmethod
    def _is_outbound(value: Any) -> bool:
        text = str(value or "").strip().lower()
        if not text:
            return False
        if text in OUTBOUND_MARKS:
            return True
        if text in INBOUND_MARKS:
            return False
        return text.startswith("出")

    @staticmethod
    def _quantity_value(value: Decimal) -> int | float:
        return int(value) if value == value.to_integral_value() else float(value)
