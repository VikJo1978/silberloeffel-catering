# Kitchen print completion verification

The adapter submits to **local CUPS at localhost:631** and queries the returned
numeric job ID on that same server. A `CUPS_SERVER` environment variable or user
client.conf no longer redirects submission to a different server.

Deploy `cups-client` and `cups-ipp-utils` (Debian/Ubuntu packages), including `lp`
and `ipptool`, and copy the entire `infra/kitchen_print_agent` directory. The
packaged `get-job-state.test` is required. The service user must be allowed to
submit to the configured queue and read its job attributes over local TCP CUPS.
Keep job history long enough for polling (normally CUPS `PreserveJobHistory Yes`).

The agent acknowledges only the matching job with IPP `job-state=9` and an
unambiguous `job-completed-successfully` reason. Canceled (7), aborted (8),
unknown/missing state, warnings/errors, and `queued-in-device` never produce
an ACK. A missing utility or inaccessible server also fails closed. Submission,
status commands and polling share the existing ACK deadline; the adapter does
not resubmit while waiting. This follows RFC 8011 sections 5.3.7–5.3.8:
https://www.rfc-editor.org/rfc/rfc8011.html#section-5.3.7

Before rollout, run a controlled print using the service account and query its
job URI with `ipptool -X ipp://localhost:631/jobs/JOB_ID
/opt/kitchen-print-agent/infra/kitchen_print_agent/get-job-state.test` (one shell
command). Confirm success attributes and the paper output. Repeat with a held
then canceled job; Core must keep `kitchen_print_confirmed_at` empty. Confirm
missing/offline CUPS produces a rejection within the claim deadline.

CUPS success is a spooler observation. Physical paper output still depends on
the deployed printer/backend reporting correctly; verify this with the actual
Brother queue before production rollout. No live printer was used in unit tests.
