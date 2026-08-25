from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    count = text.count(old)
    assert count == 1, (path, count, old[:120])
    path.write_text(text.replace(old, new, 1))


def main() -> None:
    validation = Path("src/catering_system/services/offer_snapshot_validation.py")
    replace_once(
        validation,
        '''    OfferChargesDefinition,\n    validate_charge_base_mode,\n)''',
        '''    OfferChargesDefinition,\n    ReturnLogisticsDefinition,\n    validate_charge_base_mode,\n    validate_return_mode,\n)''',
    )
    replace_once(
        validation,
        '_CHARGES_DEFINITION_KEYS = frozenset({"delivery", "dishware", "buffet"})',
        '_CHARGES_DEFINITION_KEYS = frozenset(\n    {"delivery", "dishware", "buffet", "return_logistics"}\n)',
    )
    replace_once(
        validation,
        '_BUFFET_CHARGE_KEYS = frozenset({"base_mode", "pauschale_per_person_cents"})',
        '_BUFFET_CHARGE_KEYS = frozenset({"base_mode", "pauschale_per_person_cents"})\n_RETURN_LOGISTICS_KEYS = frozenset(\n    {"mode", "pickup_window_text", "same_day_fee_cents"}\n)\n_RETURN_PICKUP_FEE_NAME = "Rückholung am Veranstaltungstag"',
    )
    marker = '''def _parse_charges_definition(value: object) -> OfferChargesDefinition | None:\n'''
    insert = '''def _parse_return_logistics(\n    payload: dict[str, object],\n) -> ReturnLogisticsDefinition:\n    _reject_unknown_keys(\n        payload, _RETURN_LOGISTICS_KEYS, "charges_definition.return_logistics"\n    )\n    mode = validate_return_mode(\n        _require_exact_str(\n            payload.get("mode"), "charges_definition.return_logistics.mode"\n        )\n    )\n    pickup_window_raw = payload.get("pickup_window_text")\n    pickup_window_text: str | None\n    if pickup_window_raw is None:\n        pickup_window_text = None\n    else:\n        pickup_window_text = _require_exact_str(\n            pickup_window_raw,\n            "charges_definition.return_logistics.pickup_window_text",\n        )\n        if len(pickup_window_text) > MAX_SHORT_TEXT_LEN:\n            raise ValueError(\n                "charges_definition.return_logistics.pickup_window_text exceeds length limit"\n            )\n        if pickup_window_text != pickup_window_text.strip():\n            raise ValueError(\n                "charges_definition.return_logistics.pickup_window_text must be trimmed"\n            )\n        if not pickup_window_text:\n            raise ValueError(\n                "charges_definition.return_logistics.pickup_window_text is required"\n            )\n    return ReturnLogisticsDefinition(\n        mode=mode,\n        pickup_window_text=pickup_window_text,\n        same_day_fee_cents=_require_cents(\n            payload.get("same_day_fee_cents"),\n            "charges_definition.return_logistics.same_day_fee_cents",\n        ),\n    )\n\n\n'''
    replace_once(validation, marker, insert + marker)
    replace_once(
        validation,
        '''    buffet = _parse_buffet_charge(\n        _require_object(payload.get("buffet"), "charges_definition.buffet")\n    )\n    return OfferChargesDefinition(delivery=delivery, dishware=dishware, buffet=buffet)''',
        '''    buffet = _parse_buffet_charge(\n        _require_object(payload.get("buffet"), "charges_definition.buffet")\n    )\n    return_logistics_raw = payload.get("return_logistics")\n    return_logistics = (\n        ReturnLogisticsDefinition()\n        if return_logistics_raw is None\n        else _parse_return_logistics(\n            _require_object(\n                return_logistics_raw, "charges_definition.return_logistics"\n            )\n        )\n    )\n    return OfferChargesDefinition(\n        delivery=delivery,\n        dishware=dishware,\n        buffet=buffet,\n        return_logistics=return_logistics,\n    )''',
    )
    replace_once(
        validation,
        '''    _validate_delivery_consistency(charges.delivery, variant, label=label)\n    _validate_dishware_consistency(charges.dishware, variant, event, label=label)\n    _validate_buffet_consistency(charges.buffet, variant, event, label=label)''',
        '''    _validate_delivery_consistency(charges.delivery, variant, label=label)\n    _validate_dishware_consistency(charges.dishware, variant, event, label=label)\n    _validate_buffet_consistency(charges.buffet, variant, event, label=label)\n    _validate_return_logistics_consistency(\n        charges.return_logistics, variant, label=label\n    )''',
    )
    marker = '''def _verify_matched_position_vat_arithmetic(\n'''
    insert = '''def _validate_return_logistics_consistency(\n    return_logistics: ReturnLogisticsDefinition,\n    variant: OfferSnapshotVariant,\n    *,\n    label: str,\n) -> None:\n    positions = [\n        position\n        for position in variant.positions\n        if position.kind == "fee" and position.name == _RETURN_PICKUP_FEE_NAME\n    ]\n    if return_logistics.mode == "NEXT_WORKING_DAY":\n        if positions:\n            raise ValueError(\n                f"{label}: return pickup fee is only valid for SAME_DAY"\n            )\n        return\n\n    if len(positions) != 1:\n        raise ValueError(\n            f"{label}: SAME_DAY return requires exactly one return pickup fee position"\n        )\n    position = positions[0]\n    if position.quantity_mode != "total" or position.quantity != "1":\n        raise ValueError(\n            f"{label}: return pickup fee position must use total quantity 1"\n        )\n    if (\n        position.unit_net_cents != return_logistics.same_day_fee_cents\n        or position.net_total_cents != return_logistics.same_day_fee_cents\n    ):\n        raise ValueError(\n            f"{label}: return pickup fee position does not match charges_definition"\n        )\n\n\n'''
    replace_once(validation, marker, insert + marker)

    offer_repo = Path("src/catering_system/repositories/sqlite_offer_repository.py")
    replace_once(
        offer_repo,
        '''    DishwareChargeDefinition,\n    OfferChargesDefinition,\n)''',
        '''    DishwareChargeDefinition,\n    OfferChargesDefinition,\n    ReturnLogisticsDefinition,\n)''',
    )
    replace_once(
        offer_repo,
        '''            "buffet": {\n                "base_mode": value.buffet.base_mode,\n                "pauschale_per_person_cents": value.buffet.pauschale_per_person_cents,\n            },\n        },''',
        '''            "buffet": {\n                "base_mode": value.buffet.base_mode,\n                "pauschale_per_person_cents": value.buffet.pauschale_per_person_cents,\n            },\n            "return_logistics": {\n                "mode": value.return_logistics.mode,\n                "pickup_window_text": value.return_logistics.pickup_window_text,\n                "same_day_fee_cents": value.return_logistics.same_day_fee_cents,\n            },\n        },''',
    )
    replace_once(
        offer_repo,
        '''        buffet_raw = parsed["buffet"]\n        additional_lines = tuple(''',
        '''        buffet_raw = parsed["buffet"]\n        return_logistics_raw = parsed.get("return_logistics")\n        return_logistics = (\n            ReturnLogisticsDefinition()\n            if return_logistics_raw is None\n            else ReturnLogisticsDefinition(\n                mode=return_logistics_raw["mode"],\n                pickup_window_text=return_logistics_raw["pickup_window_text"],\n                same_day_fee_cents=return_logistics_raw["same_day_fee_cents"],\n            )\n        )\n        additional_lines = tuple(''',
    )
    replace_once(
        offer_repo,
        '''            buffet=BuffetChargeDefinition(\n                base_mode=buffet_raw["base_mode"],\n                pauschale_per_person_cents=buffet_raw["pauschale_per_person_cents"],\n            ),\n        )''',
        '''            buffet=BuffetChargeDefinition(\n                base_mode=buffet_raw["base_mode"],\n                pauschale_per_person_cents=buffet_raw["pauschale_per_person_cents"],\n            ),\n            return_logistics=return_logistics,\n        )''',
    )

    commercial = Path("src/catering_system/domain/order_commercial_snapshot.py")
    replace_once(
        commercial,
        '''from catering_system.domain.order_payment_reminder import (''',
        '''from catering_system.domain.offer_charges import ReturnLogisticsDefinition\nfrom catering_system.domain.order_payment_reminder import (''',
    )
    replace_once(
        commercial,
        '''    positions: tuple[OrderCommercialPosition, ...]\n    variant_description: str | None = None''',
        '''    positions: tuple[OrderCommercialPosition, ...]\n    variant_description: str | None = None\n    return_logistics: ReturnLogisticsDefinition | None = None''',
    )
    replace_once(
        commercial,
        '''        created_at=created_at,\n        positions=tuple(map_offer_position(item) for item in variant.positions),''',
        '''        created_at=created_at,\n        positions=tuple(map_offer_position(item) for item in variant.positions),\n        return_logistics=(\n            offer_version.charges_definition.return_logistics\n            if offer_version.charges_definition is not None\n            else None\n        ),''',
    )

    order_repo = Path(
        "src/catering_system/repositories/sqlite_order_commercial_snapshot_repository.py"
    )
    replace_once(
        order_repo,
        '''from catering_system.domain.order_commercial_snapshot import (''',
        '''from catering_system.domain.offer_charges import ReturnLogisticsDefinition\nfrom catering_system.domain.order_commercial_snapshot import (''',
    )
    replace_once(
        order_repo,
        '''_MIGRATIONS = ((1, "create_order_commercial_snapshots", _migration_1_create_tables),)''',
        '''def _migration_2_return_logistics(connection: sqlite3.Connection) -> None:\n    columns = {\n        row[1]\n        for row in connection.execute("PRAGMA table_info(order_commercial_snapshots)")\n    }\n    if "return_logistics_json" not in columns:\n        connection.execute(\n            "ALTER TABLE order_commercial_snapshots "\n            "ADD COLUMN return_logistics_json TEXT"\n        )\n\n\n_MIGRATIONS = (\n    (1, "create_order_commercial_snapshots", _migration_1_create_tables),\n    (2, "order_commercial_snapshot_return_logistics", _migration_2_return_logistics),\n)''',
    )
    marker = '''class SQLiteOrderCommercialSnapshotRepository:\n'''
    insert = '''def _return_logistics_storage(\n    value: ReturnLogisticsDefinition | None,\n) -> str | None:\n    if value is None:\n        return None\n    return json.dumps(\n        {\n            "mode": value.mode,\n            "pickup_window_text": value.pickup_window_text,\n            "same_day_fee_cents": value.same_day_fee_cents,\n        },\n        ensure_ascii=False,\n    )\n\n\ndef _stored_return_logistics(value: str | None) -> ReturnLogisticsDefinition | None:\n    if value is None:\n        return None\n    parsed = json.loads(value)\n    if not isinstance(parsed, dict):\n        raise ValueError("return_logistics_json must decode to an object")\n    try:\n        return ReturnLogisticsDefinition(\n            mode=parsed["mode"],\n            pickup_window_text=parsed["pickup_window_text"],\n            same_day_fee_cents=parsed["same_day_fee_cents"],\n        )\n    except (KeyError, TypeError) as exc:\n        raise ValueError("return_logistics_json missing required field") from exc\n\n\n'''
    replace_once(order_repo, marker, insert + marker)
    replace_once(
        order_repo,
        '''                        payment_customer_visible_text, created_at\n                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
        '''                        payment_customer_visible_text, created_at,\n                        return_logistics_json\n                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
    )
    replace_once(
        order_repo,
        '''                        snapshot.payment_customer_visible_text,\n                        snapshot.created_at.isoformat(),\n                    ),''',
        '''                        snapshot.payment_customer_visible_text,\n                        snapshot.created_at.isoformat(),\n                        _return_logistics_storage(snapshot.return_logistics),\n                    ),''',
    )
    replace_once(
        order_repo,
        '''                   payment_customer_visible_text, created_at\n            FROM order_commercial_snapshots WHERE snapshot_id = ?''',
        '''                   payment_customer_visible_text, created_at,\n                   return_logistics_json\n            FROM order_commercial_snapshots WHERE snapshot_id = ?''',
    )
    replace_once(
        order_repo,
        '''            created_at=datetime.fromisoformat(row[12]),\n            positions=positions,\n        )''',
        '''            created_at=datetime.fromisoformat(row[12]),\n            positions=positions,\n            return_logistics=_stored_return_logistics(row[13]),\n        )''',
    )

    validation_test = Path("tests/unit/test_issue171_return_logistics_contract.py")
    validation_test.write_text('''from __future__ import annotations\n\nfrom typing import cast\n\nimport pytest\n\nfrom catering_system.services.offer_snapshot_validation import validate_offer_snapshot\nfrom tests.unit.test_offer_charges_validation import (\n    _charge_position,\n    _charges_definition,\n    _default_positions,\n    _snapshot,\n)\n\n_RETURN_FEE = 4500\n\n\ndef _return_fee_position() -> dict[str, object]:\n    return _charge_position(\n        position_id="88888888-8888-4888-8888-888888888895",\n        kind="fee",\n        name="Rückholung am Veranstaltungstag",\n        quantity_mode="total",\n        quantity="1",\n        unit_net_cents=_RETURN_FEE,\n        net_total_cents=_RETURN_FEE,\n    )\n\n\ndef _with_return(\n    charges: dict[str, object],\n    *,\n    mode: str,\n    pickup_window_text: str | None,\n    same_day_fee_cents: int = _RETURN_FEE,\n) -> dict[str, object]:\n    charges["return_logistics"] = {\n        "mode": mode,\n        "pickup_window_text": pickup_window_text,\n        "same_day_fee_cents": same_day_fee_cents,\n    }\n    return charges\n\n\ndef test_pre_171_structured_charges_default_to_next_working_day() -> None:\n    snapshot = validate_offer_snapshot(_snapshot())\n    assert snapshot.charges_definition is not None\n    assert snapshot.charges_definition.return_logistics.mode == "NEXT_WORKING_DAY"\n    assert snapshot.charges_definition.return_logistics.pickup_window_text is None\n\n\ndef test_same_day_requires_pickup_window_on_wire() -> None:\n    charges = _with_return(\n        _charges_definition(dishware_lines=[]),\n        mode="SAME_DAY",\n        pickup_window_text=None,\n    )\n    with pytest.raises(ValueError, match="requires pickup_window_text"):\n        validate_offer_snapshot(_snapshot(charges_definition=charges))\n\n\ndef test_same_day_requires_exactly_one_customer_visible_fee_position() -> None:\n    charges = _with_return(\n        _charges_definition(dishware_lines=[]),\n        mode="SAME_DAY",\n        pickup_window_text="22:00-23:00",\n    )\n    with pytest.raises(ValueError, match="exactly one return pickup fee"):\n        validate_offer_snapshot(_snapshot(charges_definition=charges))\n\n\ndef test_same_day_matching_fee_position_is_accepted() -> None:\n    charges = _with_return(\n        _charges_definition(dishware_lines=[]),\n        mode="SAME_DAY",\n        pickup_window_text="22:00-23:00",\n    )\n    positions = _default_positions() + [_return_fee_position()]\n    snapshot = validate_offer_snapshot(\n        _snapshot(positions=positions, charges_definition=charges)\n    )\n    assert snapshot.charges_definition is not None\n    assert snapshot.charges_definition.return_logistics.mode == "SAME_DAY"\n    assert (\n        snapshot.charges_definition.return_logistics.pickup_window_text\n        == "22:00-23:00"\n    )\n\n\ndef test_next_working_day_rejects_same_day_fee_position() -> None:\n    charges = _with_return(\n        _charges_definition(dishware_lines=[]),\n        mode="NEXT_WORKING_DAY",\n        pickup_window_text=None,\n    )\n    with pytest.raises(ValueError, match="only valid for SAME_DAY"):\n        validate_offer_snapshot(\n            _snapshot(\n                positions=_default_positions() + [_return_fee_position()],\n                charges_definition=charges,\n            )\n        )\n\n\ndef test_return_logistics_rejects_unknown_key() -> None:\n    charges = _with_return(\n        _charges_definition(dishware_lines=[]),\n        mode="NEXT_WORKING_DAY",\n        pickup_window_text=None,\n    )\n    cast(dict[str, object], charges["return_logistics"])["driver_id"] = "nope"\n    with pytest.raises(ValueError, match="unknown charges_definition.return_logistics field"):\n        validate_offer_snapshot(_snapshot(charges_definition=charges))\n''')

    codec_test = Path("tests/unit/test_issue171_return_logistics_offer_persistence.py")
    codec_test.write_text('''from __future__ import annotations\n\nimport json\n\nfrom catering_system.domain.offer_charges import (\n    BuffetChargeDefinition,\n    DeliveryChargeDefinition,\n    DishwareChargeDefinition,\n    OfferChargesDefinition,\n    ReturnLogisticsDefinition,\n)\nfrom catering_system.repositories.sqlite_offer_repository import (\n    _charges_definition_storage,\n    _stored_charges_definition,\n)\n\n\ndef _charges(return_logistics: ReturnLogisticsDefinition) -> OfferChargesDefinition:\n    return OfferChargesDefinition(\n        delivery=DeliveryChargeDefinition(amount_cents=3500),\n        dishware=DishwareChargeDefinition(\n            base_mode="NONE", pauschale_per_person_cents=200\n        ),\n        buffet=BuffetChargeDefinition(\n            base_mode="NONE", pauschale_per_person_cents=50\n        ),\n        return_logistics=return_logistics,\n    )\n\n\ndef test_offer_charges_json_roundtrips_same_day_return() -> None:\n    expected = _charges(\n        ReturnLogisticsDefinition(\n            mode="SAME_DAY",\n            pickup_window_text="22:00-23:00",\n            same_day_fee_cents=4500,\n        )\n    )\n    stored = _charges_definition_storage(expected)\n    assert stored is not None\n    assert _stored_charges_definition(stored) == expected\n\n\ndef test_old_offer_charges_json_loads_with_next_working_day_default() -> None:\n    stored = json.dumps(\n        {\n            "delivery": {"amount_cents": 3500},\n            "dishware": {\n                "base_mode": "NONE",\n                "pauschale_per_person_cents": 200,\n                "additional_lines": [],\n            },\n            "buffet": {\n                "base_mode": "NONE",\n                "pauschale_per_person_cents": 50,\n            },\n        }\n    )\n    loaded = _stored_charges_definition(stored)\n    assert loaded is not None\n    assert loaded.return_logistics == ReturnLogisticsDefinition()\n''')

    order_test = Path("tests/unit/test_issue171_return_logistics_order.py")
    order_test.write_text('''from __future__ import annotations\n\nfrom dataclasses import replace\nfrom datetime import timedelta\n\nfrom catering_system.domain.offer_charges import (\n    BuffetChargeDefinition,\n    DeliveryChargeDefinition,\n    DishwareChargeDefinition,\n    OfferChargesDefinition,\n    ReturnLogisticsDefinition,\n)\nfrom catering_system.domain.order_commercial_snapshot import (\n    build_order_commercial_snapshot,\n)\nfrom tests.unit.test_order_commercial_snapshot import (\n    _NOW,\n    _ORDER_ID,\n    _offer,\n    _version,\n)\n\n\ndef test_accepted_offer_carries_structured_return_into_order_snapshot() -> None:\n    return_logistics = ReturnLogisticsDefinition(\n        mode="SAME_DAY",\n        pickup_window_text="22:00-23:00",\n        same_day_fee_cents=4500,\n    )\n    charges = OfferChargesDefinition(\n        delivery=DeliveryChargeDefinition(amount_cents=3500),\n        dishware=DishwareChargeDefinition(\n            base_mode="NONE", pauschale_per_person_cents=200\n        ),\n        buffet=BuffetChargeDefinition(\n            base_mode="NONE", pauschale_per_person_cents=50\n        ),\n        return_logistics=return_logistics,\n    )\n    version = replace(_version(), charges_definition=charges)\n    offer = _offer(version=version)\n    acceptance = offer.acceptance_evidence\n    assert acceptance is not None\n    snapshot = build_order_commercial_snapshot(\n        order_id=_ORDER_ID,\n        offer=offer,\n        offer_version=version,\n        variant=version.variants[0],\n        acceptance=acceptance,\n        created_at=_NOW + timedelta(hours=2),\n    )\n    assert snapshot.return_logistics == return_logistics\n\n\ndef test_legacy_offer_without_structured_charges_keeps_return_fact_absent() -> None:\n    version = _version()\n    offer = _offer(version=version)\n    acceptance = offer.acceptance_evidence\n    assert acceptance is not None\n    snapshot = build_order_commercial_snapshot(\n        order_id=_ORDER_ID,\n        offer=offer,\n        offer_version=version,\n        variant=version.variants[0],\n        acceptance=acceptance,\n        created_at=_NOW + timedelta(hours=2),\n    )\n    assert snapshot.return_logistics is None\n''')

    repo_test = Path("tests/unit/test_order_commercial_snapshot_repository.py")
    replace_once(
        repo_test,
        '''from __future__ import annotations\n\nimport sqlite3''',
        '''from __future__ import annotations\n\nfrom dataclasses import replace\nimport sqlite3''',
    )
    replace_once(
        repo_test,
        '''from catering_system.domain.order_commercial_snapshot import (\n    build_order_commercial_snapshot,\n)''',
        '''from catering_system.domain.offer_charges import ReturnLogisticsDefinition\nfrom catering_system.domain.order_commercial_snapshot import (\n    build_order_commercial_snapshot,\n)''',
    )
    repo_test.write_text(
        repo_test.read_text()
        + '''\n\ndef test_sqlite_roundtrips_structured_return_logistics(tmp_path: Path) -> None:\n    connection = open_core_connection(tmp_path / "core.db")\n    inquiries = SQLiteInquiryRepository.from_connection(connection)\n    orders = SQLiteOrderRepository.from_connection(connection)\n    snapshots = SQLiteOrderCommercialSnapshotRepository.from_connection(connection)\n    inquiry = _inquiry()\n    inquiries.save(inquiry)\n    order, _version = seed_order(orders, inquiry)\n    connection.commit()\n\n    return_logistics = ReturnLogisticsDefinition(\n        mode="SAME_DAY",\n        pickup_window_text="22:00-23:00",\n        same_day_fee_cents=4500,\n    )\n    snapshot = replace(\n        _snapshot(order_id=order.order_id),\n        return_logistics=return_logistics,\n    )\n    snapshots.create(snapshot)\n    connection.commit()\n\n    loaded = snapshots.get_by_order_id(order.order_id)\n    assert loaded is not None\n    assert loaded.return_logistics == return_logistics\n    connection.close()\n'''
    )


if __name__ == "__main__":
    main()
