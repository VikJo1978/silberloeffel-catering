from __future__ import annotations

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)


def replace_exact_count(text: str, old: str, new: str, count: int, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise RuntimeError(f"{label}: expected {count} anchors, found {actual}")
    return text.replace(old, new)


# --- shared canonical timing invariant ------------------------------------
Path("src/catering_system/domain/logistics_timing.py").write_text(
    '''"""Canonical local time-window primitives for logistics planning.

Legacy display strings are deliberately outside this module.  A machine-usable
window exists only when its structured values were explicitly supplied.
"""

from __future__ import annotations

from datetime import date, time


def validate_optional_local_window(
    starts_at: time | None,
    ends_at: time | None,
    *,
    label: str,
) -> None:
    if (starts_at is None) != (ends_at is None):
        raise ValueError(f"{label} requires both start and end")
    if starts_at is None:
        return
    assert ends_at is not None
    if starts_at.tzinfo is not None or ends_at.tzinfo is not None:
        raise ValueError(f"{label} must use local wall-clock times without tzinfo")
    if starts_at >= ends_at:
        raise ValueError(f"{label} start must be before end")


def validate_optional_service_window(
    service_date: date | None,
    starts_at: time | None,
    ends_at: time | None,
    *,
    label: str,
) -> None:
    present = (service_date is not None, starts_at is not None, ends_at is not None)
    if any(present) and not all(present):
        raise ValueError(f"{label} requires date, start and end together")
    validate_optional_local_window(starts_at, ends_at, label=label)
''',
    encoding="utf-8",
)

# --- OfferSnapshot transport ----------------------------------------------
path = Path("src/catering_system/domain/offer_snapshot.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from datetime import date, datetime\n",
    "from datetime import date, datetime, time\n",
    "snapshot datetime import",
)
text = replace_once(
    text,
    "from catering_system.domain.inquiry import PlanningMode\n",
    "from catering_system.domain.inquiry import PlanningMode\n"
    "from catering_system.domain.logistics_timing import validate_optional_service_window\n",
    "snapshot timing import",
)
old = '''@dataclass(frozen=True)\nclass OfferSnapshotEvent:\n    event_date: date\n    time_window_text: str\n    location_text: str\n    guest_count: int | None\n    planning_mode: PlanningMode\n'''
new = '''@dataclass(frozen=True)\nclass OfferSnapshotEvent:\n    event_date: date\n    time_window_text: str\n    location_text: str\n    guest_count: int | None\n    planning_mode: PlanningMode\n    delivery_date_local: date | None = None\n    delivery_window_start_local: time | None = None\n    delivery_window_end_local: time | None = None\n\n    def __post_init__(self) -> None:\n        validate_optional_service_window(\n            self.delivery_date_local,\n            self.delivery_window_start_local,\n            self.delivery_window_end_local,\n            label="delivery window",\n        )\n'''
text = replace_once(text, old, new, "snapshot event")
path.write_text(text, encoding="utf-8")

# --- return logistics structured SAME_DAY window --------------------------
path = Path("src/catering_system/domain/offer_charges.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from dataclasses import dataclass\nfrom typing import Literal\n",
    "from dataclasses import dataclass\nfrom datetime import time\nfrom typing import Literal\n\n"
    "from catering_system.domain.logistics_timing import validate_optional_local_window\n",
    "charges timing import",
)
text = replace_once(
    text,
    "    same_day_fee_cents: int = 0\n\n    def __post_init__(self) -> None:\n",
    "    same_day_fee_cents: int = 0\n"
    "    pickup_window_start_local: time | None = None\n"
    "    pickup_window_end_local: time | None = None\n\n"
    "    def __post_init__(self) -> None:\n",
    "return timing fields",
)
text = replace_once(
    text,
    '''        if self.mode == "NEXT_WORKING_DAY" and self.pickup_window_text is not None:\n            raise ValueError(\n                "NEXT_WORKING_DAY return must not specify pickup_window_text"\n            )\n''',
    '''        validate_optional_local_window(\n            self.pickup_window_start_local,\n            self.pickup_window_end_local,\n            label="return pickup window",\n        )\n        if self.mode == "NEXT_WORKING_DAY":\n            if self.pickup_window_text is not None:\n                raise ValueError(\n                    "NEXT_WORKING_DAY return must not specify pickup_window_text"\n                )\n            if (\n                self.pickup_window_start_local is not None\n                or self.pickup_window_end_local is not None\n            ):\n                raise ValueError(\n                    "NEXT_WORKING_DAY return must not specify canonical pickup times"\n                )\n''',
    "return timing validation",
)
path.write_text(text, encoding="utf-8")

# --- OfferVersion domain ---------------------------------------------------
path = Path("src/catering_system/domain/offer.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from datetime import date, datetime\n",
    "from datetime import date, datetime, time\n",
    "offer datetime import",
)
text = replace_once(
    text,
    "from catering_system.domain.inquiry import PlanningMode, validate_planning_mode\n",
    "from catering_system.domain.inquiry import PlanningMode, validate_planning_mode\n"
    "from catering_system.domain.logistics_timing import validate_optional_service_window\n",
    "offer timing import",
)
text = replace_once(
    text,
    "    charges_definition: OfferChargesDefinition | None = None\n\n    def __post_init__(self) -> None:\n",
    "    charges_definition: OfferChargesDefinition | None = None\n"
    "    delivery_date_local: date | None = None\n"
    "    delivery_window_start_local: time | None = None\n"
    "    delivery_window_end_local: time | None = None\n\n"
    "    def __post_init__(self) -> None:\n",
    "offer timing fields",
)
text = replace_once(
    text,
    "        validate_payment_method(self.payment_method)\n",
    "        validate_payment_method(self.payment_method)\n"
    "        validate_optional_service_window(\n"
    "            self.delivery_date_local,\n"
    "            self.delivery_window_start_local,\n"
    "            self.delivery_window_end_local,\n"
    "            label=\"delivery window\",\n"
    "        )\n",
    "offer timing validation",
)
path.write_text(text, encoding="utf-8")

# --- OrderVersion domain ---------------------------------------------------
path = Path("src/catering_system/domain/order.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from datetime import date, datetime\n",
    "from datetime import date, datetime, time\n",
    "order datetime import",
)
text = replace_once(
    text,
    "from catering_system.domain.inquiry import PlanningMode\n",
    "from catering_system.domain.inquiry import PlanningMode\n"
    "from catering_system.domain.logistics_timing import validate_optional_service_window\n",
    "order timing import",
)
text = replace_once(
    text,
    "    changed_fields: tuple[str, ...] = ()\n\n\ndef is_order_version_superseded(\n",
    "    changed_fields: tuple[str, ...] = ()\n"
    "    delivery_date_local: date | None = None\n"
    "    delivery_window_start_local: time | None = None\n"
    "    delivery_window_end_local: time | None = None\n\n"
    "    def __post_init__(self) -> None:\n"
    "        validate_optional_service_window(\n"
    "            self.delivery_date_local,\n"
    "            self.delivery_window_start_local,\n"
    "            self.delivery_window_end_local,\n"
    "            label=\"delivery window\",\n"
    "        )\n\n\n"
    "def is_order_version_superseded(\n",
    "order timing fields",
)
path.write_text(text, encoding="utf-8")

# --- strict snapshot parsing ----------------------------------------------
path = Path("src/catering_system/services/offer_snapshot_validation.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from datetime import date, datetime, timedelta\n",
    "from datetime import date, datetime, time, timedelta\n",
    "validation time import",
)
text = replace_once(
    text,
    '_RETURN_LOGISTICS_KEYS = frozenset({"mode", "pickup_window_text", "same_day_fee_cents"})\n',
    '_RETURN_LOGISTICS_KEYS = frozenset(\n'
    '    {\n'
    '        "mode",\n'
    '        "pickup_window_text",\n'
    '        "same_day_fee_cents",\n'
    '        "pickup_window_start_local",\n'
    '        "pickup_window_end_local",\n'
    '    }\n'
    ')\n',
    "return keys",
)
text = replace_once(
    text,
    '        "planning_mode",\n    }\n)\n_CUSTOMER_TEXT_KEYS',
    '        "planning_mode",\n'
    '        "delivery_date_local",\n'
    '        "delivery_window_start_local",\n'
    '        "delivery_window_end_local",\n'
    '    }\n)\n_CUSTOMER_TEXT_KEYS',
    "event keys",
)
helper_anchor = '''def _require_date(value: object, field: str) -> date:\n    if not isinstance(value, str):\n        raise ValueError(f"{field} must be an ISO date")\n    try:\n        return date.fromisoformat(value)\n    except ValueError as exc:\n        raise ValueError(f"{field} must be an ISO date") from exc\n\n\n'''
helper_replacement = helper_anchor + '''def _optional_date(value: object, field: str) -> date | None:\n    if value is None:\n        return None\n    return _require_date(value, field)\n\n\ndef _optional_local_time(value: object, field: str) -> time | None:\n    if value is None:\n        return None\n    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":\n        raise ValueError(f"{field} must be HH:MM or null")\n    try:\n        parsed = time.fromisoformat(value)\n    except ValueError as exc:\n        raise ValueError(f"{field} must be HH:MM or null") from exc\n    if parsed.isoformat(timespec="minutes") != value:\n        raise ValueError(f"{field} must be canonical HH:MM or null")\n    return parsed\n\n\n'''
text = replace_once(text, helper_anchor, helper_replacement, "optional timing helpers")
text = replace_once(
    text,
    '''        planning_mode=validate_planning_mode(\n            _require_exact_str(payload.get("planning_mode"), "planning_mode")\n        ),\n    )\n''',
    '''        planning_mode=validate_planning_mode(\n            _require_exact_str(payload.get("planning_mode"), "planning_mode")\n        ),\n        delivery_date_local=_optional_date(\n            payload.get("delivery_date_local"), "event.delivery_date_local"\n        ),\n        delivery_window_start_local=_optional_local_time(\n            payload.get("delivery_window_start_local"),\n            "event.delivery_window_start_local",\n        ),\n        delivery_window_end_local=_optional_local_time(\n            payload.get("delivery_window_end_local"),\n            "event.delivery_window_end_local",\n        ),\n    )\n''',
    "parse event timing",
)
text = replace_once(
    text,
    '''        same_day_fee_cents=_require_cents(\n            payload.get("same_day_fee_cents"),\n            "charges_definition.return_logistics.same_day_fee_cents",\n        ),\n    )\n''',
    '''        same_day_fee_cents=_require_cents(\n            payload.get("same_day_fee_cents"),\n            "charges_definition.return_logistics.same_day_fee_cents",\n        ),\n        pickup_window_start_local=_optional_local_time(\n            payload.get("pickup_window_start_local"),\n            "charges_definition.return_logistics.pickup_window_start_local",\n        ),\n        pickup_window_end_local=_optional_local_time(\n            payload.get("pickup_window_end_local"),\n            "charges_definition.return_logistics.pickup_window_end_local",\n        ),\n    )\n''',
    "parse return timing",
)
path.write_text(text, encoding="utf-8")

# --- OfferService mapping --------------------------------------------------
path = Path("src/catering_system/services/offer_service.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "        charges_definition=snapshot.charges_definition,\n    )\n",
    "        charges_definition=snapshot.charges_definition,\n"
    "        delivery_date_local=snapshot.event.delivery_date_local,\n"
    "        delivery_window_start_local=snapshot.event.delivery_window_start_local,\n"
    "        delivery_window_end_local=snapshot.event.delivery_window_end_local,\n"
    "    )\n",
    "offer service timing mapping",
)
path.write_text(text, encoding="utf-8")

