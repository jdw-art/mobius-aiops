# 八股文 — AIOps 多 Agent 面试核心知识点

> 按照面试频率排序，覆盖分布式系统、Agent 框架、时序分析、知识图谱、Kafka 等方向。

---

## 一、事件驱动架构（高频）

### 1. 事件驱动 vs 请求驱动（RPC）的区别？

| 维度 | 事件驱动 | 请求驱动(RPC) |
|------|----------|---------------|
| 耦合度 | 松耦合 | 紧耦合 |
| 通信方式 | 异步 | 同步 |
| 容错 | 消息持久化，可重试 | 调用失败需自建重试 |
| 扩展性 | 新增消费者无需改生产者 | 需修改调用方 |
| 一致性 | 最终一致性 | 强一致性（可选） |

### 2. 什么是背压（Backpressure）？如何处理？

背压：下游处理速度 < 上游产生速度，导致消息堆积。

处理方案：
- Kafka 天然支持：Consumer 主动 pull，处理不过来就不拉
- 限流：Producer 端 rate limiting
- 缓冲：增大消费者数量（同消费组内）
- 降级：非核心事件丢弃

### 3. 最终一致性怎么保证？

本项目采用的方案：
- correlation_id 关联同一链路的所有事件
- 幂等消费：用 event_id 去重
- 补偿机制：自愈失败时回滚
- 死信队列：消费失败的消息进 DLQ，人工介入

---

## 二、Kafka（高频）

### 4. Kafka 如何保证消息不丢？

三个环节：
1. **Producer**: `acks=all`，所有 ISR 副本确认
2. **Broker**: `min.insync.replicas=2`，至少两个副本
3. **Consumer**: 手动 commit offset，处理完再确认

### 5. Kafka 消费组的工作原理？

- 同一消费组内的消费者均分 partition
- 不同消费组各自独立消费所有 partition
- 一个 partition 只能被组内一个消费者消费
- 消费者数 > partition 数时，多余消费者空闲

### 6. Exactly-Once 语义怎么实现？

Kafka 原生方案：
- Producer 幂等性（`enable.idempotence=true`）
- 事务（Producer 和 Consumer 协调提交）

应用层方案（本项目用的）：
- 用 event_id 作为唯一键去重
- 消费处理 + offset 提交在同一事务内

### 7. 死信队列（DLQ）是什么？什么时候用？

消费失败（如反序列化错误、业务逻辑异常）的消息发送到 `topic.dlq`：
- 避免「毒丸消息」阻塞正常消费
- DLQ 消息由人工审核处理
- 需要记录原始 topic、失败原因、重试次数

---

## 三、Agent 框架（高频）

### 8. Orchestrator vs Choreography 编排模式？

**Orchestrator（中心编排）**：
- 一个中心节点控制所有 Agent 执行顺序
- 优点：流程清晰、易调试、支持事务
- 缺点：中心节点是单点
- 本项目采用此模式

**Choreography（去中心编排）**：
- 每个 Agent 通过事件自行决定是否执行
- 优点：无单点、更灵活
- 缺点：流程难追踪

### 9. 什么是 ReAct 范式？

Reasoning + Acting 的循环：
```
思考 → 决定行动 → 执行工具 → 观察结果 → 再思考 → ...
```
LLM Agent 的核心模式。我们的 RCA Agent 类似：分析告警 → 决定查询知识图谱 → 观察依赖关系 → 推理根因。

### 10. LangGraph 的核心概念？

- **Node**: 图中的节点，对应一个处理函数（Agent）
- **Edge**: 节点间的连接，可以是条件边
- **State**: 全局状态对象，在节点间流转
- **Checkpointer**: 状态持久化，支持断点恢复

---

## 四、时序异常检测（中频）

### 11. 3-Sigma、EWMA、Isolation Forest 各自适用场景？

| 算法 | 适用 | 不适用 |
|------|------|--------|
| 3-Sigma | 正态分布的突变检测 | 非正态、季节性数据 |
| EWMA | 趋势变化、缓慢漂移 | 突发尖峰 |
| Isolation Forest | 多维异常、无需假设分布 | 数据量小、实时性要求极高 |

### 12. 动态阈值 vs 静态阈值？

静态：CPU > 80% 报警。问题——大促期间 CPU 本来就高。
动态：根据历史数据学习"正常范围"，超出正常范围才报警。

实现方式：
- Prophet 预测 + 残差分析（残差超过 3σ 为异常）
- EWMA 滑动窗口（窗口内均值 ± 3 × 标准差）

### 13. 多算法投票机制的原理？

