# 事件驱动架构详解

## 什么是事件驱动架构？

传统架构（同步 RPC）：
```
A 调用 B → B 处理 → B 返回结果给 A → A 继续
问题：A 必须等 B 完成，B 挂了 A 也挂
```

事件驱动架构：
```
A 发布事件到消息总线 → A 继续做自己的事
B 从消息总线订阅事件 → B 自己处理
问题解耦：A 不知道 B 存在，B 挂了不影响 A
```

## 本项目的事件设计

### Topic 设计

| Topic | 生产者 | 消费者 | 内容 |
|-------|--------|--------|------|
| `aiops.alerts` | MonitorAgent | RCAAgent | 告警事件 |
| `aiops.events` | RCAAgent | HealAgent | 分析结果 |
| `aiops.commands` | HealAgent | 执行引擎 | 修复命令 |
| `aiops.audit` | ChangeAgent | 审计系统 | 审批记录 |
| `*.dlq` | 消费失败 | 运维团队 | 死信队列 |

### 事件模型

所有事件继承 `BaseEvent`：
```python
class BaseEvent(BaseModel):
    event_id: str         # 唯一标识
    event_type: EventType # 事件类型
    timestamp: datetime   # 时间戳
    source_agent: AgentType  # 来源 Agent
    correlation_id: str   # 关联 ID（同一故障链共用）
```

`correlation_id` 是关键：同一次故障处理产生的所有事件共享相同的 `correlation_id`，方便追踪整个处理链路。

### 双模实现

```python
# 工厂方法：根据环境选择实现
def create_event_bus(use_kafka=False):
    if use_kafka:
        return KafkaEventBus()     # 生产环境：Kafka
    return InMemoryEventBus()      # 本地开发：内存队列
```

面试加分点：这体现了**依赖倒置原则**（DIP）和**策略模式**。

## Kafka 核心概念（面试八股）

### Producer 关键配置
```
acks=all        → 所有副本确认才算发送成功（不丢消息）
retries=3       → 发送失败自动重试
idempotence=true → 幂等性（重试不会产生重复消息）
```

### Consumer 关键配置
```
enable.auto.commit=false  → 手动提交 offset（处理完再确认）
auto.offset.reset=latest  → 从最新消息开始消费
group.id=aiops-agents     → 消费组（同组内负载均衡）
```

### 死信队列 (DLQ)
消费失败的消息发送到 `topic.dlq`，避免阻塞正常消费：
```python
async def _send_to_dlq(self, topic, value, error):
    dlq_topic = f"{topic}.dlq"
    self._producer.produce(topic=dlq_topic, value=value)
```

## 面试必考问题

**Q: Kafka 如何保证消息不丢？**
A: Producer 端 `acks=all` + Consumer 端手动 commit + 消息持久化到磁盘

**Q: 如何保证消息不重复消费？**
A: 消费端做幂等处理（用 event_id 去重），或者使用 Kafka 事务

**Q: 背压怎么处理？**
A: Kafka 天然支持——Consumer 拉取模式，处理不过来就不拉