# --- OrderService conversion + timing inheritance -------------------------
path = Path("src/catering_system/services/order_service.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "            planning_mode=offer_version.planning_mode,\n        )\n",
    "            planning_mode=offer_version.planning_mode,\n"
    "            delivery_date_local=offer_version.delivery_date_local,\n"
    "            delivery_window_start_local=offer_version.delivery_window_start_local,\n"
    "            delivery_window_end_local=offer_version.delivery_window_end_local,\n"
    "        )\n",
    "initial order timing mapping",
)
# create_relevant_order_change_version: inherit from latest existing version.
text = replace_once(
    text,
    "        next_num = max((v.version_number for v in existing), default=0) + 1\n",
    "        latest_version = max(existing, key=lambda item: item.version_number) if existing else None\n"
    "        next_num = max((v.version_number for v in existing), default=0) + 1\n",
    "latest version inheritance anchor",
)
text = replace_once(
    text,
    "            planning_mode=pm,\n        )\n        context = _operational_context_for_new_version(\n",
    "            planning_mode=pm,\n"
    "            delivery_date_local=(\n"
    "                latest_version.delivery_date_local if latest_version is not None else None\n"
    "            ),\n"
    "            delivery_window_start_local=(\n"
    "                latest_version.delivery_window_start_local\n"
    "                if latest_version is not None\n"
    "                else None\n"
    "            ),\n"
    "            delivery_window_end_local=(\n"
    "                latest_version.delivery_window_end_local\n"
    "                if latest_version is not None\n"
    "                else None\n"
    "            ),\n"
    "        )\n        context = _operational_context_for_new_version(\n",
    "relevant change timing inheritance",
)
# proposed changes inherit structured timing until a dedicated timing-change command exists.
text = replace_once(
    text,
    "            changed_fields=changed_fields,\n        )\n",
    "            changed_fields=changed_fields,\n"
    "            delivery_date_local=source.delivery_date_local,\n"
    "            delivery_window_start_local=source.delivery_window_start_local,\n"
    "            delivery_window_end_local=source.delivery_window_end_local,\n"
    "        )\n",
    "proposed change timing inheritance",
)
path.write_text(text, encoding="utf-8")

