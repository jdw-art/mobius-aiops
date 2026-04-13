"""事件驱动架构的核心数据模型

所有 Agent 间通信都基于这些事件模型，通过 Kafka 事件总线传递。
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field
import uuid


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AlertStatus(str, Enum):
    FIRING = "firing"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


class AgentType(str, Enum):
    MONITOR = "monitor"
    RCA = "rca"
    HEAL = "heal"
    CHANGE = "change"
    ORCHESTRATOR = "orchestrator"


class EventType(str, Enum):
    ALERT_FIRED = "alert.fired"
    ALERT_RESOLVED = "alert.resolved"
    RCA_STARTED = "rca.started"
    RCA_COMPLETED = "rca.completed"
    HEAL_PROPOSED = "heal.proposed"
    HEAL_EXECUTING = "heal.executing"
    HEAL_COMPLETED = "heal.completed"
    HEAL_FAILED = "heal.failed"
    CHANGE_REQUESTED = "change.requested"
    CHANGE_APPROVED = "change.approved"
    CHANGE_REJECTED = "change.rejected"


class HealLevel(str, Enum):
    """自愈分级策略"""
    L0_AUTO = "L0"       # 全自动，无需确认
    L1_SEMI = "L1"       # 半自动，需确认
    L2_MANUAL = "L2"     # 人工介入


class BaseEvent(BaseModel):
    event_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    event_type: EventType
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source_agent: AgentType
    correlation_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    metadata: dict[str, Any] = Field(default_factory=dict)


class AlertEvent(BaseEvent):
    """监控告警 Agent 产生的告警事件"""
    event_type: EventType = EventType.ALERT_FIRED
    source_agent: AgentType = AgentType.MONITOR

    alert_name: str
    severity: Severity
    status: AlertStatus = AlertStatus.FIRING
    source: str                        # 告警源（如 prometheus, loki）
    target_service: str                # 受影响服务
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None
    threshold: Optional[float] = None
    description: str = ""
    labels: dict[str, str] = Field(default_factory=dict)


class RCAEvent(BaseEvent):
    """根因分析 Agent 产生的分析结果事件"""
    event_type: EventType = EventType.RCA_COMPLETED
    source_agent: AgentType = AgentType.RCA

    alert_event_id: str                # 关联的原始告警
    root_cause: str                    # 根因描述
    confidence: float                  # 置信度 0-1
    affected_services: list[str]       # 受影响的服务链路
    evidence: list[dict[str, Any]]     # 证据链
    suggested_actions: list[str]       # 建议修复动作


class HealEvent(BaseEvent):
    """故障自愈 Agent 产生的修复事件"""
    event_type: EventType = EventType.HEAL_PROPOSED
    source_agent: AgentType = AgentType.HEAL

    rca_event_id: str                  # 关联的根因分析
    heal_level: HealLevel
    action_type: str                   # 修复类型（restart_pod, scale_up, rollback...）
    action_params: dict[str, Any]      # 修复参数
    target_service: str
    estimated_impact: str              # 预估影响
    blast_radius: float                # 爆炸半径 (0-1)
    dry_run_result: Optional[str] = None
    execution_result: Optional[str] = None


class ChangeEvent(BaseEvent):
    """变更审批 Agent 产生的审批事件"""
    event_type: EventType = EventType.CHANGE_REQUESTED
    source_agent: AgentType = AgentType.CHANGE

    heal_event_id: str
    risk_score: float                  # 风险评分 0-1
    approval_status: str = "pending"   # pending / approved / rejected
    approver: str = ""                 # 审批人（auto 表示自动审批）
    reason: str = ""
    audit_log: list[dict[str, Any]] = Field(default_factory=list)


class IncidentState(BaseModel):
    """一次完整故障处理的全局状态（流经 Orchestrator）"""
    incident_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    status: str = "open"               # open / investigating / healing / resolved

    alert_event: Optional[AlertEvent] = None
    rca_event: Optional[RCAEvent] = None
    heal_event: Optional[HealEvent] = None
    change_event: Optional[ChangeEvent] = None

    current_agent: AgentType = AgentType.MONITOR
    retry_count: int = 0
    error_message: Optional[str] = None
