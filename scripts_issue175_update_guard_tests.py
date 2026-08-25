from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


path = Path("tests/unit/test_offer_repository.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '        (9, "offer_version_charges_definition"),\n    ]',
    '        (9, "offer_version_charges_definition"),\n'
    '        (10, "offer_version_logistics_timing"),\n'
    '    ]',
    "offer migration expectation",
)
path.write_text(text, encoding="utf-8")

path = Path("tests/unit/test_sqlite_repositories.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '        ("orders", 9),  # frozen fulfillment mode in operational context\n    ]',
    '        ("orders", 9),  # frozen fulfillment mode in operational context\n'
    '        ("orders", 10),  # canonical delivery timing on immutable order versions\n'
    '    ]',
    "order migration expectation",
)
path.write_text(text, encoding="utf-8")

path = Path("tests/unit/test_order_service.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '        "changed_fields",\n    }',
    '        "changed_fields",\n'
    '        "delivery_date_local",\n'
    '        "delivery_window_start_local",\n'
    '        "delivery_window_end_local",\n'
    '    }',
    "OrderVersion allowed field guard",
)
path.write_text(text, encoding="utf-8")
