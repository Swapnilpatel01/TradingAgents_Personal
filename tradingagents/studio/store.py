"""Small transactional store. Each operation owns its SQLite connection."""

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.connect() as db:
            db.execute("CREATE TABLE IF NOT EXISTS records "
                       "(kind TEXT, id TEXT, body TEXT, PRIMARY KEY(kind,id))")

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def put(self, kind, body, key=None):
        key = key or uuid.uuid4().hex
        record = {**body, "id": key, "updated_at": datetime.now(UTC).isoformat()}
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO records VALUES (?,?,?)",
                       (kind, key, json.dumps(record, allow_nan=False)))
        return record

    def get(self, kind, key):
        with self.connect() as db:
            row = db.execute("SELECT body FROM records WHERE kind=? AND id=?", (kind, key)).fetchone()
        if not row:
            raise KeyError(key)
        return json.loads(row[0])

    def list(self, kind):
        with self.connect() as db:
            rows = db.execute("SELECT body FROM records WHERE kind=? ORDER BY rowid DESC", (kind,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def delete(self, kind, key):
        with self.connect() as db:
            db.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, key))
