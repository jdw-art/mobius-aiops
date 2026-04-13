"""根因分析 Agent — 知识图谱遍历 + 因果推断 + 多源关联

核心功能：
1. 从知识图谱获取服务拓扑，沿依赖链路追踪故障传播路径
2. 多源证据关联：指标异常 + 日志模式 + 变更记录
3. 贝叶斯推理计算根因置信度
4. 输出根因报告和建议修复动作

面试重点：
- 知识图谱节点：Service / Pod / Node / Metric / Alert
- 知识图谱边：DEPENDS_ON / RUNS_ON / MONITORS / CAUSES
- 图遍历策略：从告警节点反向 BFS，找到第一个「因」节点
- 贝叶斯推理：P(根因|症状) = P(症状|根因) * P(根因) / P(症状)
"""

import logging
from datetime import datetime
from typing import Any, Optional

from agents.base_agent import BaseAgent
from core.event_bus import EventBus
from models.events import (
    AgentType,
    AlertEvent,
    EventType,
    IncidentState,
    RCAEvent,
    Severity,
)

logger = logging.getLogger(__name__)


# 模拟的知识图谱数据（实际生产中从 Neo4j 查询）
MOCK_SERVICE_TOPOLOGY = {
    "order-service": {
        "depends_on": ["payment-service", "inventory-service", "user-service"],
        "runs_on": "node-1",
        "recent_changes": ["deploy v2.3.1 at 2026-04-05 14:00"],
    },
    "payment-service": {
        "depends_on": ["mysql-primary", "redis-cache"],
        "runs_on": "node-2",
        "recent_changes": [],
    },
    "inventory-service": {
        "depends_on": ["mysql-primary", "elasticsearch"],
        "runs_on": "node-1",
        "recent_changes": ["config change: max_connections 100→200"],
    },
    "user-service": {
        "depends_on": ["mysql-replica", "redis-cache"],
        "runs_on": "node-3",
        "recent_changes": [],
    },
    "mysql-primary": {
        "depends_on": [],
        "runs_on": "node-2",
        "recent_changes": [],
    },
    "redis-cache": {
        "depends_on": [],
        "runs_on": "node-3",
        "recent_changes": [],
    },
}

# 常见故障模式与根因的映射
FAULT_PATTERNS = {
    "high_cpu_usage": [
        {
            "root_cause": "上游服务请求量激增导致 CPU 过载",
            "evidence_pattern": "request_rate_increase",
            "base_probability": 0.35,
            "suggested_actions": ["scale_up", "rate_limit"],
        },
        {
            "root_cause": "内存泄漏导致 GC 频繁触发",
            "evidence_pattern": "memory_leak",
            "base_probability": 0.25,
            "suggested_actions": ["restart_pod", "heap_dump"],
        },
        {
            "root_cause": "近期代码部署引入性能退化",
            "evidence_pattern": "recent_deploy",
            "base_probability": 0.30,
            "suggested_actions": ["rollback", "profiling"],
        },
        {
            "root_cause": "下游服务响应慢导致线程池耗尽",
            "evidence_pattern": "downstream_slow",
            "base_probability": 0.10,
            "suggested_actions": ["circuit_breaker", "timeout_adjust"],
        },
    ],
    "high_memory_usage": [
        {
            "root_cause": "内存泄漏（未释放的对象引用）",
            "evidence_pattern": "memory_leak",
            "base_probability": 0.50,
            "suggested_actions": ["restart_pod", "heap_dump"],
        },
        {
            "root_cause": "缓存未设置过期策略",
            "evidence_pattern": "cache_overflow",
            "base_probability": 0.30,
            "suggested_actions": ["clear_cache", "set_ttl"],
        },
    ],
    "high_error_rate": [
        {
            "root_cause": "下游依赖服务不可用",
            "evidence_pattern": "dependency_down",
            "base_probability": 0.40,
            "suggested_actions": ["check_dependency", "circuit_breaker"],
        },
        {
            "root_cause": "近期配置变更导致异常",
            "evidence_pattern": "recent_config_change",
            "base_probability": 0.35,
            "suggested_actions": ["rollback_config", "review_change"],
        },
    ],
}


class BayesianReasoner:
    """贝叶斯推理引擎

    P(Cause|Evidence) = P(Evidence|Cause) * P(Cause) / P(Evidence)

    面试要点：
    - 先验概率 P(Cause) 来自历史故障统计
    - 似然 P(Evidence|Cause) 来自当前证据的匹配度
    - 后验概率就是最终的根因置信度
    """

    @staticmethod
    def compute_posterior(
        prior: float,
        likelihood: float,
        evidence_probability: float = 0.5,
    ) -> float:
        if evidence_probability == 0:
            return 0.0
        posterior = (likelihood * prior) / evidence_probability
        return min(posterior, 1.0)


