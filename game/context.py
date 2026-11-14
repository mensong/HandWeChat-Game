"""处理器共享上下文。"""
from __future__ import annotations

import logging
from typing import Callable

from .config import Config
from .rng import Rng
from .store import Store


class Ctx:
    def __init__(self, cfg: Config, store: Store, rng: Rng,
                 clock: Callable, log: logging.Logger):
        self.cfg = cfg
        self.store = store
        self.rng = rng
        self.clock = clock
        self.log = log

    def now(self):
        return self.clock()