```
3-Sigma → 是否异常？→ 1票
EWMA    → 是否异常？→ 1票
IF      → 是否异常？→ 1票

至少 2/3 投票为异常 → 最终判定为异常
```
好处：减少误报（False Positive），不同算法互补。

---

## 五、知识图谱（中频）

### 14. 图数据库 vs 关系型数据库？

多跳查询性能对比（查 5 层依赖关系）：
- SQL (5 层 JOIN): 可能超时
- Neo4j (5 跳遍历): < 100ms

本质原因：图数据库存储的是指针（直接跳转），关系型需要索引扫描。

### 15. BFS vs DFS 在根因分析中的选择？

BFS（广度优先）：
- 先找最近的依赖，适合"就近排查"
- 本项目用 BFS，因为根因通常在直接依赖中

DFS（深度优先）：
- 先追踪到底层，适合深层依赖链分析
- 适合超大规模拓扑

### 16. 贝叶斯推理在根因分析中的应用？

```
P(根因|症状) = P(症状|根因) × P(根因) / P(症状)

先验 P(根因): 历史统计（如 30% 的 CPU 高是因为部署）
似然 P(症状|根因): 当前证据（有近期部署 → 似然=0.9）
后验 P(根因|症状): 最终置信度
```

---

## 六、安全与可靠性（中频）

### 17. 熔断器模式的三个状态？

```
CLOSED（关闭）：正常工作，统计失败次数
  → 失败 ≥ N 次 → OPEN
  
OPEN（打开）：拒绝所有请求
  → 超时后 → HALF_OPEN
  
HALF_OPEN（半开）：允许少量请求试探
  → 成功 → CLOSED
  → 失败 → OPEN
```

### 18. 什么是爆炸半径？如何评估？

爆炸半径 = 变更影响的服务/Pod 数量 / 总服务/Pod 数量

评估方法：
- 知识图谱查询：变更目标的所有下游依赖
- 经验值：restart_pod ≈ 5%, rollback ≈ 15%, 全量回滚 > 50%

### 19. dry-run 怎么实现？

原理：执行修复命令的"检查模式"，只验证不实际执行。

```bash
# Kubernetes 原生支持
kubectl apply -f deploy.yaml --dry-run=server

# Ansible
ansible-playbook playbook.yml --check

# 我们的实现：解析命令 → 语法检查 → 权限检查 → 返回模拟结果
```

---

## 七、分布式系统（高频通用）

### 20. CAP 定理？

- C (Consistency): 一致性
- A (Availability): 可用性
- P (Partition tolerance): 分区容错

三者只能满足两个。本项目选择 AP：
- Kafka 保证高可用 + 分区容错
- 通过最终一致性保证数据一致

### 21. Saga 模式？

分布式事务的一种方案，适合长流程：

```
Agent 1 成功 → Agent 2 成功 → Agent 3 失败
                                ↓
              Agent 2 补偿 ← Agent 3 补偿
```

本项目的事件处理流程就是一个 Saga：
- 每个 Agent 是一个本地事务
- 失败时通过编排器触发补偿（如回滚修复操作）

---

## 八、设计模式（Java 重点）

### 22. 本项目用了哪些设计模式？

1. **模板方法模式**: BaseAgent.handle() 定义骨架，子类实现 process()
2. **策略模式**: 不同 Agent 是不同策略，异常检测器也是策略
3. **观察者模式**: 事件总线 — publish/subscribe
4. **责任链模式**: 安全护栏链 — dry-run → 爆炸半径 → 熔断器 → 审批
5. **工厂方法模式**: create_event_bus() 根据环境创建不同实现
6. **状态模式**: 熔断器的 CLOSED/OPEN/HALF_OPEN

---

## 九、Go 特色（Go 岗位重点）

### 23. goroutine vs Java Thread？

- goroutine: ~2KB 栈，M:N 调度，创建成本极低
- Java Thread: ~1MB 栈，1:1 映射 OS 线程，创建成本高
- goroutine 适合高并发 I/O 密集场景（如运维平台同时监控大量服务）

### 24. channel 在 Agent 通信中的应用？

```go
alertCh := make(chan AlertEvent, 100)  // 缓冲 channel
healCh := make(chan HealAction, 100)

// Agent 间通过 channel 传递事件
go monitorAgent.Run(alertCh)   // 写入告警
go rcaAgent.Run(alertCh, healCh) // 消费告警，产出修复方案
```

### 25. sync.Map vs map + Mutex？

- `sync.Map`: 读多写少场景优化（内部用 read-only map + dirty map）
- `map + Mutex`: 写多场景更好
- 本项目用 `sync.Map` 存储检查点（读 > 写）
