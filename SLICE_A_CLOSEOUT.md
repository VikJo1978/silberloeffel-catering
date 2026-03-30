# Slice A closeout — evidence vs SLICE_A_EXECUTION_PACK_V1

Execution-facing only. No redesign.

## §8 External Secure Intake Layer

- **Artifact:** `src/catering_system/intake/external_secure_intake_layer.py`
- **Behavior:** `normalize_public_wix_inquiry_payload` (validate/sanitize/minimal normalize); `ExternalSecureIntakeLayerPort` documents the role.
- **Wix path:** `intake/wix_form_adapter.py` applies normalization before `InquiryService.create_inquiry`.
- **Secret rule:** No HubSpot or other private tokens in this module; browser-facing traffic is expected to terminate at a Worker (or equivalent) before Core; this repo does not ship browser HubSpot credentials.

## HubSpot office-facing baseline

- **Artifact:** `src/catering_system/integration/hubspot_office_intake.py`
- **Behavior:** `HubSpotOfficeInquiryPort`, `HubSpotOfficeCredentials.private_app_token_from_env`, `HubSpotOfficeInquiryNoop` (stub until wired).
- **Secret rule:** Token only via `HUBSPOT_PRIVATE_APP_TOKEN` env; never from browser code in this repository.

## §6 Commands / events (minimal)

- **Events:** `src/catering_system/domain/slice_a_events.py` — `InquiryCreated`, `InquiryUpdated`, `CustomerCallVerified`.
- **Service:** `InquiryService` optional `event_sink`; emits on create/update; `CustomerCallVerified` when `call_verification_status` transitions to `verified`.
- **Command:** `InquiryService.verify_customer_by_call` — inquiry-level only (§6.1).

## §10 CRM office-facing boundary

- **Truth:** Inquiry `crm_stage` is office-facing process stage (frozen pipeline in `domain/inquiry.py`), not kitchen operational truth. Documented here and enforced by domain validators; no Order/OrderVersion in Slice A code.

## §11 / §15 / §17 Acceptance mapping (workspace)

| Criterion | Evidence |
| --- | --- |
| Four channels | A2 adapters + `InquiryService` sources |
| Same inquiry model | Single `create_inquiry` / `update_inquiry` |
| Frozen CRM axis | `crm_stage` + `validate_crm_stage` |
| Source preserved | `inquiry_source` on `Inquiry` |
| Customer linkage | `customer_linkage` + validation |
| No browser→HubSpot secret | No browser bundle; HubSpot token env-only in `hubspot_office_intake.py` |
| CRM not operational kitchen truth | §10 above; no order activation in repo |
| No hidden order/version | Confirmed by absence of Order types in `src/` |
| Controlled intake | Adapters + §8 normalization on wix |
| External secret boundary | §8 module + HubSpot env contract |
| Later slices untouched | No Slice B code |

Formal human sign-off remains outside this file if required by process.