# --- Offer SQLite persistence ---------------------------------------------
path = Path("src/catering_system/repositories/sqlite_offer_repository.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from datetime import date, datetime\n",
    "from datetime import date, datetime, time\n",
    "offer repo time import",
)
migration = '''\n\ndef _migration_10_offer_version_logistics_timing(\n    connection: sqlite3.Connection,\n) -> None:\n    existing = {\n        row[1] for row in connection.execute("PRAGMA table_info(offer_versions)")\n    }\n    for name in (\n        "delivery_date_local",\n        "delivery_window_start_local",\n        "delivery_window_end_local",\n    ):\n        if name not in existing:\n            connection.execute(f"ALTER TABLE offer_versions ADD COLUMN {name} TEXT")\n'''
text = replace_once(
    text,
    "\n\n_MIGRATIONS = (\n",
    migration + "\n\n_MIGRATIONS = (\n",
    "offer migration 10 insertion",
)
text = replace_once(
    text,
    '''    (\n        9,\n        "offer_version_charges_definition",\n        _migration_9_offer_version_charges_definition,\n    ),\n)\n''',
    '''    (\n        9,\n        "offer_version_charges_definition",\n        _migration_9_offer_version_charges_definition,\n    ),\n    (\n        10,\n        "offer_version_logistics_timing",\n        _migration_10_offer_version_logistics_timing,\n    ),\n)\n''',
    "offer migration tuple",
)
text = replace_once(
    text,
    '''                "same_day_fee_cents": value.return_logistics.same_day_fee_cents,\n            },\n''',
    '''                "same_day_fee_cents": value.return_logistics.same_day_fee_cents,\n                "pickup_window_start_local": (\n                    value.return_logistics.pickup_window_start_local.isoformat(\n                        timespec="minutes"\n                    )\n                    if value.return_logistics.pickup_window_start_local is not None\n                    else None\n                ),\n                "pickup_window_end_local": (\n                    value.return_logistics.pickup_window_end_local.isoformat(\n                        timespec="minutes"\n                    )\n                    if value.return_logistics.pickup_window_end_local is not None\n                    else None\n                ),\n            },\n''',
    "stored return timing",
)
text = replace_once(
    text,
    '''                same_day_fee_cents=return_logistics_raw["same_day_fee_cents"],\n            )\n''',
    '''                same_day_fee_cents=return_logistics_raw["same_day_fee_cents"],\n                pickup_window_start_local=(\n                    time.fromisoformat(return_logistics_raw["pickup_window_start_local"])\n                    if return_logistics_raw.get("pickup_window_start_local") is not None\n                    else None\n                ),\n                pickup_window_end_local=(\n                    time.fromisoformat(return_logistics_raw["pickup_window_end_local"])\n                    if return_logistics_raw.get("pickup_window_end_local") is not None\n                    else None\n                ),\n            )\n''',
    "load return timing",
)
text = replace_once(
    text,
    '''                charges_definition_json\n            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n''',
    '''                charges_definition_json, delivery_date_local,\n                delivery_window_start_local, delivery_window_end_local\n            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n''',
    "offer insert columns",
)
text = replace_once(
    text,
    '''                _charges_definition_storage(version.charges_definition),\n            ),\n''',
    '''                _charges_definition_storage(version.charges_definition),\n                (\n                    version.delivery_date_local.isoformat()\n                    if version.delivery_date_local is not None\n                    else None\n                ),\n                (\n                    version.delivery_window_start_local.isoformat(timespec="minutes")\n                    if version.delivery_window_start_local is not None\n                    else None\n                ),\n                (\n                    version.delivery_window_end_local.isoformat(timespec="minutes")\n                    if version.delivery_window_end_local is not None\n                    else None\n                ),\n            ),\n''',
    "offer insert values",
)
text = replace_once(
    text,
    '''                   customer_introduction, customer_notes, budget_definition_json,\n                   charges_definition_json\n            FROM offer_versions\n''',
    '''                   customer_introduction, customer_notes, budget_definition_json,\n                   charges_definition_json, delivery_date_local,\n                   delivery_window_start_local, delivery_window_end_local\n            FROM offer_versions\n''',
    "offer load select",
)
text = replace_once(
    text,
    '''                    charges_definition=_stored_charges_definition(row[17]),\n                )\n''',
    '''                    charges_definition=_stored_charges_definition(row[17]),\n                    delivery_date_local=(\n                        date.fromisoformat(row[18]) if row[18] is not None else None\n                    ),\n                    delivery_window_start_local=(\n                        time.fromisoformat(row[19]) if row[19] is not None else None\n                    ),\n                    delivery_window_end_local=(\n                        time.fromisoformat(row[20]) if row[20] is not None else None\n                    ),\n                )\n''',
    "offer load timing",
)
path.write_text(text, encoding="utf-8")

