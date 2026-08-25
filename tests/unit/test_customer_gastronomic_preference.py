from datetime import UTC, datetime, timedelta

import pytest

from catering_system.domain.customer_gastronomic_preference import (
    CustomerGastronomicPreference,
    validate_customer_gastronomic_preference,
    validate_preference_kind,
    validate_preference_source,
)


def _preference(**overrides: object) -> CustomerGastronomicPreference:
    created_at = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
    values: dict[str, object] = {
        "preference_id": "pref-1",
        "customer_id": "customer-1",
        "kind": "favorite_dish",
        "value": "Mini-Frikadellen",
        "source": "customer_stated",
        "created_at": created_at,
        "updated_at": created_at,
    }
    values.update(overrides)
    return CustomerGastronomicPreference(**values)  # type: ignore[arg-type]


def test_valid_explicit_preference_is_accepted() -> None:
    preference = _preference()
    assert validate_customer_gastronomic_preference(preference) is preference


@pytest.mark.parametrize("source", ["inferred", "history", "system"])
def test_inferred_or_system_sources_are_rejected(source: str) -> None:
    with pytest.raises(ValueError, match="source must be explicit"):
        validate_preference_source(source)


def test_known_explicit_sources_are_distinct() -> None:
    assert validate_preference_source("customer_stated") == "customer_stated"
    assert validate_preference_source("office_recorded") == "office_recorded"


def test_unknown_preference_kind_is_rejected() -> None:
    with pytest.raises(ValueError, match="preference kind"):
        validate_preference_kind("religion_inferred")


def test_value_must_be_non_empty_and_already_trimmed() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        validate_customer_gastronomic_preference(_preference(value=""))
    with pytest.raises(ValueError, match="already be trimmed"):
        validate_customer_gastronomic_preference(_preference(value=" vegan "))


def test_identifiers_and_timestamps_are_validated() -> None:
    with pytest.raises(ValueError, match="customer_id"):
        validate_customer_gastronomic_preference(_preference(customer_id=" "))
    with pytest.raises(ValueError, match="created_at must be timezone-aware"):
        validate_customer_gastronomic_preference(
            _preference(created_at=datetime(2026, 8, 25, 12, 0))
        )
    with pytest.raises(ValueError, match="updated_at must not be earlier"):
        created = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
        validate_customer_gastronomic_preference(
            _preference(created_at=created, updated_at=created - timedelta(seconds=1))
        )
