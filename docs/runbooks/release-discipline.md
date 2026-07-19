# Release discipline

Verified **2026-07-19** against `cf2edb568d2577f3d0cc06c534a295b861138e76`.

## Current GitHub state (proven vs owner-verified)

| Control | Status |
|---|---|
| CI workflow | `.github/workflows/ci.yml` — runs on push and pull_request |
| Job name (required target) | **`quality`** |
| `quality` on last verified application commit (`cf2edb5`) | **success** (run 29706686826) |
| Direct push to `main` by deployment user | **possible** (observed) |
| Required green `quality` before push | **not enforced** on observed pushes |
| Branch protection exact configuration | **not proven** here — may be absent or bypass may apply; requires authenticated owner/admin verification |
| Force push | **must be prohibited** (policy); server enforcement not verified without owner/admin access |

**Do not claim branch protection is enabled or disabled until authenticated
owner/admin verification of GitHub settings.**

## What `quality` runs

- `ruff check src tests`
- `ruff format --check src tests`
- `mypy src/catering_system`
- `coverage run -m pytest -q` + `coverage report`
- Node tests for staging form and Cloudflare worker

## Local pre-push gate (documented; not a server substitute)

```bash
cd /home/viktor/projects/silberloeffel-catering
source .venv/bin/activate
coverage erase && coverage run -m pytest -q && coverage report
ruff check src tests && ruff format --check src tests
mypy src/catering_system
git diff --check
```

Run on the commit you intend to push. Green local gates do not replace GitHub
`quality` on the remote.

## Target branch protection (owner action)

GitHub **Settings → Branches → Branch protection rules** for `main`:

1. Require a pull request before merging (recommended), or equivalent ruleset.
2. **Require status checks to pass** — select check name **`quality`**.
3. Require branches to be up to date before merging (recommended).
4. Do not allow bypassing the above settings.
5. **Block force pushes**.
6. Optionally restrict who can push to matching branches.

## Preferred flow

1. Branch from `main`.
2. Open PR → wait for green **`quality`**.
3. Merge to `main`.
4. Deploy using deployment truth checklist.
5. Update `docs/current-status.md` in a follow-up commit if deploy timing differs from merge.

Direct push to `main` has been possible for the deployment user; prefer PR + required green **`quality`** when practical.
