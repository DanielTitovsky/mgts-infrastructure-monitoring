# Isolated preview startup
- [x] Provide one-command isolated Compose preview with persistent data and no public DB/storage ports.
- [x] Provide up/status/logs/down; never remove data volumes automatically.
- [x] Run syntax/config checks and live health/API proxy verification.
- [x] Publish with the frontend Draft PR; keep ML workbench in its independent ML Draft.
- [x] Fix fresh database prerequisite: base tables must exist before API additive schema bootstrap; initialization must be non-destructive/idempotent.
- [x] Seed existing idempotent demo records; verify login API and populated table API.
- [ ] Complete browser DOM click smoke: both installed Chrome and headless shell crashed before interaction; HTTP checks do not establish click behavior.

Evidence: Compose health ready; laptop forwarded /admin HTTP 200 at http://127.0.0.1:13300/admin; login API 200; six admin routes 200; objects API returns five synthetic records. Draft PR #1 published; production Nitro build remains incomplete. ML Draft #2 is independent.
- [x] Historical intermediate correction: remove duplicate scripts/preview-schema.sql; use root migrations.sql (superseded by backend Alembic) with non-destructive repeatable initialization. Verify fresh schema and repeated application preserves existing records.

Historical intermediate correction (superseded by backend Alembic below): migrations.sql creates missing base tables without DROP; isolated PostgreSQL transaction proved fresh creation and repeat application preserves a sentinel record. Duplicate SQL removed.
- [x] Backend Alembic revisions and legacy/fresh parity tests; remove startup DDL and obsolete SQL owners.
- [x] Compose one-shot migration ordering for API/worker; update both launchers to explicit seed.
- [ ] Verify fresh, existing and repeat migration data preservation and migration failure gates.
- [ ] Publish correction, verify PR identity/head and restart existing preview without deleting data.
- [ ] Deploy separate MGTS preview through Dokploy from canonical PR branch; provision external HTTPS route and protect access; verify outside localhost. Do not replace unrelated services.

Alembic verification: 6 semantic/source tests; offline DDL emission; live PostgreSQL fresh + legacy-base + repeated upgrade passed, sentinel user preserved. Old SQL parity proven against commit 05a644f before removal. Current populated preview migration/restart and external hosted routing still pending.
