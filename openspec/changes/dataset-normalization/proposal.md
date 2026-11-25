# Dataset normalization CLI

Prepare the six collected infrastructure datasets for reproducible local YOLO detection training without modifying source data or production inference. Support inspect/fetch/normalize/validate via a documented CLI using uv. Secrets enter only through HF_TOKEN/environment, never source or logs. Pinned source revisions and checksums are recorded.

Support Roboflow ZIP mixed bbox/polygon YOLO, PD-Defect YOLO directories, OHL-UK COCO ZIP, Streetlevel Poles embedded-image COCO Parquet, and quarantined Powerline Faults XYXY Parquet. Keep source/task classes separate: localization is not damage; compromised is not necessarily broken. Polygon-to-box conversion must be explicit in provenance. No training or model accuracy claims.

Safety: reject archive traversal/symlinks and pathological expansion, bad image bytes, invalid class IDs and non-finite/out-of-bounds annotations; uncertain faults stay opt-in with reject/report defaults. Preserve originals, refuse overwrite of occupied outputs, deterministic outputs and detailed counts/provenance. Deduplicate exact image content across splits; group Roboflow augmented variants by original identifier; report limits on scene/near-duplicate detection instead of promising leakage-free data. Missing original heldout split requires explicit reproducible split policy or flag output as not evaluation-ready.

Acceptance: unit/integration/CLI tests including malicious archive and corrupt labels; >=80% focused coverage; real source smoke runs with numeric inspection only (no vision); documentation and six-source status matrix; source code reviewed locally, focused commit, no protected merge. Publishing a new PR requires current-task user authorization.

## Clarifications from candidate review
- The initial local-only preference was later superseded by explicit
  authorization for a WIP PR. Forge publication remains coordinator-owned;
  implementation work in this worktree is not pushed by this agent.
- Fetch must bootstrap every source on a fresh machine, including ZIP archives and their manifests, not rely on session-specific /tmp files.
- Read actual Parquet ClassLabel names, not opaque numeric names when names exist.
- A dataset blocked by conflicting duplicate annotations must remain explicitly blocked; do not arbitrarily keep one annotation. Documentation must offer an executable known-working recipe rather than a known-failing all-source command.

## Local interactive workbench

Provide an optional Marimo UI over the existing CLI operations; normalization
logic and safety rules remain owned by the CLI. The UI offers inspect, fetch,
normalize, and validate, source selection, archive/Hub roots, output/validation
paths, and the existing strict-invalid/quarantine flags. Default source
selection is the verified `broken_poles_v2` starter recipe. The user must
submit the form explicitly; opening the app or editing controls must never
inspect, fetch, normalize, or validate data. Render structured reports and
surface source limitations, especially train-only status and the blocked
Powerline/all-source path. Marimo remains an optional dependency. This is a
local data-preparation UI only: no training, upload, secret entry, or image
preview. When the user requests a server-hosted preview, use the dedicated
demo session and configured reverse-SSH port forward. Bind the
password-authenticated app to server loopback only; do not expose a public IP or
interface.

Acceptance: focused tests prove the unsubmitted form does no work, submitted
configuration maps to existing CLI arguments, and invalid/incomplete
configuration fails before CLI execution. `marimo check` and a text-only local
runtime smoke verify the app; docs state the optional install and local launch
commands. The requested server preview must have a protected canonical auth
secret, a verified PID/readiness result, no credential in logs/argv, and an
HTTP/text response through the laptop's loopback forward.

## Containerized Marimo workbench

Provide a separate, human-editable Compose deployment for the existing
workbench, built from `cv/data_pipeline` and the committed `uv.lock`. Keep the
app bound to `0.0.0.0` only inside the container; publish host port 8790 on
loopback by default. Require password authentication from a read-only secret
file, never a password argument, log entry, or URL. Configure the Hugging Face
credential only through a protected runtime environment variable. Persist the
archive, Hub cache, and normalized output roots in separate volumes. Startup
must only serve the form: it must not fetch, normalize, validate, or train
without an explicit submission. The existing pipeline remains the only owner
of data operations. Document the Compose source path and the Dokploy service
source path/port configuration; local SSH forwarding remains a developer-only
preview and is not the public deployment path.

Acceptance: static tests cover the container/Compose security and persistence
contract; `docker compose config` validates the declarative service;
`marimo check --strict` and focused pipeline tests pass; a bounded image build
and authenticated text-only HTTP smoke do not trigger data work.

## Optional photo inference

Add one explicit-submit photo inference form to the optional Marimo workbench.
It accepts a single bounded JPEG/PNG/WebP upload, uses the already-present
`cv/ml/best.pt` checkpoint (metadata: YOLO detection, class `odn_pole`,
SHA-256 `17fa86e2c49de2e125f84b7badfb2f6983aa8a607dedee5eede4743d92d3883d`),
and returns class, confidence, and source-image pixel `xyxy` boxes as structured
text. The checkpoint is mounted read-only at `/models/best.pt`; a configured
`MGTS_MODEL_PATH` must resolve to an existing file before the predictor is
constructed. The predictor obtains class names and task from checkpoint
metadata rather than assuming a meaning from its filename. Inference runs on
CPU, does not save or preview images, and never downloads weights or trains.
Its single generic class is pole-object localization only: it is not a damaged
pole or defect detector, and its output is not an accuracy/validation claim.
The optional CPU inference dependency must not pull in CUDA variants.

Acceptance: unit tests use a mocked local predictor for result mapping,
explicit-input validation, task metadata, and the no-network-on-missing-file
guard; the Marimo UI only invokes inference after its form is submitted. A
single CPU inference against an existing repository test image confirms the
installed inference stack can load the exact local checkpoint and returns
numeric detection output without interpreting pixels, training, or writing
prediction artifacts. Document model hash, class/task limitations, read-only
mount/configuration, CPU-only install, and the absence of recorded model/data
license provenance. No model binaries are added.