# --- Order SQLite persistence ---------------------------------------------
path = Path("src/catering_system/repositories/sqlite_order_repository.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from datetime import date, datetime\n",
    "from datetime import date, datetime, time\n",
    "order repo time import",
)
migration = '''\n\ndef _migration_10_order_version_logistics_timing(\n    connection: sqlite3.Connection,\n) -> None:\n    columns = {\n        row[1] for row in connection.execute("PRAGMA table_info(order_versions)")\n    }\n    for name in (\n        "delivery_date_local",\n        "delivery_window_start_local",\n        "delivery_window_end_local",\n    ):\n        if name not in columns:\n            connection.execute(f"ALTER TABLE order_versions ADD COLUMN {name} TEXT")\n    connection.execute(\n        """CREATE TRIGGER IF NOT EXISTS trg_order_version_logistics_timing_immutable\n        BEFORE UPDATE OF delivery_date_local, delivery_window_start_local,\n                         delivery_window_end_local ON order_versions\n        WHEN NEW.delivery_date_local IS NOT OLD.delivery_date_local\n          OR NEW.delivery_window_start_local IS NOT OLD.delivery_window_start_local\n          OR NEW.delivery_window_end_local IS NOT OLD.delivery_window_end_local\n        BEGIN SELECT RAISE(ABORT, 'order version logistics timing is immutable'); END"""\n    )\n'''
text = replace_once(
    text,
    "\n\n_MIGRATIONS = (\n",
    migration + "\n\n_MIGRATIONS = (\n",
    "order migration 10 insertion",
)
text = replace_once(
    text,
    '''    (\n        9,\n        "operational_context_fulfillment_mode",\n        _migration_9_operational_context_fulfillment_mode,\n    ),\n)\n''',
    '''    (\n        9,\n        "operational_context_fulfillment_mode",\n        _migration_9_operational_context_fulfillment_mode,\n    ),\n    (\n        10,\n        "order_version_logistics_timing",\n        _migration_10_order_version_logistics_timing,\n    ),\n)\n''',
    "order migration tuple",
)
old_insert = '''            self._conn.execute(\n                "INSERT INTO order_versions VALUES "\n                "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",\n                self._version_values(version),\n            )\n'''
new_insert = '''            self._conn.execute(\n                """\n                INSERT INTO order_versions (\n                    order_version_id, order_id, version_number, created_at,\n                    event_date, time_window_text, location_text, guest_count_estimate,\n                    planning_mode, kitchen_print_confirmed_at, parent_order_version_id,\n                    created_by, change_reason, changed_fields_json, delivery_date_local,\n                    delivery_window_start_local, delivery_window_end_local\n                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)\n                """,\n                self._version_values(version),\n            )\n'''
text = replace_exact_count(text, old_insert, new_insert, 2, "order inserts")
text = replace_once(
    text,
    '''            json.dumps(version.changed_fields, separators=(",", ":")),\n        )\n''',
    '''            json.dumps(version.changed_fields, separators=(",", ":")),\n            (\n                version.delivery_date_local.isoformat()\n                if version.delivery_date_local is not None\n                else None\n            ),\n            (\n                version.delivery_window_start_local.isoformat(timespec="minutes")\n                if version.delivery_window_start_local is not None\n                else None\n            ),\n            (\n                version.delivery_window_end_local.isoformat(timespec="minutes")\n                if version.delivery_window_end_local is not None\n                else None\n            ),\n        )\n''',
    "order version values",
)
text = replace_once(
    text,
    '''            changed_fields=tuple(json.loads(row[13])),\n        )\n''',
    '''            changed_fields=tuple(json.loads(row[13])),\n            delivery_date_local=(\n                date.fromisoformat(row[14]) if row[14] is not None else None\n            ),\n            delivery_window_start_local=(\n                time.fromisoformat(row[15]) if row[15] is not None else None\n            ),\n            delivery_window_end_local=(\n                time.fromisoformat(row[16]) if row[16] is not None else None\n            ),\n        )\n''',
    "order row timing",
)
path.write_text(text, encoding="utf-8")

