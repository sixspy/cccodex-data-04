import json
import sqlite3

from flask import current_app

from app.db import db_transaction, get_db
from app.services.dedup import normalize_item_key
from app.services.mapping import apply_mapping, get_mapping, version_label
from app.services.mock_catalog import CATALOGS, catalog_for_seed, parse_catalog_rows, render_catalog_page


def _get_job(db, job_id: int):
    return db.execute("SELECT * FROM crawl_jobs WHERE id = ?", (job_id,)).fetchone()


def current_batch(db, job_id: int):
    """任务当前生效的批次（未被撤出的最新一批）。"""
    return db.execute(
        "SELECT * FROM parse_batches WHERE job_id = ? AND superseded = 0 ORDER BY id DESC LIMIT 1",
        (job_id,),
    ).fetchone()


def _load_source_rows(job):
    catalog_id = catalog_for_seed(job["seed_path"])
    if catalog_id not in CATALOGS:
        return None
    html = render_catalog_page(job["seed_path"])
    if isinstance(html, tuple):
        html = html[0]
    return parse_catalog_rows(html)


def _write_batch(tx, job_id: int, batch_id: int, parsed: dict):
    inserted = 0
    skipped_dup = 0
    for it in parsed["items"]:
        key = normalize_item_key(it["code"])
        try:
            tx.execute(
                """
                INSERT INTO crawl_records (job_id, batch_id, item_key, code, title, note, payload_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    batch_id,
                    key,
                    it["code"],
                    it["title"],
                    it["note"],
                    json.dumps(it, ensure_ascii=False),
                ),
            )
            inserted += 1
        except sqlite3.IntegrityError:
            skipped_dup += 1
    for f in parsed["failures"]:
        tx.execute(
            """
            INSERT INTO parse_failures (job_id, batch_id, row_index, reason, raw_title)
            VALUES (?, ?, ?, ?, ?)
            """,
            (job_id, batch_id, f["row_index"], f["reason"], f["raw_title"]),
        )
    tx.execute(
        """
        UPDATE parse_batches
        SET inserted_count = ?, failed_count = ?, finished_at = datetime('now')
        WHERE id = ?
        """,
        (inserted, len(parsed["failures"]), batch_id),
    )
    return inserted, skipped_dup


def run_job(job_id: int) -> dict:
    """首次运行：按任务创建时绑定的映射版本解析。"""
    db = get_db()
    job = _get_job(db, job_id)
    if job is None:
        raise ValueError("任务不存在")
    if job["status"] == "running":
        raise ValueError("上一次运行尚未结束，不能再次触发")
    if job["status"] != "draft":
        raise ValueError("任务已运行过；未确认批次请改用「重新解析」")

    mapping = get_mapping(job["mapping_version_id"])
    if mapping is None:
        raise ValueError("任务绑定的映射版本不存在")

    rows = _load_source_rows(job)
    if rows is None:
        db.execute(
            "UPDATE crawl_jobs SET status = 'failed', finished_at = datetime('now') WHERE id = ?",
            (job_id,),
        )
        db.commit()
        return {"status": "failed", "reason": "unknown seed", "inserted": 0, "skipped_dup": 0, "failed": 0}

    parsed = apply_mapping(rows, mapping)
    with db_transaction() as tx:
        tx.execute(
            "UPDATE crawl_jobs SET status = 'running', finished_at = NULL WHERE id = ?",
            (job_id,),
        )
        batch_id = tx.execute(
            "INSERT INTO parse_batches (job_id, mapping_version_id) VALUES (?, ?)",
            (job_id, mapping["id"]),
        ).lastrowid
        inserted, skipped_dup = _write_batch(tx, job_id, batch_id, parsed)
        tx.execute(
            "UPDATE crawl_jobs SET status = 'done', finished_at = datetime('now') WHERE id = ?",
            (job_id,),
        )

    summary = {
        "status": "done",
        "batch_id": batch_id,
        "version": version_label(mapping),
        "inserted": inserted,
        "skipped_dup": skipped_dup,
        "failed": len(parsed["failures"]),
        "total_source": len(rows),
    }
    current_app.logger.info("job %s run: %s", job_id, summary)
    return summary


def replay_job(job_id: int, mapping_version_id: int) -> dict:
    """未确认批次整批换用更新版本重新解析。

    先把本批从正式结果里全部撤出，再按新版本写入，
    同一编码不会同时留下新旧两行。已确认批次冻结，拒绝重放。
    """
    db = get_db()
    job = _get_job(db, job_id)
    if job is None:
        raise ValueError("任务不存在")
    if job["status"] == "running":
        raise ValueError("上一次运行尚未结束，不能再次触发")
    batch = current_batch(db, job_id)
    if batch is None:
        raise ValueError("任务尚未运行，无批次可重新解析")
    if batch["confirmed"]:
        raise ValueError("批次已确认冻结，不能重新解析")

    new_mapping = get_mapping(mapping_version_id)
    if new_mapping is None:
        raise ValueError("映射版本不存在")
    catalog_id = catalog_for_seed(job["seed_path"])
    if new_mapping["catalog_id"] != catalog_id:
        raise ValueError("映射版本不属于该任务的目录")
    old_mapping = get_mapping(batch["mapping_version_id"])
    if new_mapping["version"] <= old_mapping["version"]:
        raise ValueError("只能改用更新的版本重新解析")

    rows = _load_source_rows(job)
    if rows is None:
        raise ValueError("种子目录不可用")
    parsed = apply_mapping(rows, new_mapping)

    with db_transaction() as tx:
        tx.execute(
            "UPDATE crawl_jobs SET status = 'running', finished_at = NULL WHERE id = ?",
            (job_id,),
        )
        # 先整批撤出正式结果与失败记录，再按新版本写入
        tx.execute("DELETE FROM crawl_records WHERE job_id = ?", (job_id,))
        tx.execute("DELETE FROM parse_failures WHERE job_id = ?", (job_id,))
        tx.execute(
            "UPDATE parse_batches SET superseded = 1 WHERE job_id = ? AND superseded = 0",
            (job_id,),
        )
        batch_id = tx.execute(
            "INSERT INTO parse_batches (job_id, mapping_version_id) VALUES (?, ?)",
            (job_id, new_mapping["id"]),
        ).lastrowid
        inserted, skipped_dup = _write_batch(tx, job_id, batch_id, parsed)
        tx.execute(
            "UPDATE crawl_jobs SET status = 'done', finished_at = datetime('now') WHERE id = ?",
            (job_id,),
        )

    summary = {
        "status": "done",
        "batch_id": batch_id,
        "version": version_label(new_mapping),
        "inserted": inserted,
        "skipped_dup": skipped_dup,
        "failed": len(parsed["failures"]),
        "total_source": len(rows),
    }
    current_app.logger.info("job %s replay: %s", job_id, summary)
    return summary


def confirm_batch(job_id: int) -> dict:
    """确认当前批次：确认后冻结，不能重新解析、不能改标题。"""
    db = get_db()
    job = _get_job(db, job_id)
    if job is None:
        raise ValueError("任务不存在")
    if job["status"] == "running":
        raise ValueError("上一次运行尚未结束，不能确认批次")
    batch = current_batch(db, job_id)
    if batch is None:
        raise ValueError("任务尚未运行，无批次可确认")
    if batch["confirmed"]:
        raise ValueError("批次已确认，无需重复确认")
    db.execute("UPDATE parse_batches SET confirmed = 1 WHERE id = ?", (batch["id"],))
    db.commit()
    current_app.logger.info("job %s batch %s confirmed", job_id, batch["id"])
    return {"batch_id": batch["id"], "confirmed": True}


def update_record_title(record_id: int, title: str) -> dict:
    """未确认批次允许手工改标题；已确认批次冻结，拒绝修改。"""
    db = get_db()
    rec = db.execute(
        """
        SELECT r.id, r.job_id, b.confirmed AS batch_confirmed
        FROM crawl_records r
        JOIN parse_batches b ON b.id = r.batch_id
        WHERE r.id = ?
        """,
        (record_id,),
    ).fetchone()
    if rec is None:
        raise ValueError("记录不存在")
    if rec["batch_confirmed"]:
        raise ValueError("批次已确认冻结，不能改标题")
    title = (title or "").strip()
    if not title:
        raise ValueError("标题不能为空")
    db.execute("UPDATE crawl_records SET title = ? WHERE id = ?", (title, record_id))
    db.commit()
    return {"record_id": record_id, "title": title}
