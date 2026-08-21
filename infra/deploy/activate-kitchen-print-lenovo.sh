#!/bin/sh
# One-shot Lenovo activation for Phase 3B kitchen print (Kitchen API + Agent).
# Run on debiancatering as viktor after `git merge --ff-only origin/main`.
# Requires sudo once for env files, systemd units, and service restart.

set -eu

REPO=/home/viktor/projects/silberloeffel-catering
DB=/home/viktor/catering-runtime/core.db

cd "$REPO"

if [ ! -f "$DB" ]; then
  echo "missing core.db at $DB" >&2
  exit 1
fi

if [ ! -f /etc/catering/kitchen-api.env ]; then
  token=$(openssl rand -hex 32)
  umask 077
  printf 'KITCHEN_API_TOKEN=%s\n' "$token" | sudo tee /etc/catering/kitchen-api.env >/dev/null
  {
    printf 'KITCHEN_PRINT_API_URL=http://127.0.0.1:8086\n'
    printf 'KITCHEN_PRINT_AGENT_TOKEN=%s\n' "$token"
    printf 'KITCHEN_PRINT_POLL_INTERVAL_SECONDS=5\n'
    printf 'KITCHEN_PRINT_PRINTER_NAME=Brother_L2710DN_LAN\n'
  } | sudo tee /etc/kitchen-print-agent.env >/dev/null
  sudo chown root:root /etc/catering/kitchen-api.env /etc/kitchen-print-agent.env
  sudo chmod 600 /etc/catering/kitchen-api.env /etc/kitchen-print-agent.env
  echo "created paired kitchen API/agent tokens"
else
  echo "kitchen env files already exist — leaving tokens unchanged"
fi

sudo install -m 644 "$REPO/infra/systemd/catering-kitchen-api.service" \
  /etc/systemd/system/catering-kitchen-api.service
sudo install -m 644 "$REPO/infra/systemd/kitchen-print-agent.service" \
  /etc/systemd/system/kitchen-print-agent.service
sudo systemctl daemon-reload
sudo systemctl enable catering-kitchen-api kitchen-print-agent
sudo systemctl restart catering-office-panel catering-kitchen-api kitchen-print-agent

sleep 2
systemctl is-active catering-office-panel catering-kitchen-api kitchen-print-agent
ss -ltn | grep -E ':8081|:8086' || true

token=$(sudo awk -F= '/^KITCHEN_API_TOKEN=/{print $2}' /etc/catering/kitchen-api.env)
code=$(curl -s -o /dev/null -w '%{http_code}' \
  -X POST http://127.0.0.1:8086/kitchen/v1/print-jobs/claim-next \
  -H "Authorization: Bearer ${token}" \
  -H 'Content-Type: application/json' \
  -d '{"command_id":"00000000-0000-4000-8000-000000000099"}')
echo "kitchen claim smoke (auth, empty queue): HTTP ${code} (expect 204)"
sqlite3 "$DB" 'PRAGMA quick_check;'
echo 'ACTIVATION_OK'
