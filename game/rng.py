"""可注入随机源：测试时传入固定序列，保证结果可复现。"""
from __future__ import annotations

import random
from typing import Any, Iterable, Optional, Sequence


class Rng:
    def __init__(self, seed: Optional[int] = None, sequence: Optional[Iterable[Any]] = None):
        self._sequence = list(sequence) if sequence is not None else None
        self._pos = 0
        self._random = random.Random(seed)

    def set_sequence(self, seq) -> None:
        self._sequence = list(seq)
        self._pos = 0

    def _next(self) -> Any:
        if self._sequence is None:
            raise RuntimeError("random sequence not configured")
        if self._pos >= len(self._sequence):
            raise RuntimeError("random sequence exhausted")
        v = self._sequence[self._pos]
        self._pos += 1
        return v

    def uniform(self, a: float, b: float) -> float:
        if self._sequence is not None:
            v = float(self._next())
        else:
            v = self._random.uniform(a, b)
        return round(v, 2)

    def randint(self, a: int, b: int) -> int:
        if self._sequence is not None:
            return int(self._next())
        return self._random.randint(a, b)

    def choice(self, seq: Sequence[Any]) -> Any:
        if self._sequence is not None:
            return self._next()
        return self._random.choice(seq)

    def weighted_choice(self, items: Sequence[Any], weights: Sequence[float]) -> Any:
        total = sum(weights)
        if self._sequence is not None:
            point = float(self._next())
        else:
            point = self._random.uniform(0, total)
        acc = 0.0
        for item, w in zip(items, weights):
            acc += w
            if point < acc:
                return item
        return items[-1]
