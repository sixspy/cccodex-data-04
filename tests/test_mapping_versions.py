"""列映射版本与批次冻结的六组核心测试。"""

import pytest

from app.db import get_db
from app.services.mapping import apply_mapping, get_mapping, list_mappings, save_mapping
from app.services.mock_catalog import parse_catalog_rows, render_catalog_page
from app.services.runner import (
    confirm_batch,
    replay_job,
    run_job,
    update_record_title,
)


def login(client):
    return client.post(
        "/login",
        data={"username": "admin", "password": "123456"},
        follow_redirects=True,
    )


def _mapping_id(catalog_id, version):
    return get_db().execute(
        "SELECT id FROM mapping_versions WHERE catalog_id = ? AND version = ?",
        (catalog_id, version),
    ).fetchone()["id"]


def _make_job(name="t", seed="/mock/catalog/alpha", version=1):
    db = get_db()
    mapping_id = _mapping_id("alpha", version)
    cur = db.execute(
        "INSERT INTO crawl_jobs (name, seed_path, mapping_version_id, status) VALUES (?, ?, ?, 'draft')",
        (name, seed, mapping_id),
    )
    db.commit()
    return cur.lastrowid


# 1. 旧版本不能再改：保存产生新版本，旧版本内容保持只读
def test_old_version_cannot_be_modified(app):
    with app.app_context():
        before = list_mappings("alpha")
        assert len(before) == 1
        v1 = before[0]
        v2 = save_mapping("alpha", "code", "short", "note")
        assert v2["version"] == 2
        after_v1 = get_mapping(v1["id"])
        assert after_v1["code_col"] == v1["code_col"]
        assert after_v1["title_col"] == v1["title_col"] == "name"
        assert after_v1["note_col"] == v1["note_col"]
        assert len(list_mappings("alpha")) == 2


# 2. 未确认批次重放结束后，同一编码不存在新旧两份
def test_replay_unconfirmed_leaves_single_row_per_code(app):
    with app.app_context():
        v1_id = _mapping_id("alpha", 1)
        job_id = _make_job()
        run_job(job_id)
        v2 = save_mapping("alpha", "code", "short", "note")
        summary = replay_job(job_id, v2["id"])
        assert summary["status"] == "done"

        db = get_db()
        dup = db.execute(
            """
            SELECT item_key, COUNT(*) AS c FROM crawl_records
            WHERE job_id = ? GROUP BY item_key HAVING c > 1
            """,
            (job_id,),
        ).fetchall()
        assert dup == []
        titles = {
            r["code"]: r["title"]
            for r in db.execute("SELECT code, title FROM crawl_records WHERE job_id = ?", (job_id,))
        }
        assert titles["A-001"] == "管线测绘表"  # v2 标题取自 short 列
        assert "市政管线测绘记录表" not in titles.values()
        # 旧批次已整批撤出
        superseded = db.execute(
            "SELECT COUNT(*) AS c FROM parse_batches WHERE job_id = ? AND superseded = 1",
            (job_id,),
        ).fetchone()["c"]
        assert superseded == 1
        # 任务创建时绑定的版本不变
        job = db.execute("SELECT * FROM crawl_jobs WHERE id = ?", (job_id,)).fetchone()
        assert job["mapping_version_id"] == v1_id


# 3. 已确认的批次拒绝重放，也拒绝改标题
def test_confirmed_batch_rejects_replay_and_title_edit(app):
    with app.app_context():
        job_id = _make_job()
        run_job(job_id)
        confirm_batch(job_id)
        v2 = save_mapping("alpha", "code", "short", "note")
        with pytest.raises(ValueError, match="冻结"):
            replay_job(job_id, v2["id"])
        rec_id = get_db().execute(
            "SELECT id FROM crawl_records WHERE job_id = ? LIMIT 1", (job_id,)
        ).fetchone()["id"]
        with pytest.raises(ValueError, match="冻结"):
            update_record_title(rec_id, "试图改标题")


# 4. 缺编码的来源行计入失败且标题不入库
def test_missing_code_counts_failed_and_not_stored(app):
    with app.app_context():
        job_id = _make_job()
        summary = run_job(job_id)
        assert summary["failed"] == 1
        db = get_db()
        leaked = db.execute(
            "SELECT COUNT(*) AS c FROM crawl_records WHERE job_id = ? AND title = '无名补录单'",
            (job_id,),
        ).fetchone()["c"]
        assert leaked == 0
        failures = db.execute(
            "SELECT * FROM parse_failures WHERE job_id = ?", (job_id,)
        ).fetchall()
        assert len(failures) == 1
        assert "缺少编码" in failures[0]["reason"]
        assert failures[0]["raw_title"] == "无名补录单"


# 5. 两个版本解析出的标题不一样
def test_two_versions_parse_different_titles(app):
    with app.app_context():
        v2 = save_mapping("alpha", "code", "short", "note")
        html = render_catalog_page("/mock/catalog/alpha")
        rows = parse_catalog_rows(html)
        t1 = {i["code"]: i["title"] for i in apply_mapping(rows, get_mapping(_mapping_id("alpha", 1)))["items"]}
        t2 = {i["code"]: i["title"] for i in apply_mapping(rows, v2)["items"]}
        assert t1["A-001"] == "市政管线测绘记录表"
        assert t2["A-001"] == "管线测绘表"
        assert t1["A-001"] != t2["A-001"]


# 6. 上一次运行尚未结束时拒绝再次触发
def test_running_job_rejects_retrigger(app):
    with app.app_context():
        job_id = _make_job()
        run_job(job_id)
        db = get_db()
        db.execute("UPDATE crawl_jobs SET status = 'running' WHERE id = ?", (job_id,))
        db.commit()
        with pytest.raises(ValueError, match="尚未结束"):
            run_job(job_id)
        with pytest.raises(ValueError, match="尚未结束"):
            replay_job(job_id, _mapping_id("alpha", 1))


# 附加：列表页展示绑定版本、确认状态与失败行数
def test_list_shows_version_confirmation_and_failures(app, client):
    login(client)
    with app.app_context():
        mid = _mapping_id("alpha", 1)
    client.post(
        "/jobs",
        data={"name": "t1", "seed_path": "/mock/catalog/alpha", "mapping_version_id": mid},
        follow_redirects=True,
    )
    with app.app_context():
        job_id = get_db().execute("SELECT id FROM crawl_jobs LIMIT 1").fetchone()["id"]
        run_job(job_id)
    html = client.get("/").get_data(as_text=True)
    assert "alpha v1" in html
    assert "未确认" in html
    assert "<td>1</td>" in html  # 失败行数
