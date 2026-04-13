# 简历模板 — 多 Agent AIOps 项目

> 根据你面试的岗位方向（Python/Java/Go），调整技术栈描述。

---

## 模板一：Python / AI 方向

```
多 Agent 智能运维系统 (AIOps)                         2025.xx - 至今
技术栈：Python / LangGraph / Kafka / Neo4j / Prometheus / FastAPI / Docker

● 设计并实现基于事件驱动架构的多 Agent 协作系统，包含监控告警、根因分析、
  故障自愈、变更审批 4 个专业 Agent，通过 Kafka 事件总线解耦通信

● 基于 Neo4j 构建微服务拓扑知识图谱（11 个服务节点 + 15 条依赖关系），
  实现 BFS 图遍历 + 贝叶斯推理的根因定位算法，MTTR 从 40min 降至 5min

● 集成 3-Sigma / EWMA / Isolation Forest 三算法投票的动态阈值异常检测，
  相比静态阈值误报率降低 85%，告警准确率提升至 92%

● 设计三级自愈策略（L0 全自动 / L1 半自动 / L2 人工审批），配合熔断器 +
  dry-run + 爆炸半径评估等安全护栏，自动修复覆盖 60%+ 常见故障场景
```

## 模板二：Java 后端方向

```
多 Agent 智能运维平台 (AIOps)                         2025.xx - 至今
技术栈：Java 21 / Spring Boot 3 / Spring Kafka / Spring Data Neo4j / Prometheus

● 基于 Spring Boot 构建企业级多 Agent 运维平台，采用策略模式 + 模板方法模式
  + 责任链模式实现 Agent 编排，通过 Kafka 事件总线实现 Agent 间异步解耦

● 使用 Spring Data Neo4j 构建服务拓扑知识图谱，支持 Cypher 多跳查询的
  根因分析算法，将故障定位时间从平均 40 分钟缩短至 5 分钟

● 实现 ConcurrentHashMap + DoubleSummaryStatistics 的高性能时序异常检测，
  支持 3-Sigma 统计异常检测，告警准确率 92%

● 设计 L0/L1/L2 分级审批 + 熔断器模式（AtomicInteger 无锁计数），
  60%+ 常见故障实现自动修复，支持 Prometheus + Micrometer 全链路指标暴露
```

## 模板三：Go / 云原生方向

```
多 Agent 智能运维系统 (AIOps)                         2025.xx - 至今
技术栈：Go 1.23 / Gin / sarama (Kafka) / Neo4j / Prometheus / Kubernetes

● 基于 Go interface + goroutine/channel 构建轻量级多 Agent 编排框架，
  4 个 Agent 通过 Kafka 事件总线异步协作，支持条件路由和失败重试

● 使用 sync.Map + atomic 操作实现无锁高并发的时序数据存储和异常检测，
  单实例支持 10K+ QPS 的指标处理吞吐量

● 实现知识图谱驱动的根因分析（BFS 遍历 + 贝叶斯推理），MTTR 降低 87%

● 设计 goroutine 安全的熔断器（CLOSED/OPEN/HALF_OPEN 状态机），
  配合 dry-run + 爆炸半径评估的安全护栏链，保障自愈操作安全性
```

---

## 简历 Tips

### DO ✓

- 每条用「动作 + 方法 + 量化结果」结构
- 技术栈写具体版本号（Spring Boot 3 而不是 Spring Boot）
- 量化数据要合理（不要写 99.99% 之类夸张的数据）
- 项目描述 4 条即可，控制在半页以内

### DON'T ✗

- 不要写"参与了 xx 项目"，要写"设计并实现了 xx"
- 不要罗列技术栈不解释做了什么
- 不要写"负责后端开发"，要写具体负责的模块
- 数据不要太夸张（面试官会追问细节）
