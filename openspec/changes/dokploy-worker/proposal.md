## Why

The hosted stack currently has persisted photo jobs but no resident Dokploy worker, so existing `awaiting_processing` rows never finish. Re-enable processing in the same authenticated stack without restarting the API, seeding demo records, changing credentials, or rewriting unrelated database rows.

## What Changes

- Add a CPU worker to the Dokploy Compose stack with the existing database schema, MinIO credentials, shared uploads volume, a read-only mount of the exact tracked `2-version.pt` checkpoint, and the existing Compose default network.
- Add a single-object authenticated reprocess API that queues only the requested object when it has a supported photo and is not already processing.
- Treat the generic `odn_pole` class as pole-object localization only; it must never become a cabinet defect or a claim that condition was assessed.
- Document the worker's checkpoint and cabinet-diagnosis limitations.

## Capabilities

### New Capabilities
- `photo-processing`: Run the existing persisted photo queue in Dokploy and safely requeue one specified object through the authenticated API.

### Modified Capabilities

## Impact

`compose.dokploy.yml`, FastAPI infrastructure-object API/service, CV class mapping, backend tests, and the Dokploy operation guide. No new runtime dependency, public service port, database migration, seed, or photo/model-data import is required.
