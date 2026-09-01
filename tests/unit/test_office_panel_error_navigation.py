from catering_system.ui.office_panel_http import _error_return_target


def test_error_return_target_offer_action() -> None:
    assert _error_return_target("/offer/abc-123/mark-sent") == (
        "Zurück zum Angebot",
        "/offer/abc-123",
        "offers",
    )


def test_error_return_target_inquiry_action() -> None:
    assert _error_return_target("/inquiry/inq-1/update") == (
        "Zurück zur Anfrage",
        "/inquiry/inq-1",
        "inquiries",
    )


def test_error_return_target_order_action() -> None:
    assert _error_return_target("/order/order-1/confirmation-document/send") == (
        "Zurück zum Auftrag",
        "/order/order-1",
        "orders",
    )


def test_error_return_target_encodes_record_id() -> None:
    assert _error_return_target("/offer/a%2Fb/mark-sent") == (
        "Zurück zum Angebot",
        "/offer/a%2Fb",
        "offers",
    )


def test_error_return_target_falls_back_for_non_record_error() -> None:
    assert _error_return_target("/login") == (
        "Zur Arbeitszentrale",
        "/",
        "home",
    )
