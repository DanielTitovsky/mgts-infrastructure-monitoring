## 1. Safe single-object reprocessing

- [x] 1.1 Add service/API tests for authorization, one-object requeue, missing/unsupported photo, missing object, and active-job rejection; verify they fail before implementation.
- [x] 1.2 Implement the locked single-row requeue endpoint without changing existing results or unrelated objects; verify the focused API/service tests pass.
- [x] 1.3 Add a regression test proving `odn_pole` is support localization only with `check_required` and no defect; verify its focused CV test passes.

## 2. Dokploy worker wiring and evidence

- [x] 2.1 Add the worker to Dokploy Compose on the existing application default network without published worker/database/storage ports or seed commands; verify `docker compose config` contains the service, shared volume, and read-only exact checkpoint mount using dummy required variables.
- [x] 2.2 Add a safe checkpoint metadata regression test and document the old checkpoint's cabinet limits; verify checkpoint class metadata and backend tests.
- [ ] 2.3 Run focused backend tests and OpenSpec validation, inspect the exact diff, and prepare the change's Draft PR; record that runtime processing remains unverified until the coordinator deploys it.

Verification: `uv run --with-requirements requirements.txt --with httpx -- python -m unittest discover -s tests -v` passed 18 tests. Dummy-variable `docker compose -f compose.dokploy.yml config --format json` confirms the worker uses the default network, `http://minio:9000`, no published ports, the existing `uploads` volume, and a read-only exact checkpoint mount. `openspec validate dokploy-worker --strict` passed. No Dokploy deployment or production object processing is claimed here.
- [ ] Enable the pinned cabinet detector in the hosted resident worker, verify a real queue item, processing status, and non-empty annotated output. Keep the original YOLO branch for existing assets.
