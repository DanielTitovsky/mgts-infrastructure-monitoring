# Local candidate evidence

- `cd cv/data_pipeline && uv run --extra test python -m pytest tests --cov=mgts_data_pipeline --cov-report=term-missing`: 61 passed; 84.56% focused coverage.
- Root entrypoint: `uv run --project cv/data_pipeline mgts-datasets --help` succeeds.
- Real final command: `uv run --project cv/data_pipeline mgts-datasets normalize --source broken_poles_v2 --output /tmp/mgts-normalized-final-broken-poles`; subsequent `validate` reports valid=true, 533 images, 745 annotations. 71 image records rejected whole, including 115 annotations; original files unchanged. Output remains train-only.
- Worker verified fresh-directory Broken Poles ZIP + manifest fetch, checksum mismatch rejection and token-free cache reuse; larger ZIP fresh fetch covered by tests, not repeated live download.
- Six adapters exercised by fixtures and real numeric inventories. This is not a claim that all six complete datasets normalize cleanly: Powerline quarantine opt-in reaches conflicting duplicate annotations and fails closed. No visual labeling audit or model training performed.
- Explicit relative YAML `path: .` removed: consumers should pass absolute YAML path to resolve images relative to that YAML, not a global Ultralytics datasets root. Regression test failed before fix, passes afterward.
- At the initial normalization checkpoint, no push or PR was requested/performed. A later explicit authorization allows a WIP PR, whose publication is coordinator-owned; this worktree was not pushed by the implementation agent. No protected-branch change or normalized-data upload was performed.

- Real PD-Defect run exposed float serialization regression: 10 significant digits moved boundary boxes fractionally outside image bounds. Minimal failing fixture reproduced it; switched to round-trip float representation without clipping, regression test now passes. Real rerun and standalone validate succeeded: 1,801 images, 2,182 annotations, valid=true at /tmp/mgts-normalized-final-pd.

## Marimo workbench evidence

- `bash -n cv/data_pipeline/workbench.sh` passed; focused workbench tests: 13 passed. Full pipeline suite: 74 passed, 84.86% coverage (80% threshold met). `uv lock --project cv/data_pipeline --check`, `marimo check --strict`, and `marimo export html` passed; the final exported HTML is `/tmp/mgts-dataset-workbench-final.html` (87,315 bytes). A direct local `marimo run` smoke on `127.0.0.1:8791` returned HTTP 200 and was stopped afterward without submitting the form.
- The launcher supplies `MARIMO_WORKBENCH_PASSWORD` through stdin (`--token-password-file -`), unsets the exported variable before `uv run`, and masks `access_token=` values from Marimo stdout/stderr. Source inspection of Marimo 0.25.2 confirmed its normal startup URL includes an access-token query parameter, making the output filter necessary.
- Live server readback: `bash cv/data_pipeline/workbench.sh status` reports ready at `http://127.0.0.1:8790`; the listener is bound only to `127.0.0.1`. A password form POST using the canonical secret (passed only through stdin) returned HTTP 302, and the cookie-authenticated app GET returned HTTP 200. The credential was checked without printing against the server process tree's argv/environment and Zellij scrollback; it was absent, and the token-bearing startup URL was redacted.
- Laptop access used the configured SSH alias `dev-server` with `autossh` inside tmux, forwarding server loopback `127.0.0.1:8790` to laptop loopback `127.0.0.1:18790`. The listener was verified as `127.0.0.1:18790`; laptop-side `GET /auth/login` returned HTTP 200 and contained the login-form text. No public bind or public preview URL was used. The tunnel session is `mgts-workbench-tunnel`; the app session is `mgts-dataset-workbench-8790`.
- The launcher uses a lock under the user's runtime directory and `flock --close` so a persistent Zellij daemon cannot inherit the startup lock. The old generic `/tmp` lock and pre-existing `kpfu` session were left untouched; the workbench runs in its own named session.

## Optional photo inference

