"""知识图谱模块 — Neo4j 封装 + 图遍历根因分析

核心设计（面试重点）：

节点类型：
  - Service:  微服务（order-service, payment-service...）
  - Pod:      K8s Pod 实例
  - Node:     物理/虚拟机节点
  - Metric:   监控指标
  - Alert:    告警记录
  - Change:   变更记录

关系类型：
  - DEPENDS_ON:  服务依赖（order-service → payment-service）
  - RUNS_ON:     部署关系（Pod → Node）
  - MONITORS:    监控关系（Metric → Service）
  - TRIGGERED:   告警触发（Alert → Service）
  - CAUSED_BY:   因果关系（Alert → Change）

根因分析算法：
  1. 反向 BFS：从告警节点沿 DEPENDS_ON 反向遍历
  2. PageRank 变体：计算故障传播影响力
  3. 时间关联：变更记录时间 vs 告警时间的相关性

支持两种模式：
  - Neo4j 模式：连接真实 Neo4j 数据库
  - 内存模式：不依赖外部数据库，本地开发/面试 Demo 用
"""

import logging
from collections import defaultdict, deque
from datetime import datetime, timedelta
from typing import Any, Optional

logger = logging.getLogger(__name__)


class ServiceNode:
    """服务节点"""

    def __init__(
        self,
        name: str,
        service_type: str = "microservice",
        namespace: str = "production",
        labels: Optional[dict] = None,
    ):
        self.name = name
        self.service_type = service_type
        self.namespace = namespace
        self.labels = labels or {}


class Relationship:
    """关系边"""

    def __init__(
        self,
        source: str,
        target: str,
        rel_type: str,
        properties: Optional[dict] = None,
    ):
        self.source = source
        self.target = target
        self.rel_type = rel_type
        self.properties = properties or {}