class RCAAgent(BaseAgent):
    """根因分析 Agent"""

    def __init__(self, event_bus: EventBus, knowledge_graph=None):
        super().__init__(AgentType.RCA, event_bus, "RCAAgent")
        self._kg = knowledge_graph
        self._reasoner = BayesianReasoner()

    async def process(self, state: IncidentState) -> IncidentState:
        alert = state.alert_event
        if not alert:
            logger.warning("[RCAAgent] No alert event to analyze")
            return state

        logger.info(f"[RCAAgent] Analyzing alert: {alert.alert_name} on {alert.target_service}")

        affected_chain = self._trace_dependency_chain(alert.target_service)

        evidence = self._collect_evidence(alert, affected_chain)

        candidates = self._get_fault_candidates(alert.alert_name)

        root_cause, confidence, actions = self._bayesian_inference(
            candidates, evidence
        )

        rca_event = RCAEvent(
            alert_event_id=alert.event_id,
            root_cause=root_cause,
            confidence=confidence,
            affected_services=affected_chain,
            evidence=evidence,
            suggested_actions=actions,
            correlation_id=state.incident_id,
        )

        state.rca_event = rca_event
        await self.event_bus.publish("aiops.events", rca_event)

        logger.info(
            f"[RCAAgent] Root cause: {root_cause} (confidence: {confidence:.2f})"
        )
        return state

    def _trace_dependency_chain(
        self, service: str, depth: int = 0, max_depth: int = 5
    ) -> list[str]:
        """沿知识图谱追踪依赖链路（BFS）

        面试要点：反向 BFS 从告警服务出发，找到所有可能的上游依赖
        """
        if depth >= max_depth:
            return []

        chain = [service]
        topology = MOCK_SERVICE_TOPOLOGY.get(service, {})
        for dep in topology.get("depends_on", []):
            chain.extend(self._trace_dependency_chain(dep, depth + 1, max_depth))
        return chain

    def _collect_evidence(
        self, alert: AlertEvent, affected_chain: list[str]
    ) -> list[dict[str, Any]]:
        """多源证据收集"""
        evidence = []

        evidence.append({
            "type": "metric_anomaly",
            "source": "prometheus",
            "detail": f"{alert.metric_name}={alert.metric_value} (threshold: {alert.threshold})",
            "weight": 0.8,
        })

        for svc in affected_chain:
            topo = MOCK_SERVICE_TOPOLOGY.get(svc, {})
            for change in topo.get("recent_changes", []):
                evidence.append({
                    "type": "recent_change",
                    "source": "cmdb",
                    "detail": f"{svc}: {change}",
                    "weight": 0.9,
                })

        if alert.severity in (Severity.CRITICAL, Severity.HIGH):
            evidence.append({
                "type": "severity_context",
                "source": "alert",
                "detail": f"High severity alert: {alert.severity.value}",
                "weight": 0.5,
            })

        return evidence

    def _get_fault_candidates(self, alert_name: str) -> list[dict[str, Any]]:
        normalized = alert_name.replace("anomaly_", "")
        for pattern_key, candidates in FAULT_PATTERNS.items():
            if pattern_key in normalized or normalized in pattern_key:
                return candidates
        return FAULT_PATTERNS.get("high_cpu_usage", [])

    def _bayesian_inference(
        self,
        candidates: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
    ) -> tuple[str, float, list[str]]:
        """贝叶斯推理选出最可能的根因"""
        has_recent_change = any(e["type"] == "recent_change" for e in evidence)

        best_cause = "Unknown"
        best_confidence = 0.0
        best_actions = []

        for candidate in candidates:
            prior = candidate["base_probability"]

            likelihood = 0.5
            if candidate["evidence_pattern"] == "recent_deploy" and has_recent_change:
                likelihood = 0.9
            elif candidate["evidence_pattern"] == "recent_config_change" and has_recent_change:
                likelihood = 0.85
            elif candidate["evidence_pattern"] in ("memory_leak", "request_rate_increase"):
                likelihood = 0.6

            posterior = self._reasoner.compute_posterior(prior, likelihood)

            if posterior > best_confidence:
                best_confidence = posterior
                best_cause = candidate["root_cause"]
                best_actions = candidate["suggested_actions"]

        return best_cause, round(best_confidence, 3), best_actions
