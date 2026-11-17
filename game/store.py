"""SQLite 持久化：建表、事务、玩家与账务访问。"""
from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

from .models import Player

_PLAYER_COLS = ("group_key, name, coins, charm, charm_anchor, master, enslaved_at, "
                "is_phantom, created_at, last_seen_at, last_signin_date, signin_streak, "
                "last_work_at, last_rebel_at, last_interact_at, last_ransom_at, "
                "total_charm_gained, total_gift_spent, total_gift_charm")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
  group_key        TEXT    NOT NULL,
  name             TEXT    NOT NULL,
  coins            INTEGER NOT NULL DEFAULT 200 CHECK (coins >= 0),
  charm            REAL    NOT NULL DEFAULT 10,
  charm_anchor     TEXT    NOT NULL,
  master           TEXT,
  enslaved_at      TEXT,
  is_phantom       INTEGER NOT NULL DEFAULT 0,
  created_at       TEXT    NOT NULL,
  last_seen_at     TEXT    NOT NULL,
  last_signin_date TEXT,
  signin_streak    INTEGER NOT NULL DEFAULT 0,
  last_work_at     TEXT,
  last_rebel_at    TEXT,
  last_interact_at TEXT,
  last_ransom_at   TEXT,
  total_charm_gained REAL  NOT NULL DEFAULT 0,
  total_gift_spent   INTEGER NOT NULL DEFAULT 0,
  total_gift_charm   REAL  NOT NULL DEFAULT 0,
  PRIMARY KEY (group_key, name)
);

CREATE INDEX IF NOT EXISTS idx_players_master ON players(group_key, master);

