"""同一任务内去重键：规范化编码，供落库 UNIQUE 约束使用。"""

import re


def normalize_item_key(code: str) -> str:
    """编码规范化：去空白、统一大小写，使同一编码只落库一行。"""
    return re.sub(r"\s+", "", (code or "").strip()).upper()
