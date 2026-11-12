from app.db import get_db
from app.services.runner import run_job


def login(client):
    return client.post(
        "/login",
        data={"username": "admin", "password": "123456"},
        follow_redirects=True,
    )


def _mapping_id(app, catalog_id, version):
    with app.app_context():
        row = get_db().execute(
            "SELECT id FROM mapping_versions WHERE catalog_id = ? AND version = ?",
            (catalog_id, version),
        ).fetchone()
        return row["id"]


def test_run_job_dedup_duplicate_code(app, client):
    login(client)
    mid = _mapping_id(app, "alpha", 1)
    client.post(
        "/jobs",
        data={"name": "t1", "seed_path": "/mock/catalog/alpha", "mapping_version_id": mid},
        follow_redirects=True,
    )
    with app.app_context():
        job_id = get_db().execute("SELECT id FROM crawl_jobs LIMIT 1").fetchone()["id"]
        summary = run_job(job_id)
    assert summary["status"] == "done"
    assert summary["inserted"] == 2
    assert summary["skipped_dup"] == 1
    assert summary["failed"] == 1
    assert summary["total_source"] == 4


def test_mock_catalog_http(client):
    r = client.get("/mock/catalog/alpha")
    assert r.status_code == 200
    assert "市政管线测绘记录表" in r.get_data(as_text=True)
