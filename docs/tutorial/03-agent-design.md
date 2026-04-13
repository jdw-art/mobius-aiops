# Agent 设计模式详解

## Agent 的核心抽象

每个 Agent 遵循统一的生命周期：

```
接收状态 → 前置检查 → 核心处理 → 指标采集 → 返回状态
```

### Python 实现：ABC 抽象类

```python
class BaseAgent(ABC):
    async def handle(self, state):  # 模板方法
        state = await self.process(state)  # 子类实现
        return state

    @abstractmethod
    async def process(self, state):
        """子类必须实现"""
```

### Java 实现：abstract class

```java
public abstract class BaseAgent {
    public IncidentState handle(IncidentState state) {
        return process(state);
    }
    protected abstract IncidentState process(IncidentState state);
}
```

### Go 实现：interface + 组合

```go
type Agent interface {
    Name() string
    Handle(state *IncidentState) *IncidentState
}
// Go 没有抽象类，用函数包装实现模板方法
func WrapHandle(name string, processFn func(*IncidentState) *IncidentState, state *IncidentState) *IncidentState {
    return processFn(state)
}
```

## 四大 Agent 详解

### 1. MonitorAgent — 时序异常检测

**核心算法：多算法投票**

```
3-Sigma → 投票 1
EWMA    → 投票 2     至少 2/3 投票为异常 → 报警
IF      → 投票 3
```

为什么不用单一算法？
- 3-Sigma：只能检测正态分布的突变，对缓慢漂移无感
- EWMA：能检测趋势变化，但对突发尖峰不敏感
- Isolation Forest：适合多维异常，但计算量大

三者互补 + 投票机制 = 减少误报

**告警收敛：fingerprint 去重**

```python
fingerprint = MD5(alert_name + target_service + sorted(labels))
# 5 分钟内相同 fingerprint 的告警只报一次
```

### 2. RCAAgent — 知识图谱根因分析

**图遍历策略：反向 BFS**

```
order-service 告警了
→ 它依赖 payment-service, inventory-service, user-service
→ payment-service 依赖 mysql-primary, redis-cache
→ inventory-service 有近期变更！← 根因候选
```

**贝叶斯推理**

```
P(根因|症状) = P(症状|根因) × P(根因) / P(症状)

例：
P(deploy引起|CPU高) = P(CPU高|deploy引起) × P(deploy引起) / P(CPU高)
                    = 0.9 × 0.3 / 0.5
                    = 0.54
```

### 3. HealAgent — 分级自愈 + 安全护栏

**执行链路（责任链模式）：**

```
Playbook 匹配
  → 爆炸半径检查（> 20% 升级为 L2）
    → 熔断器检查（连续 5 次失败 → 暂停）
      → dry-run 模拟执行
        → 实际执行（L0）/ 等待审批（L1/L2）
```

**熔断器状态机：**

```
CLOSED ──失败 N 次──→ OPEN ──超时──→ HALF_OPEN
   ↑                                    │
   └────────── 成功 ──────────────────┘
```

### 4. ChangeAgent — 风险评分模型

```
risk_score = 0.30 × blast_radius      # 爆炸半径
           + 0.25 × operation_risk     # 操作类型风险
           + 0.20 × time_risk          # 时间风险（凌晨更高）
           + 0.15 × history_risk       # 历史失败率
           + 0.10 × service_criticality # 服务关键度
```

## 面试如何讲 Agent 设计？

重点讲三个层次：
1. **为什么要多 Agent？** → 关注点分离、独立迭代、可插拔
2. **Agent 之间怎么协作？** → 事件驱动 + 状态机编排
3. **安全性怎么保证？** → 分级策略 + 安全护栏链
