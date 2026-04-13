# 从零开始：多 Agent AIOps 系统搭建指南

> 本教程面向零基础的同学，一步一步带你理解和运行整个项目。

## 前置知识

你需要了解以下基础概念（不需要精通）：
- HTTP API（GET / POST 请求）
- 微服务架构（服务拆分、服务间调用）
- 容器化（Docker 基本概念）

## 第一步：理解问题

### 传统运维的痛点

想象你是一家电商公司的运维工程师：
- 公司有 50+ 微服务在 Kubernetes 上运行
- 每天收到 200+ 条告警，70% 是重复或误报
- 一次故障从发现到修复平均 40 分钟
- 凌晨 3 点接到电话，赶到电脑前先花 10 分钟搞清楚哪里出问题了

### 我们的解决方案

用四个 AI Agent 自动化这个过程：

```
告警来了 → Agent 1 判断是否真的异常
         → Agent 2 分析根因在哪里
         → Agent 3 找到修复方案并执行
         → Agent 4 审批这个操作是否安全
         → 修复完成，全程 5 分钟
```

## 第二步：项目结构理解

```
项目入口在哪？

Python 版:  python/api/main.py        ← FastAPI 启动这里
Java 版:    java/src/.../AiOpsApplication.java  ← Spring Boot 启动
Go 版:      golang/cmd/server/main.go  ← Gin 启动

核心 Agent 在哪？

python/agents/monitor_agent.py   ← 监控告警
python/agents/rca_agent.py       ← 根因分析
python/agents/heal_agent.py      ← 故障自愈
python/agents/change_agent.py    ← 变更审批

编排器在哪？

python/core/orchestrator.py      ← 控制 Agent 执行顺序
```

## 第三步：运行 Python 版

### 方式一：最简运行（不需要 Docker）

```bash
cd python
pip install fastapi uvicorn pydantic pydantic-settings numpy scikit-learn structlog

# 启动服务
python -m uvicorn api.main:app --reload --port 8000
```

### 方式二：完整运行（含 Kafka + Neo4j）

```bash
cd python
pip install -r requirements.txt
docker-compose up -d    # 启动 Kafka, Neo4j, Prometheus, Grafana
python -m uvicorn api.main:app --reload --port 8000
```

### 测试一下

```bash
# 触发一次故障处理
curl -X POST http://localhost:8000/api/v1/incidents/trigger

# 查看结果
curl http://localhost:8000/api/v1/incidents

# 运行异常检测 Demo
curl http://localhost:8000/api/v1/anomaly/demo

# 查看服务拓扑
curl http://localhost:8000/api/v1/topology
```

## 第四步：运行 Demo 演示

```bash
# 直接运行 Orchestrator 的 demo 模式
cd python
python -c "import asyncio; from core.orchestrator import run_demo; asyncio.run(run_demo())"
```

这会模拟一次完整的故障处理流程，输出类似：

```
============================================================
  故障处理结果
============================================================
  事件 ID:    abc-123-def
  状态:       resolved

  [告警]
    名称:     high_cpu_usage
    严重度:   high
    服务:     order-service

  [根因分析]
    根因:     近期代码部署引入性能退化
    置信度:   0.54
    建议动作: rollback, profiling

  [自愈]
    操作:     rollback
    级别:     L1
    爆炸半径: 0.15

  [审批]
    状态:     approved
    风险分:   0.158
    审批人:   oncall-engineer
============================================================
```

## 第五步：理解代码执行流程

```
1. Orchestrator.run() 被调用
2. MonitorAgent.process()
   → 检测指标异常（Demo 模式生成模拟告警）
   → 生成 AlertEvent: CPU 95.3% > 80%
3. 条件检查：alert_event != None → 执行 RCA
4. RCAAgent.process()
   → 追踪依赖链：order-service → payment/inventory/user
   → 发现近期变更：deploy v2.3.1
   → 贝叶斯推理：P(deploy|anomaly) = 0.54
   → 建议动作：rollback
5. 条件检查：confidence 0.54 >= 0.3 → 执行 Heal
6. HealAgent.process()
   → 匹配 Playbook：rollback (L1)
   → dry-run 验证命令
   → 生成修复方案
7. ChangeAgent.process()
   → 风险评分：0.158
   → L1 + risk <= 0.5 → oncall 自动审批
   → 状态变为 resolved
```

## 下一步

- [02-event-driven.md](02-event-driven.md) — 深入理解事件驱动架构
- [03-agent-design.md](03-agent-design.md) — Agent 设计模式详解
- [04-knowledge-graph.md](04-knowledge-graph.md) — 知识图谱详解
- [05-deploy.md](05-deploy.md) — 生产部署指南
