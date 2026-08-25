from __future__ import annotations

from pathlib import Path

from issue171_apply_return_logistics_wire import main as apply_return_logistics_wire


def main() -> None:
    apply_return_logistics_wire()

    path = Path("tests/unit/test_issue171_return_logistics_contract.py")
    text = path.read_text()

    old_import = '''    _charges_definition,
    _default_positions,
    _snapshot,
)'''
    new_import = '''    _charges_definition,
    _default_positions,
    _dishware_line_def,
    _snapshot,
)'''
    assert text.count(old_import) == 1, text.count(old_import)
    text = text.replace(old_import, new_import, 1)

    old = "_charges_definition(dishware_lines=[])"
    count = text.count(old)
    assert count == 5, count
    text = text.replace(
        old,
        "_charges_definition(dishware_lines=[_dishware_line_def()])",
    )
    path.write_text(text)


if __name__ == "__main__":
    main()
