# 知识图谱详解

## 为什么需要知识图谱？

传统运维排障靠经验："order-service CPU 高？可能是数据库慢，也可能是请求量大……"

知识图谱的方法：
1. 把所有服务关系存成图（谁依赖谁、谁部署在哪、谁影响谁）
2. 故障来了，沿着图的边去追踪
3. 找到最可能的根因节点

## 图数据模型

### 节点类型

| 类型 | 示例 | 属性 |
|------|------|------|
| Service | order-service | name, type, tier, namespace |
| Pod | order-svc-abc123 | name, status, cpu, memory |
| Node | node-1 | name, ip, capacity |
| Change | deploy-v2.3.1 | description, timestamp, author |

### 关系类型

| 关系 | 含义 | 示例 |
|------|------|------|
| DEPENDS_ON | 服务依赖 | order → payment |
| RUNS_ON | 部署关系 | order-pod → node-1 |
| MONITORS | 监控关系 | cpu_metric → order |
| CAUSED_BY | 因果关系 | cpu_alert → deploy-v2.3.1 |

## Neo4j Cypher 查询示例

### 查询服务依赖链

```cypher
MATCH path = (s:Service {name: "order-service"})-[:DEPENDS_ON*1..5]->(dep)
RETURN path
```

### 查询根因候选

```cypher
MATCH path = (s:Service {name: "order-service"})-[:DEPENDS_ON*1..5]->(root)
WHERE NOT (root)-[:DEPENDS_ON]->()
RETURN root.name AS root_cause, length(path) AS distance
ORDER BY distance ASC
```

### 关联近期变更

```cypher
MATCH (s:Service {name: "order-service"})-[:DEPENDS_ON*0..3]->(dep)
MATCH (c:Change)-[:AFFECTS]->(dep)
WHERE c.timestamp > datetime() - duration({hours: 24})
RETURN c.description, dep.name, c.timestamp
```

## BFS 遍历算法（面试手写）

```python
def reverse_bfs(graph, start, max_depth=5):
    result = []
    queue = deque([(start, 0)])
    visited = {start}
    
    while queue:
        node, depth = queue.popleft()
        if depth >= max_depth:
            continue
        
        deps = graph.get_dependencies(node)
        if not deps:
            result.append(node)  # 叶子节点 = 根因候选
            continue
        
        for dep in deps:
            if dep not in visited:
                visited.add(dep)
                result.append(dep)
                queue.append((dep, depth + 1))
    
    return result
```

时间复杂度：O(V + E)，空间复杂度：O(V)

## 面试高频问题

**Q: 为什么用图数据库不用关系型数据库？**
A: 多跳查询（3 层以上依赖链）图数据库性能远优于 SQL JOIN

**Q: 知识图谱数据从哪来？**
A: CMDB（资产管理）、K8s API、服务注册中心、APM 系统

**Q: 图谱怎么更新？**
A: 事件驱动——部署变更、配置修改等事件自动触发图谱更新
