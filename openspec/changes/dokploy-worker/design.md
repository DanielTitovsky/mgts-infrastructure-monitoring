## Context

See `proposal.md` for motivation and `specs/photo-processing/spec.md` for the observable contract. The Dokploy Compose file currently has `db`, `schema-init`, MinIO, backend, frontend, and an authenticated gateway. The API and local Compose already share the uploads volume; the existing worker polls persisted status rows and uses one YOLO checkpoint. The hosted stack has no worker declaration.

## Goals / Non-Goals

**Goals:** Keep the existing queue implementation resident in Dokploy; let an authenticated caller request a safe one-row retry; use verified checkpoint metadata; preserve current stack connectivity, credentials, and data.

**Non-Goals:** Replace the model, introduce cabinet diagnosis, change the DB schema, add new secrets, seed/reset records, expose ports, rewrite existing detection output, or make local preview require a worker.

## Decisions

- **Hosted-only service declaration.** Add `worker` to `compose.dokploy.yml`, not `compose.preview.yml`; the preview remains explicitly isolated and its current product workflow does not require ML. Use the existing worker Dockerfile, schema initializer, database and MinIO service dependencies. Alternative: add it to every Compose variant, which would broaden scope and change local preview startup.
- **Reuse trusted inputs rather than copy or regenerate them.** Use the existing hosted `MGTS_DB_PASSWORD` and `MGTS_STORAGE_PASSWORD`, the same DB and bucket settings as the API, the shared `uploads` volume, and a read-only bind mount of only `cv/ml/yolo-v/2-version.pt`. Keep the model outside the worker image. Alternative: build model weights into the image, which duplicates a large artifact and makes model rotation less explicit.
- **Keep the worker on the existing application network.** It uses `http://minio:9000`, the same storage key/secret and bucket as the API, and only the Compose default network. It must not use the separate ML dataset-reader proxy, which targets a different bucket and is read-only. Alternative: bridge the worker into the ML stack, which couples unrelated data paths and does not support the worker's existing output/storage contract.
- **Serialize a single-row requeue.** Select the requested row under `FOR UPDATE`, reject active jobs and unsupported/missing photo keys, then change only the four queue-control fields. The worker uses `SKIP LOCKED`, so it cannot claim that row between selection and commit; the next poll claims the awaiting row. Alternative: unconditional SQL status reset could overwrite an active job or race the worker.
- **Preserve previous results until successful replacement.** Do not remove a processed image or existing defects during manual requeue. The worker's existing success path replaces only CV-sourced defects and old processed output; manual-source defects remain. Alternative: clear output immediately, which would lose the last known result if the retry failed.
- **Make class meaning explicit.** Keep the hosted checkpoint pinned to the actual tracked `2-version.pt`; safely parse its serialized metadata and test all 15 names against existing CV rules. Map `odn_pole` separately to support-object localization with `check_required` and no defect. Neither the generic pole model nor `2-version.pt` is a cabinet-specific condition model. Alternative: allow `odn_pole` through the generic unknown-class fallback, which would incorrectly create a defect.

## Risks / Trade-offs

- [Risk] The worker may process objects whose photo is not among its training classes → use the checkpoint's current class rules, keep an unrecognized/review outcome, and make no cabinet-condition claim.
- [Risk] The worker cannot read or write storage if the existing credentials or application network are unavailable → reuse current credential projections, validate the Compose model, and verify MinIO/worker connectivity through the Dokploy operator before runtime claims.
- [Risk] A retry of an already processing object could race a queue claim → row locking and explicit 409 rejection prevent status clobbering; test the emitted PostgreSQL `FOR UPDATE` statement.

## Migration Plan

Validate the Dokploy Compose declaration with dummy required values, then publish the focused candidate for review. At deployment, preserve existing Compose project volumes and canonical credentials; the archive-backed source must include the backend, frontend, and the single mounted checkpoint path. The API introduces no schema migration. Rollback is to remove/disable only the worker service through Dokploy while retaining the database, MinIO, and uploads volumes; do not run a DB reset or seed. Reprocessing requests remain a versioned API capability only after deployment.

## Open Questions

None.