- Inspected the existing checkpoint metadata without unpickling or viewing images. `cv/ml/best.pt` is task `detect`, class `odn_pole`, base architecture `yolov8n.pt`, SHA-256 `17fa86e2c49de2e125f84b7badfb2f6983aa8a607dedee5eede4743d92d3883d`. The duplicate `best_BACKUP_1988.pt`, `best_REMOTE_1988.pt`, and `yolo-v/1-version.pt` have the same hash; the empty local variant was excluded.
- The CPU-only lock resolves Torch `2.15.0+cpu` and TorchVision `0.29.2+cpu` from the PyTorch CPU wheel index. Runtime reported torch `2.15.0+cpu`, `torch.version.cuda is None`, and Ultralytics `8.4.214`.
- Bounded numeric-only real prediction command used `cv/ml/dataset/test/images/4_jpg.rf.2c276660b8a78cf8c1a3b102e5797c4f.jpg` with the exact mounted/local `cv/ml/best.pt`. The 386x518 image returned one `odn_pole` detection at confidence `0.3975936770439148`, box `[172.97564697265625, 7.427586555480957, 224.40773010253906, 518.0]` in source-image pixel `xyxy` coordinates, using threshold 0.25. No pixel interpretation, training, external model download, saved preview, or prediction artifact was performed.
- `COVERAGE_FILE=/tmp/mgts-inference-final.coverage uv run --locked --extra test --extra ui --extra inference python -m pytest --cov=mgts_data_pipeline --cov-report=term-missing` from `cv/data_pipeline`: 97 passed, 85.32% total coverage; new inference module 91.04%.
- `uv lock --project cv/data_pipeline --check`, strict `marimo check`, `docker compose -f compose.ml.yml config --quiet`, and `git diff --check` passed. The container image/public runtime was not built or promoted by this work slice.
- Installed Ultralytics package metadata says AGPL-3.0; source/license link and unresolved checkpoint training-data/license provenance are disclosed in the UI and pipeline guide. No new model binary was added, and no production/accuracy claim is made.

## Hosted runtime verification

Dokploy compose `UP_ySpCqfZRWZQAj-0c6O`, app `compose-connect-auxiliary-bus-t7dvpy`, on 2.56.97.211. Runtime source `198f1aa7d7cc856acb8efa40253582b0f8591577`. Exact source archive contains pipeline and existing checkpoint, no dataset copy. HTTPS edge uses pinned internal Caddy CA to port18444. Password form login and authenticated GET passed over trusted public HTTPS. Hosted `infer_photo` on the correctly named fixture above returned the same numeric detection and exact model hash. No browser/pixel checks were used.

Initial runtime failures: Dokploy recursively changed mounted-secret owner to UID1001, conflicting with service UID10001; use read-only secret projection mode0444 inside host directory0700 and recreate service after correction (canonical secret remains0600). OpenCV lacked libxcb.so.1; image now installs libxcb1/libgl1/libglib2.0-0 and gates build on importing Ultralytics. Never reuse sanitized MCP config readback as write input.

## Hosted editor candidate

- Locked Marimo CLI reports version 0.25.2. `marimo edit --help` lists the `--host`, `--port`, `--headless`, `--token-password-file`, and `--trusted` options used by the container entrypoint.
- `cd cv/data_pipeline && uv run --extra test python -m pytest tests/test_container_contract.py -q`: 6 passed. The entrypoint integration stubs verify editor mode and exact password-file argument, reject an empty password before launch, seed a new writable notebook, and preserve user edits after the bundled source changes. No password value is present in captured output.
- `bash -n cv/data_pipeline/container-entrypoint.sh`, `docker compose -f compose.ml.yml config --quiet`, `marimo check --strict cv/data_pipeline/notebooks/dataset_workbench.py`, and `git diff --check` passed.
- This candidate was not image-built or deployed here. Coordinator deployment/readback remains open: verify authenticated HTTP editor behavior and that notebook edits persist after container recreation, without browser or visual inspection.
