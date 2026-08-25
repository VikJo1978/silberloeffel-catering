from pathlib import Path


def test_issue152_order_history_architecture_note_keeps_history_read_only() -> None:
    text = Path(
        "docs/architecture/ISSUE_152_CUSTOMER_ORDER_HISTORY_PROJECTION_V1.md"
    ).read_text()

    assert "No persisted CRM-history table" in text
    assert "No inferred preference is written from history" in text
    assert (
        "editing explicit gastronomic preferences does not rewrite historical facts"
        in text
    )