class InMemoryKnowledgeGraph:
    """内存知识图谱 — 不依赖 Neo4j 的本地实现"""

    def __init__(self):
        self._nodes: dict[str, dict[str, Any]] = {}
        self._edges: list[Relationship] = []
        self._adjacency: dict[str, list[tuple[str, str, dict]]] = defaultdict(list)
        self._reverse_adjacency: dict[str, list[tuple[str, str, dict]]] = defaultdict(list)

    def add_node(self, name: str, node_type: str, properties: Optional[dict] = None) -> None:
        self._nodes[name] = {
            "name": name,
            "type": node_type,
            "properties": properties or {},
            "created_at": datetime.utcnow().isoformat(),
        }

    def add_relationship(
        self,
        source: str,
        target: str,
        rel_type: str,
        properties: Optional[dict] = None,
    ) -> None:
        rel = Relationship(source, target, rel_type, properties)
        self._edges.append(rel)
        self._adjacency[source].append((target, rel_type, properties or {}))
        self._reverse_adjacency[target].append((source, rel_type, properties or {}))

    def get_node(self, name: str) -> Optional[dict[str, Any]]:
        return self._nodes.get(name)

    def get_dependencies(self, service: str) -> list[str]:
        """获取某服务的所有直接依赖"""
        return [
            target for target, rel_type, _ in self._adjacency.get(service, [])
            if rel_type == "DEPENDS_ON"
        ]

    def get_dependents(self, service: str) -> list[str]:
        """获取依赖某服务的所有上游服务（反向查询）"""
        return [
            source for source, rel_type, _ in self._reverse_adjacency.get(service, [])
            if rel_type == "DEPENDS_ON"
        ]

    def bfs_trace(self, start: str, rel_type: str = "DEPENDS_ON", max_depth: int = 5) -> list[list[str]]:
        """BFS 遍历，返回从 start 出发的所有路径

        面试要点：时间复杂度 O(V+E)，空间复杂度 O(V)
        """
        paths = []
        queue: deque[tuple[str, list[str], int]] = deque()
        queue.append((start, [start], 0))
        visited = {start}

        while queue:
            current, path, depth = queue.popleft()
            if depth >= max_depth:
                continue

            neighbors = [
                target for target, rt, _ in self._adjacency.get(current, [])
                if rt == rel_type
            ]

            if not neighbors:
                paths.append(path)
                continue

            for neighbor in neighbors:
                if neighbor not in visited:
                    visited.add(neighbor)
                    new_path = path + [neighbor]
                    queue.append((neighbor, new_path, depth + 1))
                    paths.append(new_path)

        return paths

    def reverse_bfs_trace(
        self, start: str, rel_type: str = "DEPENDS_ON", max_depth: int = 5
    ) -> list[str]:
        """反向 BFS：从告警节点找到所有可能的根因源

        面试要点：根因分析的核心算法之一
        - 从告警服务出发，沿依赖关系反向遍历
        - 找到叶子节点（没有进一步依赖的节点）作为根因候选
        """
        result = []
        queue: deque[tuple[str, int]] = deque()
        queue.append((start, 0))
        visited = {start}

        while queue:
            current, depth = queue.popleft()
            if depth >= max_depth:
                continue

            deps = self.get_dependencies(current)

            if not deps:
                result.append(current)
                continue

            for dep in deps:
                if dep not in visited:
                    visited.add(dep)
                    result.append(dep)
                    queue.append((dep, depth + 1))

        return result

    def find_recent_changes(self, service: str, within_hours: int = 24) -> list[dict]:
        """查询某服务及其依赖的近期变更"""
        changes = []
        affected = [service] + self.get_dependencies(service)
        for svc in affected:
            node = self._nodes.get(svc, {})
            for change in node.get("properties", {}).get("recent_changes", []):
                changes.append({"service": svc, "change": change})
        return changes

    def compute_impact_score(self, service: str) -> float:
        """计算服务的影响力得分（简化版 PageRank）

        面试要点：
        - 被越多服务依赖的节点，影响力越大
        - 类似 PageRank 的思想，但简化为一步传播
        """
        dependents = self.get_dependents(service)
        total_services = max(len(self._nodes), 1)
        return len(dependents) / total_services

    def get_topology_summary(self) -> dict[str, Any]:
        return {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "node_types": defaultdict(int),
            "nodes": list(self._nodes.keys()),
        }


