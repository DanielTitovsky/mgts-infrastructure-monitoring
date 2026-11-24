# Isolated preview startup
- [x] Provide one-command isolated Compose preview with persistent data and no public DB/storage ports.
- [x] Provide up/status/logs/down; never remove data volumes automatically.
- [x] Run syntax/config checks and live health/API proxy verification.
- [x] Publish with the frontend Draft PR; keep ML workbench in its independent ML Draft.
- [x] Fix fresh database prerequisite: base tables must exist before API additive schema bootstrap; initialization must be non-destructive/idempotent.
- [x] Seed existing idempotent demo records; verify login API and populated table API.
- [ ] Complete browser DOM click smoke: both installed Chrome and headless shell crashed before interaction; HTTP checks do not establish click behavior.

Evidence: Compose health ready; laptop forwarded /admin HTTP 200 at http://127.0.0.1:13300/admin; login API 200; six admin routes 200; objects API returns five synthetic records. Draft PR #1 published; production Nitro build remains incomplete. ML Draft #2 is independent.
