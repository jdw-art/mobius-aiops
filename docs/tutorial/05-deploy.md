# 部署与运维指南

## 本地开发环境

### 最简模式（不需要任何外部依赖）

Python 版使用内存事件总线 + 内存知识图谱，零外部依赖：

```bash
cd python
pip install fastapi uvicorn pydantic pydantic-settings numpy scikit-learn structlog
python -m uvicorn api.main:app --reload --port 8000
```

### 完整模式（Docker Compose）

```bash
cd python
docker-compose up -d   # 启动 Kafka + Neo4j + Prometheus + Grafana
python -m uvicorn api.main:app --reload --port 8000
```

验证各组件：
- API: http://localhost:8000/docs
- Neo4j: http://localhost:7474 (neo4j / aiops_password)
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3000 (admin / aiops_admin)

## 生产部署架构

```
              ┌─────────────┐
              │  Ingress /   │
              │  API Gateway │
              └──────┬───────┘
                     │
    ┌────────────────┼────────────────┐
    │                │                │
┌───▼───┐    ┌──────▼──────┐   ┌─────▼─────┐
│ AIOps │    │   AIOps     │   │  AIOps    │
│ Pod 1 │    │   Pod 2     │   │  Pod 3    │
└───┬───┘    └──────┬──────┘   └─────┬─────┘
    │               │                │
    └───────────────┼────────────────┘
                    │
         ┌──────────┼──────────┐
         │          │          │
    ┌────▼────┐ ┌───▼───┐ ┌───▼──────┐
    │  Kafka  │ │ Neo4j │ │Prometheus│
    │ Cluster │ │  HA   │ │  + Loki  │
    └─────────┘ └───────┘ └──────────┘
```

## Kubernetes 部署

```yaml
# deployment.yaml 示例
apiVersion: apps/v1
kind: Deployment
metadata:
  name: aiops-agents
  namespace: aiops
spec:
  replicas: 3
  selector:
    matchLabels:
      app: aiops-agents
  template:
    spec:
      containers:
      - name: aiops
        image: aiops-agents:latest
        ports:
        - containerPort: 8000
        env:
        - name: AIOPS_KAFKA_BOOTSTRAP_SERVERS
          value: "kafka-cluster:9092"
        - name: AIOPS_NEO4J_URI
          value: "bolt://neo4j-cluster:7687"
        resources:
          requests:
            cpu: "500m"
            memory: "512Mi"
          limits:
            cpu: "2000m"
            memory: "2Gi"
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
```

## 监控自身

AIOps 系统本身也需要被监控：

1. **Prometheus 指标**：Agent 处理延迟、成功率、队列深度
2. **结构化日志**：JSON 格式，便于 Loki 查询
3. **链路追踪**：每次故障处理的完整 trace
4. **告警规则**：Agent 错误率 > 5% / P95 延迟 > 5s
