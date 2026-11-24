Provide a reproducible isolated local preview for the frontend candidate and real backend, PostgreSQL and MinIO. Use a separate Compose project; do not touch existing production services. Loopback-only browser access; users can tunnel the printed URL. Worker/training is not required for the initial UI/data-preparation preview and must not be falsely claimed running. Preserve volumes on stop. No hardcoded production credentials or Git-tracked generated secrets. This is not a production deployment.

## Backend-owned versioned migrations (current correction)
All schema definitions belong to backend/migrations with Alembic revision tracking. Remove root migrations.sql, backend/sql/schema.sql and startup bootstrap DDL only after parity/data-preservation tests. Compose runs a one-shot migration using the backend image before API/worker; neither API nor worker nor seed applies DDL. Existing legacy databases must be upgraded without deleting records, and fresh databases must produce equivalent columns, defaults, indexes and required system status. Demo seeding is an explicit separate command. Retain the current preview URL and data. Downgrade must fail safely if not supported; never silently drop user data.

Hosted preview correction: build and run this non-production candidate on the
current 2.56.97.211 server through Dokploy Compose. Existing production edge
terminates public HTTPS and forwards to the dedicated authenticated gateway over
TLS with pinned CA and SNI. Do not install conflicting ingress on the current
host or modify unrelated Caddy services. All passwords stay canonical; hostname
and environment-specific overrides remain declarative. A created resource is
not deployment proof.
