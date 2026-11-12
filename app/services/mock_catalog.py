"""站内 mock 目录页：多列来源表，模拟可采集列表（无外网依赖）。

每个目录声明自己的来源列（columns），行数据按列键存放；
列映射版本再把来源列对应到 编码 / 标题 / 备注。
"""

import re
from html import escape

CATALOGS = {
    "alpha": {
        "columns": [
            {"key": "code", "label": "编码"},
            {"key": "name", "label": "名称"},
            {"key": "short", "label": "简称"},
            {"key": "note", "label": "备注"},
        ],
        "rows": [
            {"code": "A-001", "name": "市政管线测绘记录表", "short": "管线测绘表", "note": "2026 春季版"},
            {"code": "A-002", "name": "排水井巡查台账", "short": "排水井台账", "note": "周报口径"},
            {"code": "A-002", "name": "排水井巡查台账（复录）", "short": "排水井台账", "note": "重复编码，演示去重跳过"},
            {"code": "", "name": "无名补录单", "short": "补录单", "note": "缺编码，演示失败行"},
        ],
    },
    "beta": {
        "columns": [
            {"key": "code", "label": "编码"},
            {"key": "title", "label": "标题"},
            {"key": "note", "label": "备注"},
        ],
        "rows": [
            {"code": "B-101", "title": "泵站运行日报", "note": "每日"},
            {"code": "B-102", "title": "雨污分流抽检单", "note": "抽检"},
        ],
    },
}

# 首次初始化时为每个目录播种的 v1 默认映射
DEFAULT_MAPPINGS = {
    "alpha": {"code_col": "code", "title_col": "name", "note_col": "note"},
    "beta": {"code_col": "code", "title_col": "title", "note_col": "note"},
}

_SEED_RE = re.compile(r"^/mock/catalog/([A-Za-z0-9_-]+)$")


def seed_path_for(catalog_id: str) -> str:
    return f"/mock/catalog/{catalog_id}"


def catalog_for_seed(seed_path: str) -> str | None:
    m = _SEED_RE.match((seed_path or "").strip())
    return m.group(1) if m else None


def render_catalog_page(path: str):
    catalog_id = catalog_for_seed(path)
    cat = CATALOGS.get(catalog_id)
    if cat is None:
        return _not_found(path)
    head = "".join(
        f"<th data-col='{escape(c['key'])}'>{escape(c['label'])}</th>" for c in cat["columns"]
    )
    body_rows = []
    for r in cat["rows"]:
        cells = "".join(
            f"<td data-col='{escape(c['key'])}'>{escape(r.get(c['key'], ''))}</td>"
            for c in cat["columns"]
        )
        body_rows.append(f"<tr>{cells}</tr>")
    rows = "".join(body_rows)
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>Mock 目录 {escape(path)}</title></head>
<body>
<h1>采集演练目录</h1>
<p class="seed">{escape(path)}</p>
<table id="items">
<thead><tr>{head}</tr></thead>
<tbody>{rows}</tbody>
</table>
</body></html>"""


def _not_found(path: str):
    return f"<html><body><h1>404</h1><p>{escape(path)}</p></body></html>", 404


_ROW_RE = re.compile(r"<tr>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_RE = re.compile(r"<td\s+data-col='([^']+)'\s*>(.*?)</td>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")


def parse_catalog_rows(html: str) -> list[dict]:
    """把目录页 HTML 解析成来源行：{列键: 文本}，列键来自 data-col。"""
    rows = []
    for tr in _ROW_RE.findall(html):
        cells = {}
        for key, val in _CELL_RE.findall(tr):
            cells[key] = _TAG_RE.sub("", val).strip()
        if cells:
            rows.append(cells)
    return rows
