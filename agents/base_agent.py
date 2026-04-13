"""Agent 基类 — 所有 Agent 的公共抽象

设计模式：模板方法模式
- 定义 Agent 生命周期：initialize → process → post_process
- 子类只需实现 process 方法即可
- 内置指标采集、日志、错误处理
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

from models.events import AgentType, BaseEvent, IncidentState
from core.event_bus import EventBus

logger = logging.getLogger(__name__)


class BaseAgent(ABC):
    """Agent 抽象基类"""

    def __init__(
        self,
        agent_type: AgentType,
        event_bus: EventBus,
        name: Optional[str] = None,
    ):
        self.agent_type = agent_type
        self.name = name or agent_type.value
        self.event_bus = event_bus
        self._metrics = {
            "processed_count": 0,
            "error_count": 0,
            "avg_latency_ms": 0.0,
        }

    async def handle(self, state: IncidentState) -> IncidentState:
        """模板方法：统一的 Agent 执行流程"""
        start_time = datetime.utcnow()
        logger.info(f"[{self.name}] Processing incident {state.incident_id}")

        try:
            state.current_agent = self.agent_type
            state.updated_at = datetime.utcnow()

            state = await self.process(state)

            self._metrics["processed_count"] += 1
            elapsed = (datetime.utcnow() - start_time).total_seconds() * 1000
            self._update_avg_latency(elapsed)
            logger.info(f"[{self.name}] Completed in {elapsed:.1f}ms")

        except Exception as e:
            self._metrics["error_count"] += 1
            state.error_message = f"[{self.name}] Error: {str(e)}"
            logger.error(f"[{self.name}] Failed: {e}", exc_info=True)

        return state

    @abstractmethod
    async def process(self, state: IncidentState) -> IncidentState:
        """子类实现的核心处理逻辑"""

    def _update_avg_latency(self, new_latency: float) -> None:
        count = self._metrics["processed_count"]
        old_avg = self._metrics["avg_latency_ms"]
        self._metrics["avg_latency_ms"] = old_avg + (new_latency - old_avg) / count

    def get_metrics(self) -> dict[str, Any]:
        return {
            "agent": self.name,
            "type": self.agent_type.value,
            **self._metrics,
        }
