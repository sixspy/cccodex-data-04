from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.routes.auth import login_required
from app.services.mapping import list_mappings, save_mapping, version_label
from app.services.mock_catalog import CATALOGS

bp = Blueprint("mappings", __name__)


@bp.get("/mappings")
@login_required
def list_all():
    by_catalog: dict[str, list] = {}
    for m in list_mappings():
        by_catalog.setdefault(m["catalog_id"], []).append(m)
    return render_template("mappings.html", catalogs=CATALOGS, by_catalog=by_catalog)


@bp.post("/mappings")
@login_required
def create():
    catalog_id = request.form.get("catalog_id", "").strip()
    code_col = request.form.get("code_col", "").strip()
    title_col = request.form.get("title_col", "").strip()
    note_col = request.form.get("note_col", "").strip()
    try:
        mapping = save_mapping(catalog_id, code_col, title_col, note_col)
        flash(
            f"已保存为新版本 {version_label(mapping)}；旧版本保持不变，只能查看",
            "ok",
        )
    except ValueError as e:
        flash(str(e), "error")
    return redirect(url_for("mappings.list_all"))
