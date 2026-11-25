# MGTS local dataset pipeline

This module provides a read-only `inspect`/`fetch` path and an atomic local
`normalize`/`validate` path for the six pinned research datasets. It prepares
separate YOLO detection datasets; it does **not** train a model, claim accuracy,
or change production inference. Originals remain immutable. Each output has its
own class vocabulary and provenance directory; labels from different sources
are never merged.

## Reproducible commands

From the repository root:

```sh
# Install only this pipeline's dependencies; no project-wide upgrades.
uv sync --project cv/data_pipeline --extra test

# Numeric source inventory (no pixel interpretation or rendering).
uv run --project cv/data_pipeline mgts-datasets inspect --source all
# Fail rather than reject and report any invalid annotation-bearing sample.
uv run --project cv/data_pipeline mgts-datasets inspect --source all --strict-invalid

# The private collection needs HF_TOKEN in the process environment. On the
# configured workstation, load it from the canonical secret store without
# printing it; elsewhere, provision HF_TOKEN using the local secret manager.
source /home/iter/projects/iter-private-setup/scripts/load-dotenv.sh /home/iter/.kiro/secrets.env
uv run --project cv/data_pipeline mgts-datasets fetch --source all

# Known-working selected-source recipe. This source is train-only, so the
# normalized output is not evaluation-ready. See the matrix for blocked sources.
uv run --project cv/data_pipeline mgts-datasets normalize \
  --source broken_poles_v2 --output /tmp/mgts-broken-poles
uv run --project cv/data_pipeline mgts-datasets validate /tmp/mgts-broken-poles

# Focused tests and the enforced 80% coverage threshold.
cd cv/data_pipeline
uv run --extra test python -m pytest --cov=mgts_data_pipeline --cov-report=term-missing
```

## Containerized workbench (Compose and Dokploy)

`compose.ml.yml` at the repository root is the dedicated container definition
for the existing Marimo workbench. Its build context is only
`cv/data_pipeline`; it installs the committed `uv.lock` with the optional UI
and CPU inference extras and reuses the same CLI-backed form. The existing
`cv/ml/best.pt` checkpoint is not copied into the image: Compose bind-mounts a
host artifact read-only at `/models/best.pt`. The default host source is
`./cv/ml/best.pt`; set `MGTS_MODEL_FILE` to an absolute path for a
host-managed artifact. The app reads it only after photo-form submission and
never downloads replacement weights. The container listens on port 8790
inside its network, while the default host publishing is restricted to
`127.0.0.1:8790`. Separate named volumes preserve `/data/archive`, `/data/hub`,
and `/data/output`; set `MGTS_VOLUME_PREFIX` if a different deployment needs
its own volume names. Starting the service serves the forms only—no dataset is
fetched, normalized, validated, or trained, and no photo inference runs until
a user explicitly submits the corresponding operation.

Before starting locally, provision a non-empty password file with a secure
secret manager or editor at `.secrets/marimo_password`; this path is ignored by
Git. Set `MARIMO_PASSWORD_FILE` to a protected absolute file path when using a
different location. Do not put the password in Compose arguments, an image, a
URL, or logs. The file is mounted read-only at `/run/secrets/marimo_password`
and Marimo's access-token query string is redacted from container logs. Set
`HF_TOKEN` only through a protected process environment or Dokploy secret; it
is optional for starting the app and required only when an explicitly
submitted private-Hub operation needs it.

Validate and start the independent service from the repository root:

```sh
docker compose -f compose.ml.yml config --quiet
docker compose -f compose.ml.yml up -d --build
docker compose -f compose.ml.yml ps
docker compose -f compose.ml.yml down  # preserves the named data volumes
```

For the public server deployment, configure Dokploy to build this repository
candidate using Compose file `compose.ml.yml` from the repository root. Route
the HTTPS domain to the `workbench` service on its internal port `8790`; keep
the Compose host-port binding at its loopback default rather than publishing
8790 directly to a public interface. Configure `MARIMO_PASSWORD_FILE` as a
path to a protected, host-side secret file and `HF_TOKEN` as a protected
runtime secret when private Hub access is needed. Keep the data volumes
persistent across deployments. The SSH-forwarded `workbench.sh` flow below is
only a local developer preview, not the public deployment path.

