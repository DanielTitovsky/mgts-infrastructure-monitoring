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
