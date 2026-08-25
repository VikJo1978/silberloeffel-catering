from datetime import UTC, datetime, timedelta

import pytest

from catering_system.domain.customer_gastronomic_preference import (
    CustomerGastronomicPreference,
)
from catering_system.repositories.in_memory_customer_gastronomic_preference_repository import (
    InMemoryCustomerGastronomicPreferenceRepository,
)
from catering_system.repositories.sqlite_customer_gastronomic_preference_repository import (
    SQLiteCustomerGastronomicPreferenceRepository,
)


def _preference(
    preference_id: str,
    *,
    customer_id: str = "customer-1",
    kind: str = "favorite_dish",
    value: str = "Mini-Frikadellen",
    source: str = "customer_stated",
    updated_offset: int = 0,
) -> CustomerGastronomicPreference:
    created_at = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
    return CustomerGastronomicPreference(
        preference_id=preference_id,
        customer_id=customer_id,
        kind=kind,  # type: ignore[arg-type]
        value=value,
        source=source,  # type: ignore[arg-type]
        created_at=created_at,
        updated_at=created_at + timedelta(minutes=updated_offset),
    )


@pytest.mark.parametrize("repository_kind", ["memory", "sqlite"])
def test_repository_crud_and_customer_isolation(
    repository_kind: str,
    tmp_path,
) -> None:
    if repository_kind == "memory":
        repo = InMemoryCustomerGastronomicPreferenceRepository()
    else:
        repo = SQLiteCustomerGastronomicPreferenceRepository(tmp_path / "core.sqlite3")

    first = _preference("pref-1", updated_offset=1)
    second = _preference(
        "pref-2",
        kind="disliked_dish",
        value="Leber",
        source="office_recorded",
        updated_offset=2,
    )
    other_customer = _preference(
        "pref-3",
        customer_id="customer-2",
        kind="service_style",
        value="Buffet",
        updated_offset=3,
    )

    repo.add(first)
    repo.add(second)
    repo.add(other_customer)

    assert repo.get_by_id("pref-1") == first
    assert repo.list_by_customer("customer-1") == [second, first]
    assert repo.list_by_customer("customer-2") == [other_customer]

    updated = CustomerGastronomicPreference(
        **{
            **second.__dict__,
            "value": "Innereien",
            "updated_at": second.updated_at + timedelta(minutes=1),
        }
    )
    repo.update(updated)
    assert repo.get_by_id("pref-2") == updated

    repo.delete("pref-1")
    assert repo.get_by_id("pref-1") is None

    if hasattr(repo, "close"):
        repo.close()


@pytest.mark.parametrize("repository_kind", ["memory", "sqlite"])
def test_repository_rejects_duplicate_and_missing_ids(repository_kind: str, tmp_path) -> None:
    if repository_kind == "memory":
        repo = InMemoryCustomerGastronomicPreferenceRepository()
    else:
        repo = SQLiteCustomerGastronomicPreferenceRepository(tmp_path / "core.sqlite3")

    preference = _preference("pref-1")
    repo.add(preference)
    with pytest.raises(KeyError):
        repo.add(preference)
    with pytest.raises(KeyError):
        repo.update(_preference("missing"))
    with pytest.raises(KeyError):
        repo.delete("missing")

    if hasattr(repo, "close"):
        repo.close()


def test_sqlite_migration_is_recorded_once(tmp_path) -> None:
    db_path = tmp_path / "core.sqlite3"
    first = SQLiteCustomerGastronomicPreferenceRepository(db_path)
    first.close()
    second = SQLiteCustomerGastronomicPreferenceRepository(db_path)
    rows = second._conn.execute(
        """
        SELECT version, name
        FROM schema_migrations
        WHERE component = 'customer_gastronomic_preferences'
        ORDER BY version
        """
    ).fetchall()
    assert rows == [(1, "create_customer_gastronomic_preferences")]
    second.close()
