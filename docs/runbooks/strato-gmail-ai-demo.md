# STRATO Gmail -> KI Telefonassistent demo rollout

This runbook wires the already-authorized Gmail account to the Lenovo Core database for the Saturday demo.

## 1. Prepare the dedicated worker venv on Lenovo

```bash
python3 -m venv /home/viktor/catering-runtime/strato-gmail-venv
/home/viktor/catering-runtime/strato-gmail-venv/bin/pip install --upgrade pip
/home/viktor/catering-runtime/strato-gmail-venv/bin/pip install \
  google-api-python-client google-auth-httplib2 google-auth-oauthlib openai
```

The worker venv is deliberately separate from the project `.venv`. The Office/Core dependency lock therefore stays unchanged.

## 2. Copy the Gmail OAuth token from the Mac

The OAuth setup was already completed on the Mac and produced `~/strato-gmail/token.json`.

From the Mac:

```bash
scp ~/strato-gmail/token.json viktor@<lenovo-ip>:/tmp/strato-gmail-token.json
```

On Lenovo:

```bash
sudo install -d -m 0755 /etc/catering
sudo install -o viktor -g viktor -m 0600 \
  /tmp/strato-gmail-token.json /etc/catering/strato-gmail-token.json
rm -f /tmp/strato-gmail-token.json
```

Never commit `token.json`. It contains long-lived OAuth material.

## 3. Configure the worker

```bash
sudo cp infra/systemd/catering-strato-gmail-worker.env.example \
  /etc/catering/strato-gmail-worker.env
sudo chown viktor:viktor /etc/catering/strato-gmail-worker.env
sudo chmod 600 /etc/catering/strato-gmail-worker.env
sudoedit /etc/catering/strato-gmail-worker.env
```

Set the real `OPENAI_API_KEY`. Keep these defaults unless the Lenovo paths differ:

```text
STRATO_LLM_MODEL=gpt-5.6-luna
STRATO_GMAIL_TOKEN_PATH=/etc/catering/strato-gmail-token.json
STRATO_GMAIL_DB_PATH=/home/viktor/catering-runtime/core.db
STRATO_GMAIL_POLL_SECONDS=30
```

## 4. One-shot smoke test before enabling the daemon

From the repository root:

```bash
set -a
source /etc/catering/strato-gmail-worker.env
set +a
PYTHONPATH=src /home/viktor/catering-runtime/strato-gmail-venv/bin/python3 \
  scripts/strato_gmail_worker.py \
  --db "$STRATO_GMAIL_DB_PATH" \
  --token "$STRATO_GMAIL_TOKEN_PATH" \
  --model "$STRATO_LLM_MODEL" \
  --once
```

Expected output is either `0 neue STRATO-Gespräche importiert` or one line per newly imported STRATO call followed by the count. Re-running the command must not duplicate existing calls because both STRATO ID and Gmail message ID are unique.

## 5. Install the services from the branch

```bash
sudo cp infra/systemd/catering-office-panel.service /etc/systemd/system/
sudo cp infra/systemd/catering-strato-gmail-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl restart catering-office-panel.service
sudo systemctl enable --now catering-strato-gmail-worker.service
```

Verify:

```bash
systemctl --no-pager --full status catering-office-panel.service
systemctl --no-pager --full status catering-strato-gmail-worker.service
journalctl -u catering-strato-gmail-worker.service -n 50 --no-pager
```

The Office Panel service now starts through `catering_system.ui.office_panel_with_ai`. Existing Office routes remain the normal handler; the wrapper adds only the local `/ki-telefonassistent` routes and sidebar item.

## 6. Demo path

1. Make a fresh test call to the STRATO Smart-Telefonassistent.
2. Wait up to roughly one polling interval for STRATO's Gmail summary plus worker processing.
3. Open `KI Telefonassistent` in the Office Panel. The badge should increase for a new call.
4. Open the call and inspect the original summary plus extracted facts.
5. For a complete catering request, press `Als Anfrage übernehmen`. The system creates the existing Core `Inquiry` with the recognized facts and opens it.
6. For a consultation/change request, use `Als Aufgabe übernehmen` or leave it in the inbox for review.
7. `Erledigt` closes a call without creating a business object.

## Failure behavior

If Gmail, OpenAI, JSON validation or SQLite write fails, the worker logs the error and does not mark the mail as imported. The same message is retried on the next polling cycle. The LLM never writes directly to Inquiry/Offer/Order; its output is validated before it can become an `AiTelefonCall` fact.

## After the demo

The demo worker writes the AI call inbox to the same local Core SQLite database because the Lenovo Office Panel currently runs in direct mode. The production follow-up should expose explicit AI-call read/write commands through the frozen Core Office API and then move the Office Panel back to a fully remote Core-owned surface. Do not expose SQLite or the Office Panel publicly.
