import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from .config import DATABASE


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


@contextmanager
def connect():
    con = sqlite3.connect(DATABASE, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys = ON')
    con.execute('PRAGMA busy_timeout=30000')
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db():
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
          id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, name TEXT NOT NULL,
          password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK (role IN ('admin','analyst','viewer')),
          active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sources (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, source_url TEXT, text TEXT NOT NULL,
          word_count INTEGER NOT NULL, uploaded_by TEXT NOT NULL REFERENCES users(id),
          created_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS fingerprints (
          source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
          hash TEXT NOT NULL, PRIMARY KEY (source_id, hash)
        );
        CREATE INDEX IF NOT EXISTS ix_fingerprints_hash ON fingerprints(hash);
        CREATE TABLE IF NOT EXISTS scans (
          id TEXT PRIMARY KEY, title TEXT NOT NULL, text TEXT NOT NULL,
          created_by TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL,
          word_count INTEGER NOT NULL, similarity_score REAL, ai_status TEXT NOT NULL,
          ai_probability REAL, result_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_scans_created ON scans(created_at DESC);
        CREATE TABLE IF NOT EXISTS audit (
          id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, user_id TEXT,
          action TEXT NOT NULL, object_id TEXT, details TEXT
        );
        CREATE TABLE IF NOT EXISTS login_limits (
          key TEXT PRIMARY KEY, failures INTEGER NOT NULL,
          window_start REAL NOT NULL, block_until REAL NOT NULL DEFAULT 0
        );
        ''')


def audit(db, user_id, action, object_id=None, details=None):
    db.execute('INSERT INTO audit(at,user_id,action,object_id,details) VALUES(?,?,?,?,?)',
               (now(), user_id, action, object_id, details))
