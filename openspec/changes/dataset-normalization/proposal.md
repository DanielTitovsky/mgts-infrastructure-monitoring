# Dataset normalization CLI

Prepare the six collected infrastructure datasets for reproducible local YOLO detection training without modifying source data or production inference. Support inspect/fetch/normalize/validate via a documented CLI using uv. Secrets enter only through HF_TOKEN/environment, never source or logs. Pinned source revisions and checksums are recorded.

Support Roboflow ZIP mixed bbox/polygon YOLO, PD-Defect YOLO directories, OHL-UK COCO ZIP, Streetlevel Poles embedded-image COCO Parquet, and quarantined Powerline Faults XYXY Parquet. Keep source/task classes separate: localization is not damage; compromised is not necessarily broken. Polygon-to-box conversion must be explicit in provenance. No training or model accuracy claims.

Safety: reject archive traversal/symlinks and pathological expansion, bad image bytes, invalid class IDs and non-finite/out-of-bounds annotations; uncertain faults stay opt-in with reject/report defaults. Preserve originals, refuse overwrite of occupied outputs, deterministic outputs and detailed counts/provenance. Deduplicate exact image content across splits; group Roboflow augmented variants by original identifier; report limits on scene/near-duplicate detection instead of promising leakage-free data. Missing original heldout split requires explicit reproducible split policy or flag output as not evaluation-ready.

Acceptance: unit/integration/CLI tests including malicious archive and corrupt labels; >=80% focused coverage; real source smoke runs with numeric inspection only (no vision); documentation and six-source status matrix; source code reviewed locally, focused commit, no protected merge. Publishing a new PR requires current-task user authorization.

## Clarifications from candidate review
- User requested local-only delivery: no push or PR.
- Fetch must bootstrap every source on a fresh machine, including ZIP archives and their manifests, not rely on session-specific /tmp files.
- Read actual Parquet ClassLabel names, not opaque numeric names when names exist.
- A dataset blocked by conflicting duplicate annotations must remain explicitly blocked; do not arbitrarily keep one annotation. Documentation must offer an executable known-working recipe rather than a known-failing all-source command.