# --- focused tests ---------------------------------------------------------
Path("tests/unit/test_issue175_logistics_timing.py").write_text(
    '''from __future__ import annotations\n\nfrom datetime import UTC, date, datetime, time\nfrom pathlib import Path\n\nimport pytest\n\nfrom catering_system.domain.offer import Offer, OfferPosition, OfferVariant, OfferVersion\nfrom catering_system.domain.offer_charges import (\n    BuffetChargeDefinition,\n    DeliveryChargeDefinition,\n    DishwareChargeDefinition,\n    OfferChargesDefinition,\n    ReturnLogisticsDefinition,\n)\nfrom catering_system.domain.order import Order, OrderVersion\nfrom catering_system.repositories.sqlite_offer_repository import SQLiteOfferRepository\nfrom catering_system.repositories.sqlite_order_repository import SQLiteOrderRepository\n\nNOW = datetime(2026, 8, 25, 9, 0, tzinfo=UTC)\nDAY = date(2026, 9, 12)\n\n\ndef _charges() -> OfferChargesDefinition:\n    return OfferChargesDefinition(\n        delivery=DeliveryChargeDefinition(amount_cents=1000),\n        dishware=DishwareChargeDefinition(\n            base_mode="NONE", pauschale_per_person_cents=0\n        ),\n        buffet=BuffetChargeDefinition(base_mode="NONE", pauschale_per_person_cents=0),\n        return_logistics=ReturnLogisticsDefinition(\n            mode="SAME_DAY",\n            pickup_window_text="22:00–23:00",\n            same_day_fee_cents=2500,\n            pickup_window_start_local=time(22, 0),\n            pickup_window_end_local=time(23, 0),\n        ),\n    )\n\n\ndef _offer_version() -> OfferVersion:\n    position = OfferPosition(\n        position_id="position-1",\n        kind="fee",\n        name="Test",\n        unit_net_cents=1000,\n        net_total_cents=1000,\n        vat_rate_percent=19,\n        vat_amount_cents=190,\n        gross_total_cents=1190,\n    )\n    variant = OfferVariant(\n        variant_id="variant-1",\n        offer_version_id="offer-version-1",\n        label="Test",\n        positions=(position,),\n    )\n    return OfferVersion(\n        offer_version_id="offer-version-1",\n        offer_id="offer-1",\n        version_number=1,\n        created_at=NOW,\n        valid_until=date(2026, 9, 11),\n        snapshot_id="snapshot-1",\n        snapshot_hash="sha256:" + "a" * 64,\n        event_date=DAY,\n        time_window_text="18:00–22:00",\n        location_text="Hamburg",\n        guest_count=20,\n        planning_mode="caterer_suggestion",\n        payment_method="RECHNUNG",\n        payment_customer_visible_text="Rechnung",\n        variants=(variant,),\n        charges_definition=_charges(),\n        delivery_date_local=DAY,\n        delivery_window_start_local=time(16, 0),\n        delivery_window_end_local=time(17, 0),\n    )\n\n\ndef test_offer_sqlite_roundtrip_preserves_canonical_logistics_timing(tmp_path: Path) -> None:\n    repo = SQLiteOfferRepository(tmp_path / "offers.db")\n    version = _offer_version()\n    repo.save(\n        Offer(\n            offer_id="offer-1",\n            source_inquiry_id="inquiry-1",\n            created_at=NOW,\n            versions=(version,),\n        )\n    )\n    loaded = repo.get("offer-1")\n    assert loaded is not None\n    actual = loaded.versions[0]\n    assert actual.delivery_date_local == DAY\n    assert actual.delivery_window_start_local == time(16, 0)\n    assert actual.delivery_window_end_local == time(17, 0)\n    assert actual.charges_definition is not None\n    return_plan = actual.charges_definition.return_logistics\n    assert return_plan.pickup_window_start_local == time(22, 0)\n    assert return_plan.pickup_window_end_local == time(23, 0)\n\n\ndef test_order_sqlite_roundtrip_preserves_canonical_delivery_window(tmp_path: Path) -> None:\n    repo = SQLiteOrderRepository(tmp_path / "orders.db")\n    order = Order("order-1", "inquiry-1", NOW, NOW)\n    version = OrderVersion(\n        order_version_id="order-version-1",\n        order_id="order-1",\n        version_number=1,\n        created_at=NOW,\n        event_date=DAY,\n        time_window_text="18:00–22:00",\n        location_text="Hamburg",\n        guest_count_estimate=20,\n        planning_mode="caterer_suggestion",\n        delivery_date_local=DAY,\n        delivery_window_start_local=time(16, 0),\n        delivery_window_end_local=time(17, 0),\n    )\n    repo.save_order_with_initial_version(order, version)\n    assert repo.get_order_version("order-version-1") == version\n\n\ndef test_structured_delivery_window_is_atomic_and_ordered() -> None:\n    with pytest.raises(ValueError, match="date, start and end together"):\n        OrderVersion(\n            "v", "o", 1, NOW, DAY, "legacy text", "Hamburg", 10,\n            "caterer_suggestion", delivery_date_local=DAY\n        )\n    with pytest.raises(ValueError, match="start must be before end"):\n        OrderVersion(\n            "v", "o", 1, NOW, DAY, "legacy text", "Hamburg", 10,\n            "caterer_suggestion",\n            delivery_date_local=DAY,\n            delivery_window_start_local=time(17, 0),\n            delivery_window_end_local=time(16, 0),\n        )\n\n\ndef test_return_canonical_window_is_optional_but_never_inferred() -> None:\n    legacy = ReturnLogisticsDefinition(\n        mode="SAME_DAY",\n        pickup_window_text="später am Abend",\n        same_day_fee_cents=0,\n    )\n    assert legacy.pickup_window_start_local is None\n    assert legacy.pickup_window_end_local is None\n    with pytest.raises(ValueError, match="both start and end"):\n        ReturnLogisticsDefinition(\n            mode="SAME_DAY",\n            pickup_window_text="22:00–23:00",\n            pickup_window_start_local=time(22, 0),\n        )\n\n\ndef test_next_working_day_never_carries_canonical_pickup_times() -> None:\n    with pytest.raises(ValueError, match="must not specify canonical pickup times"):\n        ReturnLogisticsDefinition(\n            mode="NEXT_WORKING_DAY",\n            pickup_window_start_local=time(9, 0),\n            pickup_window_end_local=time(10, 0),\n        )\n''',
    encoding="utf-8",
)

