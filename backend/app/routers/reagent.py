"""试剂耗材接口：维护试剂物料，覆盖冻结物料、解冻物料、登记耗尽、出入库单据整批导入等动作。"""
from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response

from app.schemas import ActionResult, EntryPayload, PageResult, ReagentImportResult
from app.services.reagent import (
    IMPORT_OPTIONAL_COLUMNS,
    IMPORT_REQUIRED_COLUMNS,
    ReagentService,
)

router = APIRouter(prefix="/api/reagent", tags=["试剂耗材"])

service = ReagentService()

LIST_FIELDS = ["物料编号", "物料名称", "规格纯度", "批号", "结存数量", "有效期至", "保管人员", "物料状态"]
STATUSES = ["正常可用", "临近有效期", "已冻结", "已耗尽"]
IMPORT_COLUMNS = IMPORT_REQUIRED_COLUMNS + IMPORT_OPTIONAL_COLUMNS


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


@router.get("/stats", response_model=dict[str, int])
def reagent_stats() -> dict[str, int]:
    """台账状态计数：与列表、明细同源于同一份台账，保证结存与状态口径一致。"""
    return service.stats()


@router.get("/import-template")
def import_template() -> Response:
    """下载出入库单据导入模板（CSV，UTF-8 带 BOM，Excel 可直接打开）。"""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(IMPORT_COLUMNS)
    writer.writerow(["REAG-0001", "AR/500mL", "B20260801", "5", "2028-08-01", "2026-09-26", "无水乙醇", "入库", "王敏"])
    content = "﻿" + buffer.getvalue()
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=reagent_import_template.csv"},
    )


@router.post("/import", response_model=ReagentImportResult)
async def import_documents(request: Request) -> ReagentImportResult:
    """按物料编号整批导入出入库单据，导入时按单据重算结存数量与临期/耗尽状态。

    任一行校验未通过则整批拒写，失败原因逐条返回；同一批号同一单据时间只入账一次，
    失败重试时已入账行自动跳过，不会重复扣减。请求体为 CSV 文本（text/csv）。
    """
    body = (await request.body()).decode("utf-8-sig").strip()
    if not body:
        raise HTTPException(status_code=400, detail="导入文件为空，请选择包含表头的 CSV 文件")
    reader = csv.DictReader(io.StringIO(body))
    headers = reader.fieldnames or []
    missing = [column for column in IMPORT_REQUIRED_COLUMNS if column not in headers]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"导入文件缺少必填表头：{'、'.join(missing)}；应为：{'、'.join(IMPORT_COLUMNS)}",
        )
    records = [dict(row) for row in reader]
    try:
        result = service.import_documents(records)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return ReagentImportResult(**result)


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
