"""时序异常检测模块 — 多算法集成

核心算法（面试必问）：

1. 3-Sigma (Z-Score):
   - 原理：假设数据服从正态分布，超过 μ±3σ 的点为异常
   - 优点：简单快速，O(n)
   - 缺点：不适合非正态分布、季节性数据
   - 适用：CPU、内存等近似正态的指标

2. EWMA (指数加权移动平均):
   - 原理：对近期数据赋予更高权重，检测趋势变化
   - 公式：EWMA_t = α * x_t + (1-α) * EWMA_{t-1}
   - α (平滑因子)：越大对近期越敏感
   - 适用：检测缓慢漂移、趋势变化

3. Isolation Forest:
   - 原理：随机切割特征空间，异常点更容易被隔离（路径更短）
   - 优点：无需假设分布，适合高维数据
   - 缺点：需要调参 contamination
   - 适用：多维指标联合异常检测

4. Prophet (可选):
   - 原理：分解时序为趋势+季节性+节假日效应
   - 优点：自动处理季节性和节假日
   - 适用：有明显周期性的业务指标（QPS、订单量）

面试高频问题：
Q: "静态阈值和动态阈值的区别？"
A: 静态阈值是固定的（如 CPU>80%），无法适应业务波动（如大促期间 CPU 本来就高）。
   动态阈值根据历史数据自动学习正常范围，能适应季节性和趋势变化。

Q: "多种算法如何协作？"
A: 投票机制 — 至少 2/3 算法同时判定为异常才报警，减少误报。
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class AnomalyResult:
    """异常检测结果"""
    is_anomaly: bool
    score: float              # 异常分数（越高越异常）
    algorithm: str            # 检测算法名
    threshold: float          # 使用的阈值
    current_value: float      # 当前值
    expected_value: float     # 预期值
    detail: str = ""


class ThreeSigmaDetector:
    """3-Sigma 异常检测器"""

    def __init__(self, sigma_multiplier: float = 3.0):
        self._sigma = sigma_multiplier

    def detect(self, values: list[float], current: float) -> AnomalyResult:
        if len(values) < 10:
            return AnomalyResult(
                is_anomaly=False, score=0.0, algorithm="3-sigma",
                threshold=self._sigma, current_value=current, expected_value=current,
                detail="Insufficient data points",
            )

        arr = np.array(values)
        mean = float(arr.mean())
        std = float(arr.std())

        if std == 0:
            return AnomalyResult(
                is_anomaly=False, score=0.0, algorithm="3-sigma",
                threshold=self._sigma, current_value=current, expected_value=mean,
            )

        z_score = abs(current - mean) / std
        is_anomaly = z_score > self._sigma

        return AnomalyResult(
            is_anomaly=is_anomaly,
            score=round(z_score, 3),
            algorithm="3-sigma",
            threshold=self._sigma,
            current_value=current,
            expected_value=round(mean, 3),
            detail=f"Z-score={z_score:.3f}, mean={mean:.3f}, std={std:.3f}",
        )


class EWMADetector:
    """EWMA 指数加权移动平均异常检测器"""

    def __init__(self, alpha: float = 0.3, threshold: float = 3.0):
        self._alpha = alpha
        self._threshold = threshold

    def detect(self, values: list[float], current: float) -> AnomalyResult:
        if len(values) < 5:
            return AnomalyResult(
                is_anomaly=False, score=0.0, algorithm="ewma",
                threshold=self._threshold, current_value=current, expected_value=current,
                detail="Insufficient data points",
            )

        ewma = values[0]
        ewma_var = 0.0
        for v in values[1:]:
            diff = v - ewma
            ewma = self._alpha * v + (1 - self._alpha) * ewma
            ewma_var = self._alpha * diff ** 2 + (1 - self._alpha) * ewma_var

        ewma_std = float(np.sqrt(ewma_var))
        if ewma_std == 0:
            return AnomalyResult(
                is_anomaly=False, score=0.0, algorithm="ewma",
                threshold=self._threshold, current_value=current, expected_value=round(ewma, 3),
            )

        deviation = abs(current - ewma) / ewma_std
        is_anomaly = deviation > self._threshold

        return AnomalyResult(
            is_anomaly=is_anomaly,
            score=round(deviation, 3),
            algorithm="ewma",
            threshold=self._threshold,
            current_value=current,
            expected_value=round(ewma, 3),
            detail=f"deviation={deviation:.3f}, ewma={ewma:.3f}, ewma_std={ewma_std:.3f}",
        )


class IsolationForestDetector:
    """Isolation Forest 异常检测器"""

    def __init__(self, contamination: float = 0.05):
        self._contamination = contamination

    def detect(self, values: list[float], current: float) -> AnomalyResult:
        if len(values) < 20:
            return AnomalyResult(
                is_anomaly=False, score=0.0, algorithm="isolation_forest",
                threshold=0.0, current_value=current, expected_value=current,
                detail="Insufficient data points (need >= 20)",
            )

        from sklearn.ensemble import IsolationForest

        data = np.array(values).reshape(-1, 1)
        current_arr = np.array([[current]])

        clf = IsolationForest(
            contamination=self._contamination,
            random_state=42,
            n_estimators=100,
        )
        clf.fit(data)

        prediction = clf.predict(current_arr)
        score = float(-clf.decision_function(current_arr)[0])

        is_anomaly = prediction[0] == -1

        return AnomalyResult(
            is_anomaly=is_anomaly,
            score=round(score, 3),
            algorithm="isolation_forest",
            threshold=self._contamination,
            current_value=current,
            expected_value=round(float(np.median(values)), 3),
            detail=f"anomaly_score={score:.3f}, prediction={prediction[0]}",
        )


class MultiDimensionalIFDetector:
    """多维 Isolation Forest — 联合多个指标检测"""

    def __init__(self, contamination: float = 0.05):
        self._contamination = contamination

    def detect(self, feature_matrix: list[list[float]], current_features: list[float]) -> AnomalyResult:
        if len(feature_matrix) < 20:
            return AnomalyResult(
                is_anomaly=False, score=0.0, algorithm="multi_dim_if",
                threshold=0.0, current_value=0.0, expected_value=0.0,
                detail="Insufficient data",
            )

        from sklearn.ensemble import IsolationForest

        data = np.array(feature_matrix)
        current_arr = np.array([current_features])

        clf = IsolationForest(
            contamination=self._contamination,
            random_state=42,
        )
        clf.fit(data)

        prediction = clf.predict(current_arr)
        score = float(-clf.decision_function(current_arr)[0])

        return AnomalyResult(
            is_anomaly=prediction[0] == -1,
            score=round(score, 3),
            algorithm="multi_dim_if",
            threshold=self._contamination,
            current_value=current_features[0] if current_features else 0.0,
            expected_value=0.0,
            detail=f"multi-dim score={score:.3f}, dims={len(current_features)}",
        )


class EnsembleDetector:
    """集成异常检测器 — 多算法投票

    面试要点：
    - 投票机制：至少 K/N 个算法同意才判定异常
    - 减少误报（False Positive）
    - 不同算法互补：3-sigma 检测突变，EWMA 检测漂移，IF 检测多维异常
    """

    def __init__(self, min_votes: int = 2):
        self._detectors = [
            ThreeSigmaDetector(sigma_multiplier=3.0),
            EWMADetector(alpha=0.3, threshold=3.0),
            IsolationForestDetector(contamination=0.05),
        ]
        self._min_votes = min_votes

    def detect(self, values: list[float], current: float) -> tuple[bool, float, list[AnomalyResult]]:
        """返回 (是否异常, 最大异常分数, 各算法结果)"""
        results = [d.detect(values, current) for d in self._detectors]
        votes = sum(1 for r in results if r.is_anomaly)
        max_score = max((r.score for r in results), default=0.0)

        is_anomaly = votes >= self._min_votes

        if is_anomaly:
            logger.info(
                f"[EnsembleDetector] ANOMALY: votes={votes}/{len(self._detectors)}, "
                f"score={max_score:.3f}, value={current}"
            )

        return is_anomaly, max_score, results


def generate_demo_metrics(n_points: int = 200, inject_anomaly: bool = True) -> tuple[list[float], list[float]]:
    """生成演示用的时序数据

    - 正弦波 + 线性趋势 + 随机噪声模拟真实指标
    - 可注入异常点用于测试
    """
    np.random.seed(42)
    t = np.arange(n_points)

    trend = 50 + 0.05 * t
    seasonal = 10 * np.sin(2 * np.pi * t / 24)
    noise = np.random.normal(0, 2, n_points)

    values = trend + seasonal + noise

    anomalies = []
    if inject_anomaly:
        anomaly_indices = [150, 170, 185]
        for idx in anomaly_indices:
            if idx < n_points:
                values[idx] += np.random.choice([-1, 1]) * 30
                anomalies.append(idx)

    return values.tolist(), [1.0 if i in anomalies else 0.0 for i in range(n_points)]