class Neo4jKnowledgeGraph:
    """Neo4j 知识图谱 — 生产环境使用

    面试要点：
    - 使用 Cypher 查询语言
    - 图数据库适合多跳查询（比关系型数据库高效）
    - 典型查询：MATCH (s:Service)-[:DEPENDS_ON*1..5]->(d) WHERE s.name = $name RETURN d
    """

    def __init__(self, uri: str, user: str, password: str):
        from neo4j import GraphDatabase
        self._driver = GraphDatabase.driver(uri, auth=(user, password))

    def close(self) -> None:
        self._driver.close()

    def init_schema(self) -> None:
        """初始化图模式（索引和约束）"""
        with self._driver.session() as session:
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (s:Service) REQUIRE s.name IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (p:Pod) REQUIRE p.name IS UNIQUE")
            session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (n:Node) REQUIRE n.name IS UNIQUE")
            session.run("CREATE INDEX IF NOT EXISTS FOR (a:Alert) ON (a.timestamp)")

    def add_service(self, name: str, properties: Optional[dict] = None) -> None:
        props = properties or {}
        with self._driver.session() as session:
            session.run(
                "MERGE (s:Service {name: $name}) SET s += $props",
                name=name, props=props,
            )

    def add_dependency(self, source: str, target: str) -> None:
        with self._driver.session() as session:
            session.run(
                """
                MATCH (s:Service {name: $source})
                MATCH (t:Service {name: $target})
                MERGE (s)-[:DEPENDS_ON]->(t)
                """,
                source=source, target=target,
            )

    def find_root_causes(self, service: str, max_depth: int = 5) -> list[dict]:
        """Cypher 查询根因候选"""
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH path = (s:Service {name: $service})-[:DEPENDS_ON*1..$max_depth]->(root)
                WHERE NOT (root)-[:DEPENDS_ON]->()
                RETURN root.name AS root_cause,
                       length(path) AS distance,
                       [n IN nodes(path) | n.name] AS path
                ORDER BY distance ASC
                """,
                service=service, max_depth=max_depth,
            )
            return [dict(record) for record in result]

    def find_recent_changes(self, service: str, hours: int = 24) -> list[dict]:
        """查询关联变更"""
        with self._driver.session() as session:
            result = session.run(
                """
                MATCH (s:Service {name: $service})-[:DEPENDS_ON*0..3]->(dep)
                MATCH (c:Change)-[:AFFECTS]->(dep)
                WHERE c.timestamp > datetime() - duration({hours: $hours})
                RETURN c.description AS change, dep.name AS service, c.timestamp AS time
                ORDER BY c.timestamp DESC
                """,
                service=service, hours=hours,
            )
            return [dict(record) for record in result]


def create_demo_knowledge_graph() -> InMemoryKnowledgeGraph:
    """创建演示用的知识图谱（含预设拓扑数据）"""
    kg = InMemoryKnowledgeGraph()

    services = {
        "api-gateway": {"type": "gateway", "tier": "frontend"},
        "order-service": {"type": "microservice", "tier": "backend", "recent_changes": ["deploy v2.3.1"]},
        "payment-service": {"type": "microservice", "tier": "backend"},
        "inventory-service": {"type": "microservice", "tier": "backend", "recent_changes": ["config: max_conn 100→200"]},
        "user-service": {"type": "microservice", "tier": "backend"},
        "notification-service": {"type": "microservice", "tier": "backend"},
        "mysql-primary": {"type": "database", "tier": "data"},
        "mysql-replica": {"type": "database", "tier": "data"},
        "redis-cache": {"type": "cache", "tier": "data"},
        "elasticsearch": {"type": "search", "tier": "data"},
        "kafka-broker": {"type": "messaging", "tier": "infra"},
    }

    for name, props in services.items():
        kg.add_node(name, node_type=props["type"], properties=props)

    dependencies = [
        ("api-gateway", "order-service", "DEPENDS_ON"),
        ("api-gateway", "user-service", "DEPENDS_ON"),
        ("api-gateway", "inventory-service", "DEPENDS_ON"),
        ("order-service", "payment-service", "DEPENDS_ON"),
        ("order-service", "inventory-service", "DEPENDS_ON"),
        ("order-service", "user-service", "DEPENDS_ON"),
        ("order-service", "kafka-broker", "DEPENDS_ON"),
        ("payment-service", "mysql-primary", "DEPENDS_ON"),
        ("payment-service", "redis-cache", "DEPENDS_ON"),
        ("inventory-service", "mysql-primary", "DEPENDS_ON"),
        ("inventory-service", "elasticsearch", "DEPENDS_ON"),
        ("user-service", "mysql-replica", "DEPENDS_ON"),
        ("user-service", "redis-cache", "DEPENDS_ON"),
        ("notification-service", "kafka-broker", "DEPENDS_ON"),
        ("mysql-replica", "mysql-primary", "DEPENDS_ON"),
    ]

    for source, target, rel_type in dependencies:
        kg.add_relationship(source, target, rel_type)

    node_deployments = [
        ("order-service", "node-1", "RUNS_ON"),
        ("payment-service", "node-2", "RUNS_ON"),
        ("inventory-service", "node-1", "RUNS_ON"),
        ("user-service", "node-3", "RUNS_ON"),
        ("mysql-primary", "node-2", "RUNS_ON"),
        ("redis-cache", "node-3", "RUNS_ON"),
    ]

    for svc, node, rel_type in node_deployments:
        kg.add_node(node, "host")
        kg.add_relationship(svc, node, rel_type)

    return kg
