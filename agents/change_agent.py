"""变更审批 Agent — 风险评估 + 爆炸半径 + 审批门控 + 审计日志

核心功能：
1. 对自愈 Agent 提出的修复方案进行风险评估
2. 计算爆炸半径：评估变更影响范围
3. 自动审批 / 人工审批门控
4. 完整审计日志记录

面试重点：
- 审批策略：L0 自动通过 / L1 需要 oncall 确认 / L2 需要 TL 审批
- 风险评分模型：综合爆炸半径、变更类型、时间窗口、历史成功率
- 审计日志：不可篡改的操作记录，满足 SOC2 合规
- RBAC：不同角色拥有不同审批权限
"""

import logging
from datetime import datetime
from typing import Any, Optional

from agents.base_agent import BaseAgent
from core.event_bus import EventBus
from models.events import (
    AgentType,
    ChangeEvent,
    EventType,
    HealLevel,
    IncidentState,
)

logger = logging.getLogger(__name__)


class RiskScorer:
    """风险评分模型

    综合多维度因素计算变更风险分数 (0-1)：
    - 爆炸半径权重: 0.30
    - 操作类型权重: 0.25
    - 时间窗口权重: 0.20
    - 历史成功率权重: 0.15
    - 服务关键度权重: 0.10
    """

    OPERATION_RISK = {
        "restart_pod": 0.2,
        "scale_up": 0.15,
        "rate_limit": 0.1,
        "circuit_breaker": 0.1,
        "rollback_config": 0.5,
        "rollback": 0.6,
        "heap_dump": 0.05,
    }

    CRITICAL_SERVICES = {
        "payment-service": 1.0,
        "order-service": 0.9,
        "user-service": 0.8,
        "inventory-service": 0.7,
    }

    def compute(
        self,
        action_type: str,
        blast_radius: float,
        target_service: str,
        hour: int,
    ) -> float:
        op_risk = self.OPERATION_RISK.get(action_type, 0.5)
        svc_criticality = self.CRITICAL_SERVICES.get(target_service, 0.5)

        # 非工作时间风险加成（凌晨/周末操作风险更高，因为响应人力少）
        time_risk = 0.3 if (hour < 8 or hour > 22) else 0.1

        # 模拟历史成功率（实际应从数据库查询）
        history_risk = 0.1

        score = (
            0.30 * blast_radius
            + 0.25 * op_risk
            + 0.20 * time_risk
            + 0.15 * history_risk
            + 0.10 * svc_criticality
        )
        return round(min(score, 1.0), 3)


class AuditLogger:
    """审计日志记录器

    面试要点：
    - 所有审批操作必须记录，不可篡改
    - 包含：谁(who)、什么时候(when)、做了什么(what)、为什么(why)
    - 生产环境可写入只追加的日志存储（如 Elasticsearch/Loki）
    """

    def __init__(self):
        self._logs: list[dict[str, Any]] = []

    def log(
        self,
        action: str,
        actor: str,
        target: str,
        reason: str,
        metadata: Optional[dict] = None,
    ) -> dict[str, Any]:
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action,
            "actor": actor,
            "target": target,
            "reason": reason,
            "metadata": metadata or {},
        }
        self._logs.append(entry)
        logger.info(f"[Audit] {action} by {actor} on {target}: {reason}")
        return entry

    def get_logs(self) -> list[dict[str, Any]]:
        return self._logs.copy()


class ChangeAgent(BaseAgent):
    """变更审批 Agent"""

    def __init__(
        self,
        event_bus: EventBus,
        auto_approve_threshold: float = 0.3,
    ):
        super().__init__(AgentType.CHANGE, event_bus, "ChangeAgent")
        self._scorer = RiskScorer()
        self._audit = AuditLogger()
        self._auto_approve_threshold = auto_approve_threshold

    async def process(self, state: IncidentState) -> IncidentState:
        heal = state.heal_event
        if not heal:
            logger.warning("[ChangeAgent] No heal event to review")
            return state

        current_hour = datetime.utcnow().hour
        risk_score = self._scorer.compute(
            action_type=heal.action_type,
            blast_radius=heal.blast_radius,
            target_service=heal.target_service,
            hour=current_hour,
        )

        approval_status, approver, reason = self._make_decision(
            heal.heal_level, risk_score, heal.action_type
        )

        self._audit.log(
            action=f"change_{approval_status}",
            actor=approver,
            target=heal.target_service,
            reason=reason,
            metadata={
                "risk_score": risk_score,
                "action_type": heal.action_type,
                "heal_level": heal.heal_level.value,
                "blast_radius": heal.blast_radius,
                "incident_id": state.incident_id,
            },
        )

        event_type = (
            EventType.CHANGE_APPROVED
            if approval_status == "approved"
            else EventType.CHANGE_REJECTED
        )

        change_event = ChangeEvent(
            event_type=event_type,
            heal_event_id=heal.event_id,
            risk_score=risk_score,
            approval_status=approval_status,
            approver=approver,
            reason=reason,
            audit_log=self._audit.get_logs()[-5:],
            correlation_id=state.incident_id,
        )

        state.change_event = change_event

        if approval_status == "approved":
            state.status = "resolved"
        else:
            state.status = "pending_approval"

        await self.event_bus.publish("aiops.audit", change_event)

        logger.info(
            f"[ChangeAgent] {approval_status.upper()}: {heal.action_type} "
            f"risk={risk_score:.3f} approver={approver}"
        )
        return state

    def _make_decision(
        self,
        heal_level: HealLevel,
        risk_score: float,
        action_type: str,
    ) -> tuple[str, str, str]:
        """审批决策逻辑"""
        if heal_level == HealLevel.L0_AUTO and risk_score <= self._auto_approve_threshold:
            return (
                "approved",
                "auto-system",
                f"L0 auto-approved: risk={risk_score:.3f} <= threshold={self._auto_approve_threshold}",
            )

        if heal_level == HealLevel.L1_SEMI:
            if risk_score <= 0.5:
                return (
                    "approved",
                    "oncall-engineer",
                    f"L1 approved by oncall: risk={risk_score:.3f}, action={action_type}",
                )
            return (
                "pending",
                "oncall-engineer",
                f"L1 pending review: risk={risk_score:.3f} requires manual check",
            )

        if heal_level == HealLevel.L2_MANUAL:
            return (
                "pending",
                "tech-lead",
                f"L2 requires TL approval: risk={risk_score:.3f}, action={action_type}",
            )

        if risk_score <= self._auto_approve_threshold:
            return (
                "approved",
                "auto-system",
                f"Low risk auto-approved: {risk_score:.3f}",
            )

        return (
            "pending",
            "oncall-engineer",
            f"Risk {risk_score:.3f} exceeds auto-approve threshold, manual review required",
        )

    def get_audit_logs(self) -> list[dict[str, Any]]:
        return self._audit.get_logs()
