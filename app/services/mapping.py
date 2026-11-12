"""列映射版本：每个站内目录的「来源列 → 编码/标题/备注」对应关系。

规则：
- 每保存一次产生一个新版本（版本号按目录递增）；
- 已存在的版本只读，不提供任何修改入口；
- 任务创建时绑定一个版本，创建后不能改绑；
- 解析、确认、重放的裁决全部在服务端完成。
"""

from app.db import get_db
from app.services.mock_catalog import CATALOGS


def save_mapping(catalog_id: str, code_col: str, title_col: str, note_col: str):
    """保存即产生新版本；已存在的版本永远不变。"""
    cat = CATALOGS.get(catalog_id)
    if cat is None:
        raise ValueError(f"未知目录: {catalog_id}")
    valid = {c["key"] for c in cat["columns"]}
    for label, col in (("编码", code_col), ("标题", title_col), ("备注", note_col)):
        if col not in valid:
            raise ValueError(f"{label}映射的来源列不存在: {col}")
    db = get_db()
    version = db.execute(
        "SELECT COALESCE(MAX(version), 0) + 1 AS v FROM mapping_versions WHERE catalog_id = ?",
        (catalog_id,),
    ).fetchone()["v"]
    cur = db.execute(
        """
        INSERT INTO mapping_versions (catalog_id, version, code_col, title_col, note_col)
        VALUES (?, ?, ?, ?, ?)
        """,
        (catalog_id, version, code_col, title_col, note_col),
    )
    db.commit()
    return get_mapping(cur.lastrowid)


def get_mapping(mapping_id: int):
    if mapping_id is None:
        return None
    return get_db().execute(
        "SELECT * FROM mapping_versions WHERE id = ?", (mapping_id,)
    ).fetchone()


def list_mappings(catalog_id: str | None = None):
    db = get_db()
    if catalog_id:
        return db.execute(
            "SELECT * FROM mapping_versions WHERE catalog_id = ? ORDER BY version",
            (catalog_id,),
        ).fetchall()
    return db.execute(
        "SELECT * FROM mapping_versions ORDER BY catalog_id, version"
    ).fetchall()


def version_label(mapping) -> str:
    return f"{mapping['catalog_id']} v{mapping['version']}"


def apply_mapping(rows: list[dict], mapping) -> dict:
    """按映射把来源行裁成 (编码, 标题, 备注)。

    缺编码的行不进 items，计入 failures（行号、原因、被丢弃的标题）。
    """
    items, failures = [], []
    for idx, row in enumerate(rows, start=1):
        code = (row.get(mapping["code_col"]) or "").strip()
        title = (row.get(mapping["title_col"]) or "").strip()
        note = (row.get(mapping["note_col"]) or "").strip()
        if not code:
            failures.append(
                {"row_index": idx, "reason": "来源行缺少编码，不予入库", "raw_title": title}
            )
            continue
        items.append({"code": code, "title": title, "note": note})
    return {"items": items, "failures": failures}
