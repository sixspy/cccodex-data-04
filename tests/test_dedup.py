from app.services.dedup import normalize_item_key


def test_normalize_item_key_collapses_code_space_and_case():
    a = normalize_item_key("A-002")
    b = normalize_item_key("  a-002  ")
    assert a == b
