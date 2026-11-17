"""数据模型。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Player:
    group_key: str
    name: str
    coins: int
    charm: float
    charm_anchor: str
    master: Optional[str]
    enslaved_at: Optional[str]
    is_phantom: int
    created_at: str
    last_seen_at: str
    last_signin_date: Optional[str]
    signin_streak: int
    last_work_at: Optional[str]
    last_rebel_at: Optional[str]
    last_interact_at: Optional[str]
    last_ransom_at: Optional[str]
    total_charm_gained: float
    total_gift_spent: int
    total_gift_charm: float


@dataclass
class Gift:
    id: str
    name: str
    aliases: list
    price: int
    charm: float


@dataclass
class WorkEvent:
    text: str
    coins_min: int
    coins_max: int
    weight: float


@dataclass
class Interaction:
    text: str
    tone: str


@dataclass
class Command:
    name: str
    target: Optional[str] = None
    amount: Optional[int] = None
    gift: Optional[str] = None
    count: Optional[int] = None
    mention: Optional[str] = None


@dataclass
class Pat:
    pat: str
    patted: str
    what: str = ""