# Extend existing snapshot-validation tests using their local fixture helpers.
path = Path("tests/unit/test_offer_snapshot_validation.py")
text = path.read_text(encoding="utf-8")
if "test_canonical_delivery_window_passes_without_parsing_legacy_text" in text:
    raise RuntimeError("issue 175 snapshot tests already present")
text += '''\n\ndef test_canonical_delivery_window_passes_without_parsing_legacy_text() -> None:\n    payload = _valid_snapshot()\n    event = cast(dict[str, object], payload["event"])\n    event["delivery_date_local"] = "2026-08-20"\n    event["delivery_window_start_local"] = "16:00"\n    event["delivery_window_end_local"] = "17:30"\n    payload["snapshot_hash"] = compute_snapshot_hash(payload)\n\n    snapshot = validate_offer_snapshot(payload)\n    assert snapshot.event.delivery_date_local.isoformat() == "2026-08-20"\n    assert snapshot.event.delivery_window_start_local.isoformat(timespec="minutes") == "16:00"\n    assert snapshot.event.delivery_window_end_local.isoformat(timespec="minutes") == "17:30"\n    assert snapshot.event.time_window_text == "18:00–22:00"\n\n\ndef test_legacy_event_text_is_not_parsed_into_canonical_delivery_window() -> None:\n    snapshot = validate_offer_snapshot(_valid_snapshot())\n    assert snapshot.event.delivery_date_local is None\n    assert snapshot.event.delivery_window_start_local is None\n    assert snapshot.event.delivery_window_end_local is None\n\n\ndef test_partial_canonical_delivery_window_is_rejected() -> None:\n    payload = _valid_snapshot()\n    event = cast(dict[str, object], payload["event"])\n    event["delivery_date_local"] = "2026-08-20"\n    payload["snapshot_hash"] = compute_snapshot_hash(payload)\n    with pytest.raises(ValueError, match="date, start and end together"):\n        validate_offer_snapshot(payload)\n\n\ndef test_noncanonical_delivery_time_is_rejected() -> None:\n    payload = _valid_snapshot()\n    event = cast(dict[str, object], payload["event"])\n    event["delivery_date_local"] = "2026-08-20"\n    event["delivery_window_start_local"] = "16:00:00"\n    event["delivery_window_end_local"] = "17:00"\n    payload["snapshot_hash"] = compute_snapshot_hash(payload)\n    with pytest.raises(ValueError, match="HH:MM"):\n        validate_offer_snapshot(payload)\n'''
path.write_text(text, encoding="utf-8")
