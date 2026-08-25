# Kiosk order feed logistics timing V3

Issue: #175

This is an additive planning extension to the existing kiosk order-feed contract.
The frozen V1 selection/read-only contract and the issue #171 V2 return-logistics
extension remain valid.

## Goal

Expose accepted canonical local logistics timing to Courier App without parsing
human display text. These fields are planning facts only. They do not assign a
courier or vehicle and do not create, complete, or mutate `PickupTask` or
checklist execution state.

## Delivery timing

Each order gains an additive `delivery_window` field:

```json
"delivery_window": {
  "date": "2026-10-01",
  "start_local": "18:00",
  "end_local": "19:00"
}
```

If the effective `OrderVersion` has no complete canonical delivery date/start/end,
`delivery_window` is `null`. `time_window_text` remains unchanged and is never
parsed or used to manufacture this object.

The values come only from the effective immutable `OrderVersion` mirrored by the
existing `WochenuebersichtEntry` read model. Order selection remains exclusively
the existing Wochenübersicht/effective-version gate.

## Return timing

For non-null `return_logistics`, V3 adds:

```json
"pickup_window_start_local": "22:00",
"pickup_window_end_local": "23:00"
```

Both values are `null` when no accepted canonical SAME_DAY pickup window exists.
`pickup_window_text` remains display text and is never parsed.

`NEXT_WORKING_DAY` still carries no canonical pickup time. Its deterministic
planned `return_date` continues to use the current Monday-Friday rule from V2;
Core does not invent public-holiday or company-closure knowledge.

## Format and semantics

- dates are ISO `YYYY-MM-DD`;
- local times are canonical `HH:MM` without timezone/UTC conversion;
- start/end are atomic: a complete canonical pair is projected, otherwise the
  canonical window is unknown;
- prices remain outside the kiosk boundary;
- courier, vehicle, assignment, checklist, completion and overdue execution
  state remain Courier App-owned;
- missing canonical timing means downstream logistics capacity must report an
  UNKNOWN/INCOMPLETE signal rather than guess from display text, order count or
  guest count.

## Backward compatibility

Existing consumers may ignore the new fields. V1/V2 producers and legacy
accepted rows remain readable: canonical timing is explicitly absent/null rather
than inferred from `time_window_text` or `pickup_window_text`.