## Interactive local workbench (optional)

Install the optional Marimo UI and CPU inference extras, then either run it on
your local machine or use the configured server preview:

```sh
uv sync --project cv/data_pipeline --extra ui --extra inference
# Local app; Marimo prints its URL and listens on loopback by default.
MGTS_MODEL_PATH="$PWD/cv/ml/best.pt" uv run --project cv/data_pipeline \
  --extra ui --extra inference marimo run \
  cv/data_pipeline/notebooks/dataset_workbench.py
# Static notebook check.
uv run --project cv/data_pipeline --extra ui --extra inference marimo check --strict \
  cv/data_pipeline/notebooks/dataset_workbench.py
```

The dataset app is a thin form over the same `mgts-datasets` CLI. It does not duplicate
normalization code. Select an action, source(s), roots and paths, then submit
the form: **opening the app or editing form controls does not run a pipeline
operation**. The default is the known-working `broken_poles_v2` starter source;
its data is train-only and remains unsuitable for evaluation without a separate
held-out split. The form exposes no image preview, model training, Hub upload,
or token field. For private Hub downloads, provision `HF_TOKEN` to the server
process through the configured secret store.

Photo inference is a separate explicit-submit form. It accepts one JPEG, PNG,
or WebP file up to 10 MB / 20 megapixels, runs on CPU, does not render or save
the image, and returns class names from the checkpoint metadata, confidence,
and source-image pixel `xyxy` boxes. Local launchers must point
`MGTS_MODEL_PATH` to an existing trusted checkpoint; the default is
`/models/best.pt`. A missing or invalid checkpoint fails closed before any
prediction—there is no weight download or training fallback.

