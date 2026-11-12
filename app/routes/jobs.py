from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.db import get_db
from app.routes.auth import login_required
from app.services.mapping import get_mapping, list_mappings
from app.services.mock_catalog import CATALOGS, catalog_for_seed, seed_path_for
from app.services.runner import (
    confirm_batch,
    replay_job,
    run_job,
    update_record_title,
)

bp = Blueprint("jobs", __name__)


@bp.route("/")
@login_required
def list_jobs():
    db = get_db()
    jobs = db.execute(
        """
        SELECT j.*, m.catalog_id AS m_catalog, m.version AS m_version
        FROM crawl_jobs j
        JOIN mapping_versions m ON m.id = j.mapping_version_id
        ORDER BY j.id DESC
        """
    ).fetchall()
    counts = {
        row["job_id"]: row["c"]
        for row in db.execute(
            "SELECT job_id, COUNT(*) AS c FROM crawl_records GROUP BY job_id"
        )
    }
    # 每个任务至多一个未撤出批次：用于列表展示确认状态与失败行数
    batches = {
        row["job_id"]: row
        for row in db.execute("SELECT * FROM parse_batches WHERE superseded = 0")
    }
    return render_template(
        "jobs_list.html",
        jobs=jobs,
        counts=counts,
        batches=batches,
        seeds=sorted(seed_path_for(cid) for cid in CATALOGS),
        mappings=list_mappings(),
    )


@bp.post("/jobs")
@login_required
def create_job():
    name = request.form.get("name", "").strip()
    seed = request.form.get("seed_path", "").strip()
    version_id = request.form.get("mapping_version_id", type=int)
    if not name or not seed or not version_id:
        flash("请填写任务名、种子路径并选定列映射版本", "error")
        return redirect(url_for("jobs.list_jobs"))
    catalog_id = catalog_for_seed(seed)
    if catalog_id not in CATALOGS:
        flash("种子路径必须是已注册的 mock 目录", "error")
        return redirect(url_for("jobs.list_jobs"))
    mapping = get_mapping(version_id)
    if mapping is None:
        flash("所选列映射版本不存在", "error")
        return redirect(url_for("jobs.list_jobs"))
    if mapping["catalog_id"] != catalog_id:
        flash("列映射版本与种子目录不匹配，已拒绝（服务端裁决）", "error")
        return redirect(url_for("jobs.list_jobs"))
    db = get_db()
    db.execute(
        """
        INSERT INTO crawl_jobs (name, seed_path, mapping_version_id, status)
        VALUES (?, ?, ?, 'draft')
        """,
        (name, seed, version_id),
    )
    db.commit()
    flash(f"任务已创建，绑定 {mapping['catalog_id']} v{mapping['version']}（创建后不可改绑）", "ok")
    return redirect(url_for("jobs.list_jobs"))


@bp.post("/jobs/<int:job_id>/run")
@login_required
def run_job_view(job_id: int):
    try:
        summary = run_job(job_id)
        flash(
            f"运行完成（{summary['version']}）：写入 {summary['inserted']} 条，"
            f"去重跳过 {summary['skipped_dup']} 条，缺编码失败 {summary['failed']} 行",
            "ok",
        )
    except ValueError as e:
        flash(str(e), "error")
    except Exception as e:
        flash(f"运行失败: {e}", "error")
    return redirect(url_for("jobs.detail", job_id=job_id))


@bp.post("/jobs/<int:job_id>/replay")
@login_required
def replay_view(job_id: int):
    version_id = request.form.get("mapping_version_id", type=int)
    try:
        summary = replay_job(job_id, version_id)
        flash(
            f"已改用 {summary['version']} 重新解析：写入 {summary['inserted']} 条，"
            f"去重跳过 {summary['skipped_dup']} 条，缺编码失败 {summary['failed']} 行；"
            "旧批次已整批撤出正式结果",
            "ok",
        )
    except ValueError as e:
        flash(str(e), "error")
    except Exception as e:
        flash(f"重放失败: {e}", "error")
    return redirect(url_for("jobs.detail", job_id=job_id))


@bp.post("/jobs/<int:job_id>/confirm")
@login_required
def confirm_view(job_id: int):
    try:
        confirm_batch(job_id)
        flash("批次已确认冻结：此后不能重新解析，也不能改标题", "ok")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("jobs.detail", job_id=job_id))


@bp.post("/records/<int:record_id>/title")
@login_required
def edit_record_title(record_id: int):
    db = get_db()
    rec = db.execute(
        "SELECT job_id FROM crawl_records WHERE id = ?", (record_id,)
    ).fetchone()
    if rec is None:
        flash("记录不存在", "error")
        return redirect(url_for("jobs.list_jobs"))
    try:
        update_record_title(record_id, request.form.get("title", ""))
        flash("标题已更新", "ok")
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("jobs.detail", job_id=rec["job_id"]))


@bp.get("/jobs/<int:job_id>")
@login_required
def detail(job_id: int):
    db = get_db()
    job = db.execute("SELECT * FROM crawl_jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        flash("任务不存在", "error")
        return redirect(url_for("jobs.list_jobs"))
    bound = get_mapping(job["mapping_version_id"])
    batches = db.execute(
        """
        SELECT b.*, m.catalog_id AS m_catalog, m.version AS m_version
        FROM parse_batches b
        JOIN mapping_versions m ON m.id = b.mapping_version_id
        WHERE b.job_id = ?
        ORDER BY b.id DESC
        """,
        (job_id,),
    ).fetchall()
    batch = next((b for b in batches if not b["superseded"]), None)
    batch_mapping = get_mapping(batch["mapping_version_id"]) if batch else None
    newer_versions = []
    if batch and not batch["confirmed"] and batch_mapping:
        newer_versions = [
            m
            for m in list_mappings(batch_mapping["catalog_id"])
            if m["version"] > batch_mapping["version"]
        ]
    records = db.execute(
        "SELECT * FROM crawl_records WHERE job_id = ? ORDER BY id",
        (job_id,),
    ).fetchall()
    failures = db.execute(
        "SELECT * FROM parse_failures WHERE job_id = ? ORDER BY row_index",
        (job_id,),
    ).fetchall()
    return render_template(
        "job_detail.html",
        job=job,
        bound=bound,
        batch=batch,
        batch_mapping=batch_mapping,
        batches=batches,
        newer_versions=newer_versions,
        records=records,
        failures=failures,
    )
