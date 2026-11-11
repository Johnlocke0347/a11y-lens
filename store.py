"""Persistent scan history (SQLite) + on-disk report files.

Inside Hermes the database lives in ``<HERMES_HOME>/plugin-data/a11y-lens/`` (via the public
``plugins.plugin_storage`` helpers) so it survives plugin updates and follows the active profile.
Outside Hermes (unit tests, the standalone CLI) it falls back to an explicit directory.

Screenshot storage note: screenshots are per-element PNGs capped at 180 000 bytes and 24 per
scan (enforced in worker.py), base64-encoded inside the scan record stored as JSON in SQLite.
With the default retention of 100 scans (`keep_scans` / `KEEP_DEFAULT`) the DB is bounded:
worst-case ~5.7 MiB per scan → ~570 MiB for 100 scans; typical scans are far smaller.
No silent discarding of evidence is performed; operators can lower `keep_scans` if disk usage
is a concern. A redesign to externalise screenshots was considered but rejected for this
narrow remediation because it would change the storage schema and complicate history handling
without clear benefit given the existing bounds. See docs/SAFETY.md § Screenshot storage.
"""


from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PLUGIN_NAME = "a11y-lens"
KEEP_DEFAULT = 100

_SCHEMA = """
CREATE TABLE IF NOT EXISTS scans (
    n            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at   TEXT NOT NULL,
    label        TEXT NOT NULL,
    scan_url     TEXT NOT NULL,
    status       TEXT NOT NULL,
    error_code   TEXT,
    error_msg    TEXT,
    violations   INTEGER NOT NULL DEFAULT 0,
    instances    INTEGER NOT NULL DEFAULT 0,
    review       INTEGER NOT NULL DEFAULT 0,
    duration_ms  INTEGER,
    note         TEXT,
    record_json  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scans_label ON scans(label, n);
"""


def scan_id_for(n: int) -> str:
    return f"scan-{n:04d}"


def parse_scan_id(value: Any) -> int | None:
    """Accept ``scan-0007``, ``scan 7``, ``s7``, ``7``, 7."""
    if isinstance(value, int):
        return value
    m = re.fullmatch(r"\s*(?:scan|s)?[-_ ]*0*(\d+)\s*", str(value or ""), re.I)
    return int(m.group(1)) if m else None


class Store:
    def __init__(self, conn: sqlite3.Connection, data_dir: Path):
        self.conn = conn
        self.data_dir = Path(data_dir)
        self.reports_dir = self.data_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._lock:
            self.conn.executescript(_SCHEMA)
            self.conn.commit()

    # -- construction ---------------------------------------------------------------------
    @classmethod
    def open_default(cls, data_dir: Path | None = None) -> "Store":
        if data_dir is None:
            try:
                from plugins.plugin_storage import plugin_data_dir, plugin_db  # public API

                return cls(plugin_db(PLUGIN_NAME), plugin_data_dir(PLUGIN_NAME))
            except ImportError:
                data_dir = Path.home() / ".a11y-lens"
        data_dir = Path(data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(data_dir / "data.db"), check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return cls(conn, data_dir)

    # -- writes ---------------------------------------------------------------------------
    def save(self, record: dict[str, Any], keep: int = KEEP_DEFAULT) -> str:
        """Persist a scan record; returns its id.  ``record`` must carry summary fields."""
        s = record["summary"]
        err = record.get("error") or {}
        with self._lock:
            cur = self.conn.execute(
                "INSERT INTO scans(created_at,label,scan_url,status,error_code,error_msg,violations,instances,review,"
                "duration_ms,note,record_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record["created_at"], record["target"]["label"], record["target"]["scan_url"], record["status"],
                    err.get("code"), err.get("message"), s["rules_violated"], s["instances"], s["needs_review_rules"],
                    record.get("duration_ms"), record.get("note"), "{}",
                ),
            )
            n = int(cur.lastrowid)
            record["id"] = scan_id_for(n)
            self.conn.execute("UPDATE scans SET record_json=? WHERE n=?", (json.dumps(record, ensure_ascii=False), n))
            # retention: keep the newest `keep`
            self.conn.execute("DELETE FROM scans WHERE n NOT IN (SELECT n FROM scans ORDER BY n DESC LIMIT ?)", (int(keep),))
            self.conn.commit()
        return record["id"]

    # -- reads ----------------------------------------------------------------------------
    def get(self, scan_id: Any) -> dict[str, Any] | None:
        n = parse_scan_id(scan_id)
        if n is None:
            return None
        with self._lock:
            row = self.conn.execute("SELECT record_json FROM scans WHERE n=?", (n,)).fetchone()
        return json.loads(row[0]) if row else None

    def list(self, label: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        q = "SELECT n,created_at,label,status,violations,instances,review,error_code,note FROM scans"
        args: list[Any] = []
        if label:
            q += " WHERE label=?"
            args.append(label)
        q += " ORDER BY n DESC LIMIT ?"
        args.append(int(limit))
        with self._lock:
            rows = self.conn.execute(q, args).fetchall()
        return [
            {"id": scan_id_for(r[0]), "created_at": r[1], "target": r[2], "status": r[3], "rules_violated": r[4],
             "instances": r[5], "needs_review_rules": r[6], "error_code": r[7], "note": r[8]}
            for r in rows
        ]

    def latest(self, label: str | None = None, *, status: str | None = None, before_n: int | None = None) -> dict[str, Any] | None:
        q, args = "SELECT record_json FROM scans WHERE 1=1", []
        if label:
            q += " AND label=?"; args.append(label)
        if status:
            q += " AND status=?"; args.append(status)
        if before_n:
            q += " AND n<?"; args.append(before_n)
        q += " ORDER BY n DESC LIMIT 1"
        with self._lock:
            row = self.conn.execute(q, args).fetchone()
        return json.loads(row[0]) if row else None

    # -- files ----------------------------------------------------------------------------
    def report_path(self, name: str, ext: str) -> Path:
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)
        return self.reports_dir / f"{safe}.{ext}"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