CREATE TABLE IF NOT EXISTS gift_events (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  group_key  TEXT    NOT NULL,
  ts         TEXT    NOT NULL,
  sender     TEXT    NOT NULL,
  receiver   TEXT    NOT NULL,
  gift_id    TEXT    NOT NULL,
  gift_name  TEXT    NOT NULL,
  count      INTEGER NOT NULL,
  cost       INTEGER NOT NULL,
  charm_gain REAL    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gift_events_group_ts ON gift_events(group_key, ts);

CREATE TABLE IF NOT EXISTS coin_ledger (
  id             INTEGER PRIMARY KEY AUTOINCREMENT,
  group_key      TEXT    NOT NULL,
  ts             TEXT    NOT NULL,
  actor          TEXT    NOT NULL,
  counterparty   TEXT,
  amount         INTEGER NOT NULL,
  reason         TEXT    NOT NULL,
  balance_after  INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_coin_ledger_group_ts ON coin_ledger(group_key, ts);

CREATE TABLE IF NOT EXISTS daily_counters (
  group_key TEXT    NOT NULL,
  date      TEXT    NOT NULL,
  name      TEXT    NOT NULL,
  action    TEXT    NOT NULL,
  count     INTEGER NOT NULL DEFAULT 0,
  amount    INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (group_key, date, name, action)
);
"""


class Store:
    def __init__(self, db_path: str | Path):
        self.db_path = str(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, isolation_level=None, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_SCHEMA)
            cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(players)")}
            if "last_interact_at" not in cols:
                self._conn.execute("ALTER TABLE players ADD COLUMN last_interact_at TEXT")
            if "last_ransom_at" not in cols:
                self._conn.execute("ALTER TABLE players ADD COLUMN last_ransom_at TEXT")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @contextmanager
    def transaction(self):
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
            except Exception:
                self._conn.rollback()
                raise
            else:
                self._conn.commit()

    # ---------- players ----------

    @staticmethod
    def _player(row) -> Optional[Player]:
        if row is None:
            return None
        return Player(**{k: row[k] for k in row.keys()})

    def upsert_player(self, group: str, name: str, now_iso: str,
                      initial_coins: int, charm_base: float) -> Player:
        with self._lock:
            self._conn.execute(
                """INSERT INTO players
                   (group_key, name, coins, charm, charm_anchor, is_phantom,
                    created_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, 0, ?, ?)
                   ON CONFLICT(group_key, name) DO UPDATE SET
                     last_seen_at = excluded.last_seen_at,
                     is_phantom = 0""",
                (group, name, initial_coins, charm_base, now_iso, now_iso, now_iso),
            )
            return self.get_player(group, name)

    def get_player(self, group: str, name: str) -> Optional[Player]:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_PLAYER_COLS} FROM players WHERE group_key=? AND name=?",
                (group, name),
            ).fetchone()
        return self._player(row)

    def find_player_ci(self, group: str, name: str) -> Optional[Player]:
        with self._lock:
            row = self._conn.execute(
                f"SELECT {_PLAYER_COLS} FROM players WHERE group_key=? AND LOWER(name)=LOWER(?)",
                (group, name),
            ).fetchone()
        return self._player(row)

    def resolve_player(self, group: str, name: str) -> Optional[Player]:
        """精确 → 忽略大小写 → 已知玩家最长前缀。

        前缀解析用于 OCR 吞空格后昵称粘连闲聊的情况
        （如 "张三谢谢" 命中已有玩家 "张三"）。
        """
        p = self.get_player(group, name)
        if p is not None:
            return p
        p = self.find_player_ci(group, name)
        if p is not None:
            return p
        with self._lock:
            rows = self._conn.execute(
                "SELECT name FROM players WHERE group_key=?", (group,)
            ).fetchall()
        low = name.lower()
        candidates = [r["name"] for r in rows if low.startswith(r["name"].lower())]
        if candidates:
            return self.get_player(group, max(candidates, key=len))
        return None

    def get_or_create_target(self, group: str, name: str, now_iso: str,
                             initial_coins: int, charm_base: float,
                             auto_create: bool) -> Optional[Player]:
        p = self.resolve_player(group, name)
        if p is not None:
            return p
        if not auto_create or not 1 <= len(name) <= 20:
            return None
        with self._lock:
            self._conn.execute(
                """INSERT INTO players
                   (group_key, name, coins, charm, charm_anchor, is_phantom,
                    created_at, last_seen_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                (group, name, initial_coins, charm_base, now_iso, now_iso, now_iso),
            )
        return self.get_player(group, name)

    def update_charm(self, group: str, name: str, charm: float, anchor_iso: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE players SET charm=?, charm_anchor=? WHERE group_key=? AND name=?",
                (charm, anchor_iso, group, name),
            )

    def set_master(self, group: str, name: str, master: Optional[str], ts_iso: str) -> None:
        with self._lock:
            if master is None:
                self._conn.execute(
                    "UPDATE players SET master=NULL, enslaved_at=NULL WHERE group_key=? AND name=?",
                    (group, name),
                )
            else:
                self._conn.execute(
                    "UPDATE players SET master=?, enslaved_at=? WHERE group_key=? AND name=?",
                    (master, ts_iso, group, name),
                )

    def list_players(self, group: str) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT name, coins, charm, master, is_phantom, signin_streak,
                          last_signin_date, last_work_at, last_rebel_at
                   FROM players WHERE group_key=?
                   ORDER BY is_phantom ASC, coins DESC, name ASC""",
                (group,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_groups(self) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT group_key FROM players ORDER BY group_key"
            ).fetchall()
        return [r["group_key"] for r in rows]

    def admin_add_coins(self, group: str, name: str, amount: int,
                        ts_iso: str) -> int:
        return self.adjust_coins(group, name, amount, "admin", None, ts_iso)

    def admin_set_charm(self, group: str, name: str, value: float) -> None:
        value = float(value)
        if value < 0:
            raise ValueError("charm must be >= 0")
        with self._lock:
            cur = self._conn.execute(
                "UPDATE players SET charm=? WHERE group_key=? AND name=?",
                (value, group, name),
            )
            if cur.rowcount == 0:
                raise LookupError(f"player not found: {name}")

    def admin_clear_master(self, group: str, name: str) -> None:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE players SET master=NULL, enslaved_at=NULL WHERE group_key=? AND name=?",
                (group, name),
            )
            if cur.rowcount == 0:
                raise LookupError(f"player not found: {name}")

    def admin_get_player(self, group: str, name: str) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT name, coins, charm, master FROM players WHERE group_key=? AND name=?",
                (group, name),
            ).fetchone()
        if row is None:
            raise LookupError(f"player not found: {name}")
        return dict(row)

    def delete_player(self, group: str, name: str,
                      purge_history: bool = False) -> dict:
        """删除单个玩家：名下奴隶自动恢复自由身，每日计数器一并删除。

        purge_history=True 时连同该玩家相关的金币流水与礼物记录一起删除。
        """
        with self.transaction():
            exists = self._conn.execute(
                "SELECT 1 FROM players WHERE group_key=? AND name=?",
                (group, name),
            ).fetchone()
            if exists is None:
                raise LookupError(f"player not found: {name}")
            freed = self._conn.execute(
                "UPDATE players SET master=NULL, enslaved_at=NULL "
                "WHERE group_key=? AND master=?",
                (group, name),
            ).rowcount
            self._conn.execute(
                "DELETE FROM daily_counters WHERE group_key=? AND name=?",
                (group, name),
            )
            if purge_history:
                self._conn.execute(
                    "DELETE FROM coin_ledger WHERE group_key=? AND (actor=? OR counterparty=?)",
                    (group, name, name),
                )
                self._conn.execute(
                    "DELETE FROM gift_events WHERE group_key=? AND (sender=? OR receiver=?)",
                    (group, name, name),
                )
            self._conn.execute(
                "DELETE FROM players WHERE group_key=? AND name=?",
                (group, name),
            )
        return {"released_slaves": freed}

    def delete_phantom_players(self, group: str,
                               purge_history: bool = False) -> int:
        """删除指定群全部影子玩家，返回删除数量。"""
        with self.transaction():
            names = [r["name"] for r in self._conn.execute(
                "SELECT name FROM players WHERE group_key=? AND is_phantom=1",
                (group,),
            ).fetchall()]
            if not names:
                return 0
            placeholders = ",".join("?" for _ in names)
            self._conn.execute(
                f"""UPDATE players SET master=NULL, enslaved_at=NULL
                    WHERE group_key=? AND master IN ({placeholders})""",
                (group, *names),
            )
            self._conn.execute(
                f"DELETE FROM daily_counters WHERE group_key=? AND name IN ({placeholders})",
                (group, *names),
            )
            if purge_history:
                for name in names:
                    self._conn.execute(
                        "DELETE FROM coin_ledger WHERE group_key=? AND (actor=? OR counterparty=?)",
                        (group, name, name),
                    )
                    self._conn.execute(
                        "DELETE FROM gift_events WHERE group_key=? AND (sender=? OR receiver=?)",
                        (group, name, name),
                    )
            cur = self._conn.execute(
                "DELETE FROM players WHERE group_key=? AND is_phantom=1",
                (group,),
            )
        return cur.rowcount

    def clear_group_data(self, group: str, purge_history: bool = False) -> dict:
        """清空指定群全部玩家与计数器；流水/礼物记录默认保留。"""
        with self.transaction():
            n = self._conn.execute(
                "SELECT COUNT(*) AS c FROM players WHERE group_key=?",
                (group,),
            ).fetchone()["c"]
            self._conn.execute(
                "DELETE FROM daily_counters WHERE group_key=?", (group,),
            )
            if purge_history:
                self._conn.execute(
                    "DELETE FROM coin_ledger WHERE group_key=?", (group,),
                )
                self._conn.execute(
                    "DELETE FROM gift_events WHERE group_key=?", (group,),
                )
            self._conn.execute(
                "DELETE FROM players WHERE group_key=?", (group,),
            )
        return {"players": n, "purged_history": purge_history}

    def slaves(self, group: str, master: str) -> list[Player]:
        with self._lock:
            rows = self._conn.execute(
                f"""SELECT {_PLAYER_COLS} FROM players
                    WHERE group_key=? AND master=? ORDER BY enslaved_at ASC, name ASC""",
                (group, master),
            ).fetchall()
        return [self._player(r) for r in rows]

    def slave_count(self, group: str, master: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COUNT(*) AS c FROM players WHERE group_key=? AND master=?",
                (group, master),
            ).fetchone()
        return row["c"]

    # ---------- coins ----------

    def adjust_coins(self, group: str, name: str, delta: int, reason: str,
                     counterparty: Optional[str], ts_iso: str) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT coins FROM players WHERE group_key=? AND name=?",
                (group, name),
            ).fetchone()
            if row is None:
                raise LookupError(f"player not found: {name}")
            new_balance = row["coins"] + delta
            if new_balance < 0:
                raise ValueError(f"insufficient coins for {name}")
            self._conn.execute(
                "UPDATE players SET coins=? WHERE group_key=? AND name=?",
                (new_balance, group, name),
            )
            self._conn.execute(
                """INSERT INTO coin_ledger
                   (group_key, ts, actor, counterparty, amount, reason, balance_after)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (group, ts_iso, name, counterparty, delta, reason, new_balance),
            )
        return new_balance

    def coin_rank(self, group: str, limit: int) -> list[tuple[str, int]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT name, coins FROM players WHERE group_key=? AND is_phantom=0
                   ORDER BY coins DESC, name ASC LIMIT ?""",
                (group, limit),
            ).fetchall()
        return [(r["name"], r["coins"]) for r in rows]

    def coin_rank_position(self, group: str, coins: int) -> int:
        with self._lock:
            row = self._conn.execute(
                """SELECT COUNT(*) AS c FROM players
                   WHERE group_key=? AND is_phantom=0 AND coins > ?""",
                (group, coins),
            ).fetchone()
        return row["c"] + 1

    def charm_rank(self, group: str, limit: int) -> list[tuple[str, float]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT name, charm FROM players WHERE group_key=? AND is_phantom=0
                   ORDER BY charm DESC, name ASC LIMIT ?""",
                (group, limit),
            ).fetchall()
        return [(r["name"], r["charm"]) for r in rows]

    def charm_rank_position(self, group: str, charm: float) -> int:
        with self._lock:
            row = self._conn.execute(
                """SELECT COUNT(*) AS c FROM players
                   WHERE group_key=? AND is_phantom=0 AND charm > ?""",
                (group, charm),
            ).fetchone()
        return row["c"] + 1

    # ---------- daily counters ----------

    def incr_daily(self, group: str, date: str, name: str, action: str,
                   count: int = 1, amount: int = 0) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO daily_counters (group_key, date, name, action, count, amount)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(group_key, date, name, action) DO UPDATE SET
                     count = count + excluded.count,
                     amount = amount + excluded.amount""",
                (group, date, name, action, count, amount),
            )

    def get_daily(self, group: str, date: str, name: str, action: str) -> tuple[int, int]:
        with self._lock:
            row = self._conn.execute(
                "SELECT count, amount FROM daily_counters WHERE group_key=? AND date=? AND name=? AND action=?",
                (group, date, name, action),
            ).fetchone()
        if row is None:
            return 0, 0
        return row["count"], row["amount"]

    def set_player_field(self, group: str, name: str, field: str, value) -> None:
        if field not in ("last_signin_date", "signin_streak", "last_work_at",
                         "last_rebel_at", "last_interact_at", "last_ransom_at"):
            raise ValueError(f"field not writable: {field}")
        with self._lock:
            self._conn.execute(
                f"UPDATE players SET {field}=? WHERE group_key=? AND name=?",
                (value, group, name),
            )

    # ---------- gifts ----------

    def insert_gift_event(self, group: str, ts_iso: str, sender: str, receiver: str,
                          gift_id: str, gift_name: str, count: int,
                          cost: int, charm_gain: float) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO gift_events
                   (group_key, ts, sender, receiver, gift_id, gift_name, count, cost, charm_gain)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (group, ts_iso, sender, receiver, gift_id, gift_name, count, cost, charm_gain),
            )
            self._conn.execute(
                """UPDATE players SET total_gift_spent = total_gift_spent + ?,
                                          total_gift_charm = total_gift_charm + ?
                   WHERE group_key=? AND name=?""",
                (cost, charm_gain, group, sender),
            )
            self._conn.execute(
                """UPDATE players SET total_charm_gained = total_charm_gained + ?,
                                          total_gift_charm = total_gift_charm + ?
                   WHERE group_key=? AND name=?""",
                (charm_gain, charm_gain, group, receiver),
            )

    def gift_send_rank(self, group: str, since_iso: str, limit: int) -> list[tuple[str, int]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT sender, SUM(cost) AS s FROM gift_events
                   WHERE group_key=? AND ts>=?
                   GROUP BY sender ORDER BY s DESC, sender ASC LIMIT ?""",
                (group, since_iso, limit),
            ).fetchall()
        return [(r["sender"], r["s"]) for r in rows]

    def gift_recv_rank(self, group: str, since_iso: str, limit: int) -> list[tuple[str, float]]:
        with self._lock:
            rows = self._conn.execute(
                """SELECT receiver, SUM(charm_gain) AS s FROM gift_events
                   WHERE group_key=? AND ts>=?
                   GROUP BY receiver ORDER BY s DESC, receiver ASC LIMIT ?""",
                (group, since_iso, limit),
            ).fetchall()
        return [(r["receiver"], r["s"]) for r in rows]
