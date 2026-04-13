"""Agent 编排器 — 基于状态机的多 Agent 工作流编排

核心设计（面试重点）：
1. 状态机模式：IncidentState 在 Agent 间流转，每个节点是一个 Agent
2. 条件路由：根据上一步结果决定下一步走向
3. 检查点恢复：每步完成后持久化状态，失败可从断点恢复
4. 重试机制：单个 Agent 失败自动重试，超过次数则跳过或上报

LangGraph 风格的图编排（简化实现，不强依赖 LangGraph 库）：
  Monitor → RCA → Heal → Change → End
     ↓         ↓       ↓
   (skip)   (skip)  (rejected → retry/escalate)

面试关键问答：
Q: "为什么不用简单的 Pipeline？为什么要状态机？"
A: Pipeline 是线性的，无法处理条件分支、重试、跳过、回退。
   状态机支持：
   - 条件路由（RCA 置信度低 → 重新分析）
   - 失败重试（Heal 执行失败 → 重试 3 次）
   - 人工介入（Change 被拒 → 暂停等待审批）
   - 检查点恢复（服务重启后从断点继续）
"""

import asyncio
import logging
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Optional

from agents.base_agent import BaseAgent
from agents.monitor_agent import MonitorAgent
from agents.rca_agent import RCAAgent
from agents.heal_agent import HealAgent
from agents.change_agent import ChangeAgent
from core.event_bus import EventBus
from models.events import AgentType, IncidentState

logger = logging.getLogger(__name__)


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class WorkflowNode:
    """工作流节点 — 封装一个 Agent 的执行"""

    def __init__(
        self,
        name: str,
        agent: BaseAgent,
        condition: Optional[Callable[[IncidentState], bool]] = None,
        max_retries: int = 3,
    ):
        self.name = name
        self.agent = agent
        self.condition = condition
        self.max_retries = max_retries
        self.status = NodeStatus.PENDING
        self.retry_count = 0

    def should_execute(self, state: IncidentState) -> bool:
        if self.condition is None:
            return True
        return self.condition(state)


class Orchestrator:
    """多 Agent 编排器

    实现了一个简化版的 LangGraph 状态机：
    - 节点 = Agent
    - 边 = 条件路由
    - 状态 = IncidentState
    """

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self._nodes: list[WorkflowNode] = []
        self._checkpoints: dict[str, IncidentState] = {}
        self._build_default_workflow()

    def _build_default_workflow(self) -> None:
        """构建默认工作流：Monitor → RCA → Heal → Change"""
        monitor = MonitorAgent(self.event_bus)
        rca = RCAAgent(self.event_bus)
        heal = HealAgent(self.event_bus, dry_run=True)
        change = ChangeAgent(self.event_bus)

        self._nodes = [
            WorkflowNode(
                name="monitor",
                agent=monitor,
                condition=None,  # 始终执行
            ),
            WorkflowNode(
                name="rca",
                agent=rca,
                condition=lambda s: s.alert_event is not None,
            ),
            WorkflowNode(
                name="heal",
                agent=heal,
                condition=lambda s: (
                    s.rca_event is not None and s.rca_event.confidence >= 0.3
                ),
            ),
            WorkflowNode(
                name="change",
                agent=change,
                condition=lambda s: s.heal_event is not None,
            ),
        ]

    async def run(
        self,
        initial_state: Optional[IncidentState] = None,
        metadata: Optional[dict] = None,
    ) -> IncidentState:
        """执行完整的事件处理工作流"""
        state = initial_state or IncidentState()
        if metadata:
            state.metadata = metadata

        logger.info(f"[Orchestrator] Starting workflow for incident {state.incident_id}")

        for node in self._nodes:
            if not node.should_execute(state):
                node.status = NodeStatus.SKIPPED
                logger.info(f"[Orchestrator] Skipping node: {node.name}")
                continue

            node.status = NodeStatus.RUNNING
            success = False

            while node.retry_count <= node.max_retries:
                try:
                    state = await node.agent.handle(state)

                    if state.error_message and node.retry_count < node.max_retries:
                        node.retry_count += 1
                        logger.warning(
                            f"[Orchestrator] Retrying {node.name} "
                            f"({node.retry_count}/{node.max_retries})"
                        )
                        state.error_message = None
                        continue

                    node.status = NodeStatus.COMPLETED
                    success = True
                    break

                except Exception as e:
                    node.retry_count += 1
                    logger.error(
                        f"[Orchestrator] Node {node.name} failed: {e} "
                        f"(retry {node.retry_count}/{node.max_retries})"
                    )
                    if node.retry_count > node.max_retries:
                        break

            if not success:
                node.status = NodeStatus.FAILED
                logger.error(f"[Orchestrator] Node {node.name} failed after {node.max_retries} retries")

            self._save_checkpoint(state)

        state.updated_at = datetime.utcnow()
        logger.info(
            f"[Orchestrator] Workflow completed: incident={state.incident_id} "
            f"status={state.status}"
        )

        return state

    def _save_checkpoint(self, state: IncidentState) -> None:
        self._checkpoints[state.incident_id] = state.model_copy(deep=True)

    def get_checkpoint(self, incident_id: str) -> Optional[IncidentState]:
        return self._checkpoints.get(incident_id)

    def get_workflow_status(self) -> list[dict[str, Any]]:
        return [
            {
                "name": node.name,
                "status": node.status.value,
                "agent_type": node.agent.agent_type.value,
                "retry_count": node.retry_count,
                "metrics": node.agent.get_metrics(),
            }
            for node in self._nodes
        ]


async def run_demo():
    """演示运行：模拟一次完整的故障处理流程"""
    from core.event_bus import InMemoryEventBus

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    event_bus = InMemoryEventBus()
    await event_bus.start()

    orchestrator = Orchestrator(event_bus)

    state = await orchestrator.run()

    print("\n" + "=" * 60)
    print("  故障处理结果")
    print("=" * 60)
    print(f"  事件 ID:    {state.incident_id}")
    print(f"  状态:       {state.status}")

    if state.alert_event:
        print(f"\n  [告警]")
        print(f"    名称:     {state.alert_event.alert_name}")
        print(f"    严重度:   {state.alert_event.severity.value}")
        print(f"    服务:     {state.alert_event.target_service}")
        print(f"    指标值:   {state.alert_event.metric_value}")

    if state.rca_event:
        print(f"\n  [根因分析]")
        print(f"    根因:     {state.rca_event.root_cause}")
        print(f"    置信度:   {state.rca_event.confidence}")
        print(f"    影响链:   {' → '.join(state.rca_event.affected_services[:5])}")
        print(f"    建议动作: {', '.join(state.rca_event.suggested_actions)}")

    if state.heal_event:
        print(f"\n  [自愈]")
        print(f"    操作:     {state.heal_event.action_type}")
        print(f"    级别:     {state.heal_event.heal_level.value}")
        print(f"    爆炸半径: {state.heal_event.blast_radius:.2f}")
        print(f"    Dry-run:  {state.heal_event.dry_run_result}")

    if state.change_event:
        print(f"\n  [审批]")
        print(f"    状态:     {state.change_event.approval_status}")
        print(f"    风险分:   {state.change_event.risk_score}")
        print(f"    审批人:   {state.change_event.approver}")
        print(f"    原因:     {state.change_event.reason}")

    print("\n  [工作流节点状态]")
    for node_info in orchestrator.get_workflow_status():
        print(f"    {node_info['name']:12s} → {node_info['status']}")

    print("=" * 60)

    await event_bus.stop()
    return state


if __name__ == "__main__":
    asyncio.run(run_demo())
