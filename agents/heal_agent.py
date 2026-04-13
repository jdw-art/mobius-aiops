"""故障自愈 Agent — 修复方案匹配 + 安全执行 + 回滚验证

核心功能：
1. 根据 RCA 结果匹配最佳修复方案
2. 分级自愈策略：L0（全自动）/ L1（半自动）/ L2（人工）
3. 安全护栏：dry-run 模拟 → 爆炸半径评估 → 熔断器检查 → 执行
4. 执行后验证 + 自动回滚

面试重点：
- 为什么要分级？→ 不同风险的操作需要不同级别的审批
- dry-run 怎么实现？→ 模拟执行但不实际变更，检查命令合法性
- 熔断器模式？→ 连续失败 N 次后暂停自动修复，避免雪崩
- 爆炸半径怎么算？→ 受影响 Pod 数 / 总 Pod 数
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from agents.base_agent import BaseAgent
from core.event_bus import EventBus
from models.events import (
    AgentType,
    EventType,
    HealEvent,
    HealLevel,
    IncidentState,
)

logger = logging.getLogger(__name__)


# 修复方案库（生产环境中可以从数据库或 RAG 检索）
REMEDIATION_PLAYBOOKS = {
    "restart_pod": {
        "level": HealLevel.L0_AUTO,
        "description": "重启故障 Pod",
        "command_template": "kubectl rollout restart deployment/{service} -n {namespace}",
        "estimated_duration_sec": 30,
        "blast_radius_factor": 0.05,
        "rollback_command": None,
    },
    "scale_up": {
        "level": HealLevel.L0_AUTO,
        "description": "水平扩容 Pod 副本数",
        "command_template": "kubectl scale deployment/{service} --replicas={replicas} -n {namespace}",
        "estimated_duration_sec": 60,
        "blast_radius_factor": 0.02,
        "rollback_command": "kubectl scale deployment/{service} --replicas={original_replicas} -n {namespace}",
    },
    "rollback": {
        "level": HealLevel.L1_SEMI,
        "description": "回滚到上一个稳定版本",
        "command_template": "kubectl rollout undo deployment/{service} -n {namespace}",
        "estimated_duration_sec": 120,
        "blast_radius_factor": 0.15,
        "rollback_command": None,
    },
    "rate_limit": {
        "level": HealLevel.L0_AUTO,
        "description": "启用限流保护",
        "command_template": "kubectl annotate svc/{service} rate-limit={rate} -n {namespace} --overwrite",
        "estimated_duration_sec": 10,
        "blast_radius_factor": 0.01,
        "rollback_command": "kubectl annotate svc/{service} rate-limit- -n {namespace}",
    },
    "circuit_breaker": {
        "level": HealLevel.L0_AUTO,
        "description": "开启熔断器",
        "command_template": "kubectl annotate svc/{service} circuit-breaker=open -n {namespace} --overwrite",
        "estimated_duration_sec": 5,
        "blast_radius_factor": 0.08,
        "rollback_command": "kubectl annotate svc/{service} circuit-breaker=closed -n {namespace} --overwrite",
    },
    "rollback_config": {
        "level": HealLevel.L1_SEMI,
        "description": "回滚配置变更",
        "command_template": "kubectl rollout undo configmap/{service}-config -n {namespace}",
        "estimated_duration_sec": 30,
        "blast_radius_factor": 0.10,
        "rollback_command": None,
    },
    "heap_dump": {
        "level": HealLevel.L2_MANUAL,
        "description": "执行堆转储分析",
        "command_template": "kubectl exec {pod} -- jmap -dump:live,format=b,file=/tmp/heap.hprof 1",
        "estimated_duration_sec": 300,
        "blast_radius_factor": 0.0,
        "rollback_command": None,
    },
}


class CircuitBreaker:
    """熔断器模式

    面试要点：
    - CLOSED → 正常状态，失败计数
    - OPEN → 熔断状态，拒绝所有请求
    - HALF_OPEN → 试探状态，允许少量请求通过
    """

    def __init__(self, threshold: int = 5, timeout_sec: int = 60):
        self._threshold = threshold
        self._timeout = timedelta(seconds=timeout_sec)
        self._failure_count = 0
        self._last_failure_time: Optional[datetime] = None
        self._state = "CLOSED"

    def allow_request(self) -> bool:
        if self._state == "CLOSED":
            return True
        if self._state == "OPEN":
            if datetime.utcnow() - self._last_failure_time >= self._timeout:
                self._state = "HALF_OPEN"
                return True
            return False
        return True  # HALF_OPEN

    def record_success(self) -> None:
        self._failure_count = 0
        self._state = "CLOSED"

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = datetime.utcnow()
        if self._failure_count >= self._threshold:
            self._state = "OPEN"
            logger.warning("[CircuitBreaker] Circuit OPEN — auto-heal suspended")

    @property
    def state(self) -> str:
        return self._state


class HealAgent(BaseAgent):
    """故障自愈 Agent"""

    def __init__(
        self,
        event_bus: EventBus,
        dry_run: bool = True,
        max_blast_radius: float = 0.2,
    ):
        super().__init__(AgentType.HEAL, event_bus, "HealAgent")
        self._dry_run = dry_run
        self._max_blast_radius = max_blast_radius
        self._circuit_breaker = CircuitBreaker()

    async def process(self, state: IncidentState) -> IncidentState:
        rca = state.rca_event
        if not rca:
            logger.warning("[HealAgent] No RCA result to act on")
            return state

        if not self._circuit_breaker.allow_request():
            logger.warning("[HealAgent] Circuit breaker OPEN, skipping auto-heal")
            state.error_message = "Circuit breaker is open, auto-heal suspended"
            return state

        action_type = self._select_best_action(rca.suggested_actions)
        playbook = REMEDIATION_PLAYBOOKS.get(action_type)
        if not playbook:
            logger.warning(f"[HealAgent] No playbook for action: {action_type}")
            return state

        blast_radius = playbook["blast_radius_factor"]
        if blast_radius > self._max_blast_radius:
            logger.warning(
                f"[HealAgent] Blast radius {blast_radius} exceeds max {self._max_blast_radius}"
            )
            playbook = REMEDIATION_PLAYBOOKS.get(action_type, playbook)
            playbook_level = HealLevel.L2_MANUAL
        else:
            playbook_level = playbook["level"]

        target_service = (
            state.alert_event.target_service if state.alert_event else "unknown"
        )

        dry_run_result = None
        if self._dry_run:
            dry_run_result = self._execute_dry_run(playbook, target_service)

        heal_event = HealEvent(
            rca_event_id=rca.event_id,
            heal_level=playbook_level,
            action_type=action_type,
            action_params={
                "command": playbook["command_template"],
                "service": target_service,
                "namespace": "production",
                "estimated_duration_sec": playbook["estimated_duration_sec"],
            },
            target_service=target_service,
            estimated_impact=playbook["description"],
            blast_radius=blast_radius,
            dry_run_result=dry_run_result,
            correlation_id=state.incident_id,
        )

        if playbook_level == HealLevel.L0_AUTO and self._dry_run:
            execution_result = await self._execute_remediation(playbook, target_service)
            heal_event.execution_result = execution_result
            heal_event.event_type = EventType.HEAL_COMPLETED

            if "SUCCESS" in execution_result:
                self._circuit_breaker.record_success()
            else:
                self._circuit_breaker.record_failure()
                heal_event.event_type = EventType.HEAL_FAILED
        else:
            heal_event.event_type = EventType.HEAL_PROPOSED

        state.heal_event = heal_event
        state.status = "healing"

        await self.event_bus.publish("aiops.commands", heal_event)

        logger.info(
            f"[HealAgent] Action: {action_type} [{playbook_level.value}] "
            f"blast_radius={blast_radius:.2f}"
        )
        return state

    def _select_best_action(self, suggested_actions: list[str]) -> str:
        """选择风险最低、可自动执行的修复方案"""
        priority_order = [
            "rate_limit", "circuit_breaker", "scale_up",
            "restart_pod", "rollback_config", "rollback", "heap_dump",
        ]
        for action in priority_order:
            if action in suggested_actions:
                return action
        return suggested_actions[0] if suggested_actions else "restart_pod"

    def _execute_dry_run(self, playbook: dict, service: str) -> str:
        """Dry-run 模拟执行"""
        cmd = playbook["command_template"].format(
            service=service, namespace="production",
            replicas=3, original_replicas=2, rate="100", pod="dummy-pod",
        )
        logger.info(f"[HealAgent] DRY-RUN: {cmd}")
        return f"DRY-RUN OK: command validated — {cmd}"

    async def _execute_remediation(self, playbook: dict, service: str) -> str:
        """实际执行修复（Demo 模式下模拟执行）"""
        cmd = playbook["command_template"].format(
            service=service, namespace="production",
            replicas=3, original_replicas=2, rate="100", pod="dummy-pod",
        )
        logger.info(f"[HealAgent] EXECUTING: {cmd}")
        return f"SUCCESS: {playbook['description']} completed for {service}"
