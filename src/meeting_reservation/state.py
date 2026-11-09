"""SQLite 操作台账与待处理申请；仅适用于单机共享持久卷部署。

同一 operation_id 只允许同一用户和同一 payload；运行中/未知操作不自动重放。
"""

import json
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .identity import Actor


class StateError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class StateStore:
    def __init__(self, path: str):
        if path == ":memory:":
            raise ValueError("操作台账必须持久化，不能使用内存 SQLite")
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS operations (
                    operation_id TEXT PRIMARY KEY,
                    actor_key TEXT NOT NULL,
                    request_hash TEXT NOT NULL,
                    state TEXT NOT NULL,
                    result_json TEXT,
                    started_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pending_requests (
                    pending_id TEXT PRIMARY KEY,
                    actor_key TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    intent_json TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    used INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            db.commit()

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def begin(self, actor: Actor, op_id: str, digest: str) -> dict | None:
        """返回原结果，或插入一条未完成操作。并发请求只能有一个执行者。"""
        now = int(time.time())
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT * FROM operations WHERE operation_id = ?", (op_id,)
                ).fetchone()
                if row is not None:
                    if row["actor_key"] != actor.key:
                        raise StateError("DENIED")
                    if row["request_hash"] != digest:
                        raise StateError("IDEMPOTENCY_MISMATCH")
                    previous = json.loads(row["result_json"]) if row["result_json"] else {
                        "status": "UNKNOWN" if now - row["started_at"] >= 30
                        else "IN_PROGRESS"
                    }
                    db.commit()
                    return previous
                db.execute(
                    """INSERT INTO operations
                    (operation_id, actor_key, request_hash, state, started_at, updated_at)
                    VALUES (?, ?, ?, 'IN_PROGRESS', ?, ?)""",
                    (op_id, actor.key, digest, now, now),
                )
                db.commit()
                return None
            except Exception:
                db.rollback()
                raise

    def finish(self, op_id: str, result: dict) -> None:
        with closing(self._connect()) as db:
            db.execute(
                """UPDATE operations
                SET state = ?, result_json = ?, updated_at = ?
                WHERE operation_id = ?""",
                (result["status"], _dump(result), int(time.time()), op_id),
            )
            db.commit()

    def operation(self, actor: Actor, op_id: str) -> dict | None:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM operations WHERE operation_id = ?", (op_id,)
            ).fetchone()
        if row is None:
            return None
        if row["actor_key"] != actor.key:
            raise StateError("DENIED")
        if row["result_json"]:
            return json.loads(row["result_json"])
        return {
            "status": "UNKNOWN" if int(time.time()) - row["started_at"] >= 30
            else "IN_PROGRESS"
        }

    def create_pending(
        self, actor: Actor, intent: dict, options: list[dict]
    ) -> tuple[str, int, str]:
        pending_id = "pending_" + uuid.uuid4().hex
        expires = (
            datetime.now(timezone.utc) + timedelta(minutes=30)
        ).isoformat(timespec="seconds")
        with closing(self._connect()) as db:
            db.execute(
                """INSERT INTO pending_requests
                (pending_id, actor_key, revision, intent_json, options_json, expires_at)
                VALUES (?, ?, 1, ?, ?, ?)""",
                (pending_id, actor.key, _dump(intent), _dump(options), expires),
            )
            db.commit()
        return pending_id, 1, expires

    def read_pending(
        self, actor: Actor, pending_id: str, revision: int
    ) -> tuple[dict, list[dict]]:
        """补参校验前先读取，不因为输入错误消耗申请。"""
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT * FROM pending_requests WHERE pending_id = ?", (pending_id,)
            ).fetchone()
        if row is None:
            raise StateError("NOT_FOUND")
        self._validate_pending(row, actor, revision)
        return json.loads(row["intent_json"]), json.loads(row["options_json"])

    @staticmethod
    def _validate_pending(row: sqlite3.Row, actor: Actor, revision: int) -> None:
        if row["actor_key"] != actor.key:
            raise StateError("DENIED")
        if row["used"] or row["revision"] != revision:
            raise StateError("STALE_PENDING")
        if datetime.fromisoformat(row["expires_at"]) < datetime.now(timezone.utc):
            raise StateError("EXPIRED")

    def consume_pending(
        self, actor: Actor, pending_id: str, revision: int
    ) -> tuple[dict, list[dict]]:
        with closing(self._connect()) as db:
            try:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT * FROM pending_requests WHERE pending_id = ?",
                    (pending_id,),
                ).fetchone()
                if row is None:
                    raise StateError("NOT_FOUND")
                self._validate_pending(row, actor, revision)
                db.execute(
                    "UPDATE pending_requests SET used = 1 WHERE pending_id = ?",
                    (pending_id,),
                )
                db.commit()
                return json.loads(row["intent_json"]), json.loads(row["options_json"])
            except Exception:
                db.rollback()
                raise
