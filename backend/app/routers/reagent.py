"""试剂耗材接口：维护试剂物料，覆盖冻结物料、解冻物料、登记耗尽与出入库单据整批导入。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, ImportPayload, ImportResult, PageResult
from app.services.reagent import ReagentService

router = APIRouter(prefix="/api/reagent", tags=["试剂耗材"])

service = ReagentService()

LIST_FIELDS = ["物料编号", "物料名称", "规格纯度", "批号", "结存数量", "有效期至", "保管人员", "物料状态"]
STATUSES = ["正常可用", "临近有效期", "已冻结", "已耗尽"]


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按物料编号检索"),
    status: str | None = Query(default=None, description="正常可用、临近有效期、已冻结、已耗尽"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按物料编号与状态过滤试剂耗材列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/import", response_model=ImportResult)
def import_entries(payload: ImportPayload) -> ImportResult:
    """整批导入出入库单据：按物料编号入账并重算结存。

    同一批号在同一单据时间重复导入只入账一次；规格纯度不一致、数量为负、
    单据时间早于上一次结存或物料已冻结的行逐条列出原因并拒绝写入。
    """
    if not payload.rows:
        return ImportResult(ok=False, message="导入文件为空，没有可处理的出入库单据")
    result = service.import_documents(payload.rows)
    return ImportResult(**result)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出试剂耗材清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "reagent", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条试剂物料明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"试剂物料 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条试剂物料，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    return ActionResult(ok=True, message="试剂物料已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条试剂物料执行冻结物料、解冻物料、登记耗尽；不允许的动作会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
