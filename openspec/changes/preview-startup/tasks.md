# Isolated preview startup
- [ ] Provide one-command isolated Compose preview with persistent data and no public DB/storage ports.
- [ ] Provide up/status/logs/down; never remove data volumes automatically.
- [ ] Run syntax/config checks and live health/API proxy verification.
- [ ] Publish with the frontend Draft PR; keep ML workbench in its independent ML Draft.
- [ ] Fix fresh database prerequisite: base tables must exist before API additive schema bootstrap; initialization must be non-destructive/idempotent.
