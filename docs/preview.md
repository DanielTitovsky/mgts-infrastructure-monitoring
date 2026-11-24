# Preview: one command

Requires Docker Engine + Compose v2+ (no local Node/Python installation needed).

```sh
./scripts/preview.sh up
./scripts/preview.sh status
./scripts/preview.sh logs
./scripts/preview.sh down
```

Open http://127.0.0.1:3300/. On a remote server forward port 3300 with SSH
(`ssh -L 3300:127.0.0.1:3300 user@server`). Only the frontend is exposed,
on loopback. Containers listen internally on all interfaces. Do not publicly
publish this unauthenticated development stack or use its fixed demo credentials
in production. PostgreSQL, MinIO, API and frontend are isolated under Compose
project `mgts-preview`; existing production containers are not changed.

`up` rebuilds the candidate and waits for health checks. `down` preserves database,
photos and uploads; it never removes volumes. For another isolated instance use
both `MGTS_PREVIEW_PROJECT=mgts-preview-2` and `MGTS_PREVIEW_PORT=3301` consistently.
Readiness means HTTP services are running, not trained-model quality.

The preview uses the real API, not mock data. The existing idempotent seed populates synthetic demo records; login: `admin` / `admin123` (preview only). These are not ML evaluation results. YOLO
worker is deliberately not started: model provisioning and ML workbench are
separate workflows in the ML Draft PR (`cv/data_pipeline/README.md`). Uploaded
objects will not receive automatic inference until a worker is configured.
No dataset download or training happens during startup.

## Verified candidate preview

The current server preview is forwarded to the laptop at
http://127.0.0.1:13300/admin (dedicated `mgts-frontend-tunnel` session).
Login API, six admin routes and five seeded objects returned successful HTTP
responses. Browser automation crashed before interactions, so click-through
verification remains pending. The production Nitro build is not verified;
this preview uses the existing Nuxt development Docker entrypoint.
