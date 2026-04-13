"""事件总线 — Kafka 生产者/消费者封装

核心设计：
1. 所有 Agent 间通信都通过事件总线，实现完全解耦
2. 支持 topic 路由：不同事件类型发往不同 topic
3. 消费者组隔离：每个 Agent 独立消费组，互不干扰
4. 内置重试 + 死信队列（DLQ）机制
5. 可降级为内存队列（本地开发/面试 Demo 用）
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from collections import defaultdict
from datetime import datetime
from typing import Any, Callable, Optional

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class EventBus(ABC):
    """事件总线抽象基类 — 策略模式，方便切换 Kafka/内存实现"""

    @abstractmethod
    async def publish(self, topic: str, event: BaseModel) -> None:
        """发布事件到指定 topic"""

    @abstractmethod
    async def subscribe(
        self, topic: str, group_id: str, handler: Callable
    ) -> None:
        """订阅 topic，指定消费组和处理函数"""

    @abstractmethod
    async def start(self) -> None:
        """启动事件总线"""

    @abstractmethod
    async def stop(self) -> None:
        """停止事件总线"""


class InMemoryEventBus(EventBus):
    """内存事件总线 — 本地开发和测试用，无需启动 Kafka

    面试要点：可以解释为什么提供内存实现——
    1. 降低开发门槛，docker-compose 不是必须的
    2. 单元测试不依赖外部服务
    3. 体现「依赖倒置原则」和「策略模式」
    """

    def __init__(self):
        self._subscribers: dict[str, list[tuple[str, Callable]]] = defaultdict(list)
        self._running = False
        self._event_log: list[dict[str, Any]] = []

    async def publish(self, topic: str, event: BaseModel) -> None:
        event_data = event.model_dump(mode="json")
        self._event_log.append({
            "topic": topic,
            "event": event_data,
            "timestamp": datetime.utcnow().isoformat(),
        })
        logger.info(f"[EventBus] Published to {topic}: {event_data.get('event_type', 'unknown')}")

        for group_id, handler in self._subscribers.get(topic, []):
            try:
                await handler(event_data)
            except Exception as e:
                logger.error(f"[EventBus] Handler error in group {group_id}: {e}")

    async def subscribe(
        self, topic: str, group_id: str, handler: Callable
    ) -> None:
        self._subscribers[topic].append((group_id, handler))
        logger.info(f"[EventBus] Subscribed {group_id} to {topic}")

    async def start(self) -> None:
        self._running = True
        logger.info("[EventBus] InMemory event bus started")

    async def stop(self) -> None:
        self._running = False
        logger.info("[EventBus] InMemory event bus stopped")

    def get_event_log(self) -> list[dict[str, Any]]:
        return self._event_log.copy()


class KafkaEventBus(EventBus):
    """Kafka 事件总线 — 生产环境用

    面试要点：
    1. Producer 使用 acks=all 保证消息不丢
    2. Consumer 使用手动 commit，处理完再确认
    3. 序列化用 JSON（也可以换 Avro/Protobuf）
    4. 死信队列处理消费失败的消息
    """

    def __init__(
        self,
        bootstrap_servers: str = "localhost:9092",
        max_retries: int = 3,
    ):
        self._bootstrap_servers = bootstrap_servers
        self._max_retries = max_retries
        self._producer = None
        self._consumers: list = []
        self._running = False

    async def publish(self, topic: str, event: BaseModel) -> None:
        from confluent_kafka import Producer

        if self._producer is None:
            self._producer = Producer({
                "bootstrap.servers": self._bootstrap_servers,
                "acks": "all",
                "retries": self._max_retries,
                "retry.backoff.ms": 100,
            })

        event_data = event.model_dump_json()
        self._producer.produce(
            topic=topic,
            value=event_data.encode("utf-8"),
            callback=self._delivery_callback,
        )
        self._producer.flush(timeout=5)
        logger.info(f"[KafkaEventBus] Published to {topic}")

    async def subscribe(
        self, topic: str, group_id: str, handler: Callable
    ) -> None:
        from confluent_kafka import Consumer

        consumer = Consumer({
            "bootstrap.servers": self._bootstrap_servers,
            "group.id": group_id,
            "auto.offset.reset": "latest",
            "enable.auto.commit": False,
        })
        consumer.subscribe([topic])

        async def _consume_loop():
            while self._running:
                msg = consumer.poll(timeout=1.0)
                if msg is None:
                    await asyncio.sleep(0.1)
                    continue
                if msg.error():
                    logger.error(f"[KafkaEventBus] Consumer error: {msg.error()}")
                    continue

                try:
                    event_data = json.loads(msg.value().decode("utf-8"))
                    await handler(event_data)
                    consumer.commit(asynchronous=False)
                except Exception as e:
                    logger.error(f"[KafkaEventBus] Handler error: {e}")
                    await self._send_to_dlq(topic, msg.value(), str(e))

        self._consumers.append((_consume_loop, consumer))

    async def start(self) -> None:
        self._running = True
        for consume_loop, _ in self._consumers:
            asyncio.create_task(consume_loop())
        logger.info("[KafkaEventBus] Kafka event bus started")

    async def stop(self) -> None:
        self._running = False
        for _, consumer in self._consumers:
            consumer.close()
        if self._producer:
            self._producer.flush(timeout=10)
        logger.info("[KafkaEventBus] Kafka event bus stopped")

    @staticmethod
    def _delivery_callback(err, msg):
        if err:
            logger.error(f"[KafkaEventBus] Delivery failed: {err}")
        else:
            logger.debug(f"[KafkaEventBus] Delivered to {msg.topic()} [{msg.partition()}]")

    async def _send_to_dlq(self, original_topic: str, value: bytes, error: str) -> None:
        dlq_topic = f"{original_topic}.dlq"
        if self._producer:
            self._producer.produce(topic=dlq_topic, value=value)
            self._producer.flush(timeout=5)
            logger.warning(f"[KafkaEventBus] Sent to DLQ {dlq_topic}: {error}")


def create_event_bus(use_kafka: bool = False, **kwargs) -> EventBus:
    """工厂方法创建事件总线实例"""
    if use_kafka:
        return KafkaEventBus(**kwargs)
    return InMemoryEventBus()
