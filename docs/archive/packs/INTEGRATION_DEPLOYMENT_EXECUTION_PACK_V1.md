INTEGRATION_DEPLOYMENT_EXECUTION_PACK_V1

0. Purpose

Execution pack for the outward-facing integration layer: real HubSpot HTTP
client behind the existing office-facing port, the Cloudflare Worker fulfilling
the External Secure Intake Layer role (Slice A pack §8), and deployment notes
for the kitchen Lenovo. Evidence rule as in OPERATIONAL_CORE_EXECUTION_PACK_V1 §2.

1. Scope

In scope (code in this repository):
	•	HubSpotOfficeInquiryHttp implementing the existing HubSpotOfficeInquiryPort
		— stdlib urllib only, token strictly from HUBSPOT_PRIVATE_APP_TOKEN env
		(never a parameter that could be fed from browser input), injectable
		transport so tests never touch the network
	•	explicit inquiry→properties mapping in one function; CRM pipeline-stage
		mapping stays configuration-side, not invented here (frozen crm_stage set
		is office-facing truth; HubSpot mirrors it as plain text in MVP)
	•	missing token → loud ValueError, never a silent no-op (the Noop stub stays
		available where a no-op is wanted explicitly)
	•	infra/cloudflare_worker/worker.js — §8 role: accept the public Wix form
		POST, validate/sanitize/minimally normalize, forward to a configured
		upstream with a server-side secret; browser never sees any token
	•	DEPLOYMENT.md — manual steps for: HubSpot token, Worker deploy (wrangler),
		kiosk service on the kitchen Lenovo

Out of scope (must-fail if folded in):
	•	actually performing the external deploys (needs the user's HubSpot account,
		Cloudflare account, and physical Lenovo — manual steps, not repo code)
	•	two-way HubSpot sync, webhooks, contact dedup — office-facing push only
	•	any change to Core truth semantics; this layer is transport only
	•	secrets in code, tests, or browser-served content

2. Acceptance

	•	HTTP client sends the documented request (URL, auth header, JSON body)
		against an injected transport in tests; live network never touched by tests
	•	missing env token raises before any request is built
	•	worker validates and strips input, rejects non-POST and oversized/invalid
		payloads, and never echoes its secret
	•	existing suites remain green

3. Exit

Complete when client + mapping tests pass, worker and deployment notes exist,
and a WORKLOG entry records it. External deploys remain manual user steps.
