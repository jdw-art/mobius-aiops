"""AIOps 多 Agent 系统全局配置"""

from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    app_name: str = "Multi-Agent AIOps"
    debug: bool = False

    # Kafka
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_group_id: str = "aiops-agents"
    kafka_topics_alerts: str = "aiops.alerts"
    kafka_topics_events: str = "aiops.events"
    kafka_topics_commands: str = "aiops.commands"
    kafka_topics_audit: str = "aiops.audit"

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "aiops_password"

    # LLM
    openai_api_key: Optional[str] = None
    openai_model: str = "gpt-4o-mini"
    openai_base_url: Optional[str] = None

    # Prometheus
    prometheus_url: str = "http://localhost:9090"

    # Agent 配置
    monitor_check_interval: int = 30
    rca_max_depth: int = 5
    heal_dry_run: bool = True
    heal_max_retries: int = 3
    change_auto_approve_threshold: float = 0.9

    # 安全护栏
    circuit_breaker_threshold: int = 5
    circuit_breaker_timeout: int = 60
    rate_limit_per_minute: int = 30
    blast_radius_max_percent: float = 0.2

    model_config = {"env_prefix": "AIOPS_", "env_file": ".env"}


settings = Settings()