The selected existing artifact is `cv/ml/best.pt`, whose checkpoint metadata
identifies task `detect`, class `odn_pole`, and YOLOv8n base architecture.
Its SHA-256 is
`17fa86e2c49de2e125f84b7badfb2f6983aa8a607dedee5eede4743d92d3883d`.
This is generic pole-object localization only, not a damage detector, and no
accuracy or held-out evaluation claim is made. The repository does not record
the checkpoint's original training-data source or license. Ultralytics 8.4.214
is licensed AGPL-3.0 ([upstream source and
license](https://github.com/ultralytics/ultralytics/blob/main/LICENSE));
resolve applicable source-offer/enterprise obligations before any public or
production deployment. Do not expose a model-file download endpoint.

The inference extra selects CPU-only Torch/TorchVision wheels from the official
CPU wheel index; no CUDA runtime is installed. The install and launch commands
above show the local model path. For the Compose service, `MGTS_MODEL_PATH` is
fixed at `/models/best.pt` and the host-side mount source is configurable with
`MGTS_MODEL_FILE`.

For a user-browser preview on the configured server, the workbench launcher
starts, checks, or stops the app in the dedicated demo session. It uses
password authentication on loopback and prints the server PID/readiness. The
current task's access path is a local SSH forward, not a public server port:

```sh
bash cv/data_pipeline/workbench.sh start
bash cv/data_pipeline/workbench.sh status
bash cv/data_pipeline/workbench.sh stop
```

The shared password is stored only in canonical
`/home/iter/projects/iter-private-setup/shared.env` as
`MARIMO_WORKBENCH_PASSWORD`; `/home/iter/.kiro/secrets.env` is its symlink
projection. Do not put the password in shell history or the command line.
On this server, open the app at `http://127.0.0.1:18790` on the user's laptop
after the reverse-SSH forward is active. The tunnel must target server port
8790. Do not expose the authenticated app through a public IP or bind it to
`0.0.0.0` for this local preview. On the configured laptop, where `dev-server`
is its SSH alias for this host, start the loopback-only forward with:

```sh
tmux new-session -d -s mgts-workbench-tunnel \
  'AUTOSSH_GATETIME=0 autossh -M 0 -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -o ExitOnForwardFailure=yes -L 127.0.0.1:18790:127.0.0.1:8790 dev-server'
```

The authenticated server runs in the dedicated Zellij session
`mgts-dataset-workbench-8790`; it receives the configured password through
Marimo's stdin password-file option and redacts Marimo's token-bearing startup
URL before it reaches terminal output. To stop access, run
`tmux kill-session -t mgts-workbench-tunnel` on the laptop and
`bash cv/data_pipeline/workbench.sh stop` on the server. The password itself
remains only in the canonical local secret store and must not be put in a URL,
command line, or log.

The all-source recipe is intentionally not exposed in the UI: Powerline Faults
still fails closed on conflicting duplicate labels even when invalid rows are
quarantined. Other classes remain separate: lean is not broken,
Compromised-Pole is not broken, and object-localization sources are not defect
labels. The UI displays these limitations before the form.

`fetch` reads only pinned files from private Hugging Face dataset revision
`8d78368c4407e489ee7e0a3295607e76afc040f7`; it never uploads or modifies Hub
state. On a new machine it downloads the three ZIP archives **and** their source
manifests into `--archive-root` (default `/tmp/mgts-dataset-transfer`); files
for the other sources go into `--hub-root`. It reuses existing local files only
when they match the pinned checksums and Hub object IDs; a mismatched archive
or manifest fails closed and is never overwritten. Set `--archive-root` to a
durable location if `/tmp` is not suitable. `HF_TOKEN` is read from the
environment; it is not accepted as a CLI argument and is never written to
output. A token is needed when local files are missing and for the private Hub
sources. If all requested local files are already verified, fetching those
local sources can run without a token.

`normalize` refuses any output path that already exists. It builds in a sibling
temporary directory, validates the candidate, and only then renames it into
place. To rerun, select a new destination; do not delete or overwrite an output
implicitly. For non-Powerline sources, an image with any malformed annotation
is rejected whole and recorded in `rejects.json`; the pipeline never keeps only
the valid boxes from a bad sample. `--strict-invalid` restores fail-fast
behavior for invalid annotations. Powerline Faults additionally requires the
explicit `--quarantine-invalid` opt-in; without it, invalid records fail closed.
When opted in, each bad row is excluded whole and listed in `rejects.json`. No
coordinates are clipped, repaired, or silently dropped.

The output contains one subdirectory per source, with local `data.yaml`,
`images/`, `labels/`, `SOURCE.json`, `samples.jsonl`, and
`deduplicated.jsonl`. If invalid source records were rejected, it also contains
`rejects.json` with the source path, split, reason, and number of annotation
entries excluded with that record. `SOURCE.json` and the multi-source catalog
include rejection counts. A source without both held-out `val` and `test`
partitions is marked `evaluation_ready: false`; the pipeline does not invent a
split. Run `validate` on either one source subdirectory or the multi-source
output root.

## Six-source matrix

| ID | Pinned source / selected format | Source classes kept separate | Numeric inventory and policy | Evaluation / known limitations |
| --- | --- | --- | --- | --- |
| `ohl_uk` | OHL-UK ZIP SHA-256 `1de42934b8e446b4229a38af501a76ca0e5ac574c81281e7362abdf5efbe639d`; COCO Object Detection Fold 0 only | `Pole`, `Sign` | Fold 0 has 2,920 train and 730 val images; 5,277 and 1,318 COCO boxes | No test split in the selected fold. The five folds are repeated partitions; the separate Segmentation and unlabeled Test Images trees are not mixed in. CC BY 4.0. |
| `utility_pole_y8w7k_v3` | Roboflow utility-pole-y8w7k v3 ZIP SHA-256 `1f621fac775109c6dfa51b9142baf0027a9f3b390ce59295adfb3e1b81950a4f` | `Compromised-Pole`, `Stable` | 24,031 images; 10,384 bbox rows and 19,510 polygon rows | Polygon rows become enclosing axis-aligned boxes, counted in output provenance. Filename-prefix family grouping is a heuristic, not scene/near-duplicate detection. CC BY 4.0. |
| `broken_poles_v2` | Roboflow broken-poles v2 ZIP SHA-256 `50ff7ed26bf154ea4bf8bd82c7309046ab5772bf9968372b0180195c81e8727d` | `broken`, `normal` | 604 train-only images; 857 bbox rows and 3 polygon rows | Remains train-only and not evaluation-ready. Polygon conversion and grouping limits are as above. CC BY 4.0. |
| `pd_defect` | `EPDCL/pd-defect` at `b9c64b2f9615ef5ade71fceade7d9d31b0dc9416`; `pole_lean_assessment/object_detection` YOLO tree | `Leaned_Pole`, `Straight_Pole` | 1,801 images, source YOLO labels retained as boxes | Lean assessment is not damage/fault classification; source notes head-on smartphone capture and no moving-car validation. CC BY 4.0. |
| `streetlevel_poles` | `hotosm/streetlevel-poles` at `0352f0b2b067439ca3467994cb9938a42310a09e`; embedded-image Parquet with COCO pixel `xywh` boxes/categories | `pole`, `tower` | 3,500 images; source README reports 1,563 boxes | Object localization, not defect labels; train is heavily negative. CC BY-SA 4.0. Source imagery/geography does not guarantee scene independence. |
| `powerline_faults` | `docmhvr/powerline-components-and-faults` at `79a307bc40b0ccb9cc6bebd99d549e1b6b651be0`; embedded-image Parquet with XYXY boxes/labels | `Broken Cable`, `Broken Insulator`, `Cable`, `Insulators`, `Tower`, `Vegetation` (class IDs are validated against Parquet `ClassLabel` metadata) | 1,912 640×640 images; 15,067 boxes, of which 4,989 fail XYXY bounds/geometry validation | Invalid records fail closed by default; `--quarantine-invalid` opts into excluding whole bad records with a reject report. Normalization still fails closed on exact duplicate images with conflicting labels; do not select one arbitrarily. Thus Powerline and `--source all` are currently blocked. MIT per source README; drone imagery and mosaic augmentation. |

The final `inspect` report includes current numeric counts and source-checksum
readback. The fetch manifest records checksums for downloaded or reused source
files. Output manifests preserve the source commit, collection commit,
checksums, class mapping, split counts, format conversions, duplicate counts,
EXIF orientation values, and rejected-record counts. Local images are copied
byte-for-byte: dimensions and labels use the encoded image's raw coordinate
frame, no image is transposed or re-encoded, and EXIF metadata is preserved.

Exact SHA-256 image duplicates are removed deterministically within each source
dataset. Roboflow variants are grouped by the portion of their image filename
before `_jpg.rf.` and assigned to their majority source split (ties prefer
train, then val, then test). This reduces augmentation-family split leakage but
does not identify shared scenes or near-duplicates. Sources remain separate so
`Stable` is not equated with `normal`, `pole` detection is not equated with
defect detection, and powerline component labels stay in their own vocabulary.

## Safety / failure behavior

- ZIP members are checked for traversal, absolute/drive paths, symlinks,
  duplicate names, excessive member counts/sizes, and pathological expansion
  before selected members are read. Source files are never extracted in place.
- Every emitted image is decoded and checked for supported format, finite size,
  and corrupt bytes. Labels reject unknown class IDs, non-finite numbers,
  zero-area/out-of-bounds boxes, malformed polygons, and mismatched source
  dimensions; a malformed annotation rejects that whole sample unless
  `--strict-invalid` is set. Powerline invalid rows still require the explicit
  quarantine opt-in. Polygon-to-box conversion is explicit and counted.
- Exact duplicate bytes with conflicting annotations fail closed rather than
  selecting one label arbitrarily. Every output image receives a label file,
  including an empty file for a negative example.
- The Hub repository revision and each fetched local archive, source manifest,
  or Hub file checksum are written to `.mgts-fetch-manifest.json`; output
  provenance copies a deterministic hash of its source-specific record and the
  selected per-file inventory. Inputs must still match those checksums during
  normalization.
- The `validate` command re-decodes images, verifies normalized labels, checks
  source/output counts and class IDs, and catches duplicate images, orphan
  labels, unsafe links, or invalid YAML/JSON metadata.

Pass an **absolute** path to the generated `data.yaml` to Ultralytics. The YAML intentionally omits `path` so its own directory is the dataset root, rather than a global Ultralytics datasets directory. Train-only outputs still require a separately prepared held-out validation split before normal training/evaluation.
