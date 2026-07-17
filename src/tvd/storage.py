"""SQLite evidence/metadata store.

One row per event, with a SHA-256 of the finalized clip for integrity (see
docs/06). Pure stdlib; safe to import and unit-test anywhere.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from dataclasses import asdict
from typing import Optional

from .violations.base import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
  id           INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_utc       TEXT NOT NULL,
  type         TEXT NOT NULL,
  tier         INTEGER NOT NULL,
  confidence   REAL NOT NULL,
  degraded     INTEGER NOT NULL DEFAULT 0,
  lat          REAL, lon REAL,
  speed_mps    REAL, heading_deg REAL,
  clip_path    TEXT, clip_sha256 TEXT,
  still_path   TEXT,
  plate_text   TEXT, plate_conf REAL,
  meta_json    TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts   ON events(ts_utc);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(type);
"""


def sha256_file(path: str, chunk: int = 1 << 20) -> Optional[str]:
    if not path or not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


class EventStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def record(self, event: Event, *, clip_path: str = None, still_path: str = None,
               plate_text: str = None, plate_conf: float = None,
               gps=None, speed_mps: float = None, heading_deg: float = None) -> int:
        """Insert one event row. Computes the clip hash if a clip is present."""
        from datetime import datetime, timezone
        clip_sha = sha256_file(clip_path) if clip_path else None
        row = (
            datetime.fromtimestamp(event.ts, tz=timezone.utc).isoformat(),
            event.type, event.tier, event.confidence, int(event.degraded),
            getattr(gps, "lat", None), getattr(gps, "lon", None),
            speed_mps, heading_deg,
            clip_path, clip_sha, still_path,
            plate_text, plate_conf, json.dumps(event.meta),
        )
        with self._lock:
            cur = self._conn.execute(
                """INSERT INTO events
                   (ts_utc,type,tier,confidence,degraded,lat,lon,speed_mps,
                    heading_deg,clip_path,clip_sha256,still_path,plate_text,
                    plate_conf,meta_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", row)
            self._conn.commit()
            return int(cur.lastrowid)

    def update_clip(self, event_id: int, clip_path: str) -> None:
        """Attach a finalized clip (and its integrity hash) to an event."""
        with self._lock:
            self._conn.execute(
                "UPDATE events SET clip_path=?, clip_sha256=? WHERE id=?",
                (clip_path, sha256_file(clip_path), event_id))
            self._conn.commit()

    def recent(self, limit: int = 50) -> list[dict]:
        with self._lock:
            self._conn.row_factory = sqlite3.Row
            rows = self._conn.execute(
                "SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    def close(self):
        with self._lock:
            self._conn.close()
