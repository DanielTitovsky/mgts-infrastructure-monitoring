# Dokploy preview

Source: GitHub `DanielTitovsky/mgts-infrastructure-monitoring`, branch
`feat/primevue-sakai-ui`, compose path `compose.dokploy.yml`.

One configuration chain: local service defaults in `compose.preview.yml`,
hosted overrides in `compose.dokploy.yml`. Backend-owned Alembic migrations
complete before API startup. Demo seeding is explicit, not part of migrations.
Frontend defaults remain editable in `frontend/config.ts`; environment overrides
are for deployment-specific values.

Build and run the preview on `2.56.97.211`; publish gateway HTTPS on 18443.
Route public HTTPS through Dokploy-managed production Traefik with a dedicated
file-provider route, pinned gateway root CA and matching SNI; never disable TLS verification. Database, object storage and API
have no published host ports (only the authenticated TLS gateway does). Gateway HTTP Basic authentication protects every
route; backend JWT authorization is also enabled. Browser requests carry a
backend JWT in `X-MGTS-Authorization` for this hosted deployment; after Basic
authentication, Caddy maps that value to the backend's standard `Authorization`
header and removes the transport header. The frontend defaults to
`Authorization` elsewhere, and SSR continues to send `Authorization` directly
to the internal API. This preserves Basic protection on every gateway path
without a public API bypass or enabling default admin seeding. Populate the
required `MGTS_*` variables from the canonical secret store; never commit
their values.

Current operator identity: project `rghjtik2yNArKL1FfDyCX`, environment
`Em_m45h4dBvE_x57nvVrC`, compose `cYpwjyQRKQhuu5i5U53F_`.
No successful hosted deployment is claimed yet. The exposed Dokploy Compose
schema supports a runtime server at creation but no separate build-server
selection; ignored update keys are not placement proof. Live API readback verifies
`serverId=tmFr-4nexNmvrBWB0ng4g`, resolving to `2.56.97.211`. Builds on this
host are intended and authorized; the build restriction applies to production
`159.195.51.237`, not this host. Private Git clone access remains to be verified
by the deployment.

Stop/rollback through Dokploy; preserve volumes. Never replace another service
or remove data to repair a preview.

The initial empty null-server candidate `X8-i_K7MTW-1i7W9gZ7tZ` was never
deployed; it is not the active runtime target. Native Compose server placement
is creation-only. The supported current target explicitly selects
`tmFr-4nexNmvrBWB0ng4g` and builds there, not on the production edge.
