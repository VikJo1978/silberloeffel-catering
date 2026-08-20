"""Regression coverage for the asynchronous kitchen-print waiting state."""

from types import SimpleNamespace

from catering_system.ui.office_panel_order_detail import (
    OrderDetailFormFields,
    _primary_action,
)


class _PrintContext:
    def can(self, permission: str) -> bool:
        return permission == "orders.print.confirm"


def _forms(*, action_available: bool) -> OrderDetailFormFields:
    return OrderDetailFormFields(
        csrf_input="<input name='csrf'>",
        print_confirm_command_fields={"version-1": "<input name='command'>"},
        effective_command_fields={},
        ready_command_fields="",
        cancel_command_fields="",
        version_command_fields="",
        payment_command_fields="",
        print_confirm_button_labels={"version-1": "Küchendruck starten"},
        print_status_messages={"version-1": "Druckauftrag wird verarbeitet …"},
        print_action_available={"version-1": action_available},
    )


def _render_print_action(*, action_available: bool) -> str:
    return _primary_action(
        SimpleNamespace(cancelled_at=None, order_id="order-1"),
        SimpleNamespace(order_version_id="version-1"),
        {"action": "print-confirm"},
        _forms(action_available=action_available),
        ready=None,
        confirmation=None,
        live_preview=None,
        source_inquiry=None,
        operational_data=None,
        operational_pause={"active": False},
        context=_PrintContext(),
    )


def test_processing_print_job_shows_waiting_state_and_auto_refresh() -> None:
    html = _render_print_action(action_available=False)

    assert "Druckauftrag gesendet" in html
    assert "warte auf Druckbestätigung" in html
    assert "window.location.reload()" in html
    assert "1500" in html
    assert 'action="/order/order-1/print-confirm"' not in html
    assert "Küchenzettel öffnen" in html


def test_available_print_job_keeps_single_start_action_without_auto_refresh() -> None:
    html = _render_print_action(action_available=True)

    assert "Küchenzettel für den aktuellen Stand drucken" in html
    assert "Küchendruck starten" in html
    assert 'action="/order/order-1/print-confirm"' in html
    assert "window.location.reload()" not in html
