import sqlite3
from contextlib import contextmanager

from flask import current_app, g

from app.services.mock_catalog import DEFAULT_MAPPINGS


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(e=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def db_transaction():
    db = get_db()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise


def init_db(app):
    with app.app_context():
        db = get_db()
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS mapping_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                catalog_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                code_col TEXT NOT NULL,
                title_col TEXT NOT NULL,
                note_col TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(catalog_id, version)
            );
            CREATE TABLE IF NOT EXISTS crawl_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                seed_path TEXT NOT NULL,
                mapping_version_id INTEGER NOT NULL REFERENCES mapping_versions(id),
                status TEXT NOT NULL DEFAULT 'draft',
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS parse_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES crawl_jobs(id) ON DELETE CASCADE,
                mapping_version_id INTEGER NOT NULL REFERENCES mapping_versions(id),
                confirmed INTEGER NOT NULL DEFAULT 0,
                superseded INTEGER NOT NULL DEFAULT 0,
                inserted_count INTEGER NOT NULL DEFAULT 0,
                failed_count INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
                finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS crawl_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES crawl_jobs(id) ON DELETE CASCADE,
                batch_id INTEGER NOT NULL REFERENCES parse_batches(id) ON DELETE CASCADE,
                item_key TEXT NOT NULL,
                code TEXT NOT NULL,
                title TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL,
                fetched_at TEXT NOT NULL DEFAULT (datetime('now')),
                UNIQUE(job_id, item_key)
            );
            CREATE TABLE IF NOT EXISTS parse_failures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                job_id INTEGER NOT NULL REFERENCES crawl_jobs(id) ON DELETE CASCADE,
                batch_id INTEGER NOT NULL REFERENCES parse_batches(id) ON DELETE CASCADE,
                row_index INTEGER NOT NULL,
                reason TEXT NOT NULL,
                raw_title TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        # 首次启动为每个目录播种 v1 默认映射；之后版本只增不改
        seeded = db.execute("SELECT COUNT(*) AS c FROM mapping_versions").fetchone()["c"]
        if seeded == 0:
            for catalog_id, m in DEFAULT_MAPPINGS.items():
                db.execute(
                    """
                    INSERT INTO mapping_versions (catalog_id, version, code_col, title_col, note_col)
                    VALUES (?, 1, ?, ?, ?)
                    """,
                    (catalog_id, m["code_col"], m["title_col"], m["note_col"]),
                )
        db.commit()
