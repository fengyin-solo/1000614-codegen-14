"""接口出入参模型：列表分页、动作结果与各模块的明细结构。"""
from __future__ import annotations

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageResult(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int = 1
    size: int = 20


class ActionResult(BaseModel):
    ok: bool
    message: str
    entry: dict[str, Any] | None = None


class EntryPayload(BaseModel):
    """登记或修改一条业务记录时提交的字段集合。"""

    values: dict[str, Any] = Field(default_factory=dict)
    remark: str | None = None


class ImportPayload(BaseModel):
    """整批导入出入库单据时提交的行集合。"""

    rows: list[dict[str, Any]] = Field(default_factory=list)


class ImportRowError(BaseModel):
    """导入时被拒绝的单行：行号、逐条原因与原始内容。"""

    row: int
    reasons: list[str]
    values: dict[str, Any] = Field(default_factory=dict)


class ImportResult(BaseModel):
    """整批导入结果：入账、重复跳过与拒绝三段的汇总。"""

    ok: bool
    message: str
    total: int = 0
    posted: int = 0
    duplicated: int = 0
    rejected: int = 0
    errors: list[ImportRowError] = Field(default_factory=list)
    entries: list[dict[str, Any]] = Field(default_factory=list)



class SampleEntry(BaseModel):
    """样品明细结构。"""

    field_0: str | None = None  # 样品编号
    field_1: str | None = None  # 样品名称
    field_2: str | None = None  # 样品类别
    field_3: str | None = None  # 送检单位
    field_4: str | None = None  # 送检人
    field_5: str | None = None  # 接收日期
    field_6: str | None = None  # 保存条件
    field_7: str | None = None  # 样品状态

class ClientEntry(BaseModel):
    """委托单位明细结构。"""

    field_0: str | None = None  # 单位编码
    field_1: str | None = None  # 单位名称
    field_2: str | None = None  # 单位类型
    field_3: str | None = None  # 联系人
    field_4: str | None = None  # 联系电话
    field_5: str | None = None  # 结算方式
    field_6: str | None = None  # 资质编号
    field_7: str | None = None  # 单位状态

class ProjectEntry(BaseModel):
    """检测项目明细结构。"""

    field_0: str | None = None  # 项目编码
    field_1: str | None = None  # 项目名称
    field_2: str | None = None  # 检测方法
    field_3: str | None = None  # 方法标准号
    field_4: str | None = None  # 检出限
    field_5: str | None = None  # 计量单位
    field_6: str | None = None  # 收费单价
    field_7: str | None = None  # 项目状态

class TaskEntry(BaseModel):
    """检测任务明细结构。"""

    field_0: str | None = None  # 任务编号
    field_1: str | None = None  # 关联样品
    field_2: str | None = None  # 检测项目
    field_3: str | None = None  # 承检人员
    field_4: str | None = None  # 计划完成日
    field_5: str | None = None  # 实际完成日
    field_6: str | None = None  # 任务优先级
    field_7: str | None = None  # 任务状态

class ExecuteEntry(BaseModel):
    """执行记录明细结构。"""

    field_0: str | None = None  # 记录编号
    field_1: str | None = None  # 关联任务
    field_2: str | None = None  # 前处理方式
    field_3: str | None = None  # 检测条件
    field_4: str | None = None  # 原始记录号
    field_5: str | None = None  # 执行人员
    field_6: str | None = None  # 执行时间
    field_7: str | None = None  # 执行状态

class ResultEntry(BaseModel):
    """检测结果明细结构。"""

    field_0: str | None = None  # 结果编号
    field_1: str | None = None  # 关联任务
    field_2: str | None = None  # 检测值
    field_3: str | None = None  # 计量单位
    field_4: str | None = None  # 检出限
    field_5: str | None = None  # 判定结论
    field_6: str | None = None  # 录入人员
    field_7: str | None = None  # 结果状态

class ReviewEntry(BaseModel):
    """复核记录明细结构。"""

    field_0: str | None = None  # 复核编号
    field_1: str | None = None  # 关联结果
    field_2: str | None = None  # 复核项目
    field_3: str | None = None  # 复核人
    field_4: str | None = None  # 复核意见
    field_5: str | None = None  # 复核时间
    field_6: str | None = None  # 差异说明
    field_7: str | None = None  # 复核状态

class InstrumentEntry(BaseModel):
    """仪器设备明细结构。"""

    field_0: str | None = None  # 设备编号
    field_1: str | None = None  # 设备名称
    field_2: str | None = None  # 设备型号
    field_3: str | None = None  # 量程范围
    field_4: str | None = None  # 校准周期
    field_5: str | None = None  # 校准到期日
    field_6: str | None = None  # 责任人
    field_7: str | None = None  # 设备状态

class CalibrationEntry(BaseModel):
    """校准记录明细结构。"""

    field_0: str | None = None  # 校准编号
    field_1: str | None = None  # 关联设备
    field_2: str | None = None  # 校准方式
    field_3: str | None = None  # 标准物质
    field_4: str | None = None  # 校准结果
    field_5: str | None = None  # 校准日期
    field_6: str | None = None  # 下次校准日
    field_7: str | None = None  # 校准状态

class ReagentEntry(BaseModel):
    """试剂物料明细结构。"""

    field_0: str | None = None  # 物料编号
    field_1: str | None = None  # 物料名称
    field_2: str | None = None  # 规格纯度
    field_3: str | None = None  # 批号
    field_4: str | None = None  # 结存数量
    field_5: str | None = None  # 有效期至
    field_6: str | None = None  # 保管人员
    field_7: str | None = None  # 物料状态

class ConsumeEntry(BaseModel):
    """领用单明细结构。"""

    field_0: str | None = None  # 领用单号
    field_1: str | None = None  # 物料名称
    field_2: str | None = None  # 领用数量
    field_3: str | None = None  # 领用人员
    field_4: str | None = None  # 领用日期
    field_5: str | None = None  # 用途说明
    field_6: str | None = None  # 所属科室
    field_7: str | None = None  # 领用状态

class EnvironmentEntry(BaseModel):
    """环境记录明细结构。"""

    field_0: str | None = None  # 记录编号
    field_1: str | None = None  # 监控区域
    field_2: str | None = None  # 温度值
    field_3: str | None = None  # 湿度值
    field_4: str | None = None  # 压差值
    field_5: str | None = None  # 采集时间
    field_6: str | None = None  # 记录人员
    field_7: str | None = None  # 监控状态

class ReportEntry(BaseModel):
    """检测报告明细结构。"""

    field_0: str | None = None  # 报告编号
    field_1: str | None = None  # 关联样品
    field_2: str | None = None  # 报告类型
    field_3: str | None = None  # 编制人员
    field_4: str | None = None  # 审核人员
    field_5: str | None = None  # 签发人员
    field_6: str | None = None  # 出具日期
    field_7: str | None = None  # 报告状态

class IssueEntry(BaseModel):
    """变更记录明细结构。"""

    field_0: str | None = None  # 变更编号
    field_1: str | None = None  # 关联报告
    field_2: str | None = None  # 变更类型
    field_3: str | None = None  # 变更原因
    field_4: str | None = None  # 申请人
    field_5: str | None = None  # 批准人
    field_6: str | None = None  # 变更日期
    field_7: str | None = None  # 变更状态

class QcEntry(BaseModel):
    """质控记录明细结构。"""

    field_0: str | None = None  # 质控编号
    field_1: str | None = None  # 质控类型
    field_2: str | None = None  # 关联项目
    field_3: str | None = None  # 质控结果
    field_4: str | None = None  # 偏差范围
    field_5: str | None = None  # 判定结论
    field_6: str | None = None  # 质控人员
    field_7: str | None = None  # 质控状态

class ComplaintEntry(BaseModel):
    """投诉记录明细结构。"""

    field_0: str | None = None  # 投诉编号
    field_1: str | None = None  # 投诉单位
    field_2: str | None = None  # 投诉事由
    field_3: str | None = None  # 涉及样品
    field_4: str | None = None  # 受理人员
    field_5: str | None = None  # 处理措施
    field_6: str | None = None  # 处理期限
    field_7: str | None = None  # 投诉状态

class StockinEntry(BaseModel):
    """流转记录明细结构。"""

    field_0: str | None = None  # 流转编号
    field_1: str | None = None  # 关联样品
    field_2: str | None = None  # 流转环节
    field_3: str | None = None  # 交接人
    field_4: str | None = None  # 接收人
    field_5: str | None = None  # 交接时间
    field_6: str | None = None  # 存放位置
    field_7: str | None = None  # 流转状态

class SettlementEntry(BaseModel):
    """结算单明细结构。"""

    field_0: str | None = None  # 结算单号
    field_1: str | None = None  # 委托单位
    field_2: str | None = None  # 结算周期
    field_3: str | None = None  # 检测项数
    field_4: str | None = None  # 应收金额
    field_5: str | None = None  # 已收金额
    field_6: str | None = None  # 开票状态
    field_7: str | None = None  # 结算状态
