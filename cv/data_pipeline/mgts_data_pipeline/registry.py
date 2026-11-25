from __future__ import annotations

from dataclasses import dataclass


HUB_REPOSITORY = "itertea/mgts-infrastructure-datasets"
HUB_REVISION = "8d78368c4407e489ee7e0a3295607e76afc040f7"
HUB_REVISION_URL = f"https://huggingface.co/datasets/{HUB_REPOSITORY}/tree/{HUB_REVISION}"


@dataclass(frozen=True)
class SourceSpec:
    source_id: str
    title: str
    kind: str
    classes: tuple[str, ...]
    provenance: str
    license: str
    limitations: tuple[str, ...]
    source_layout: str
    collection_paths: tuple[str, ...] = ()
    collection_revision: str = HUB_REVISION


SOURCE_SPECS: dict[str, SourceSpec] = {
    "ohl_uk": SourceSpec(
        source_id="ohl_uk",
        title="OHL-UK overhead-line object detection",
        kind="ohl_coco_zip",
        classes=("Pole", "Sign"),
        provenance="OHL-UK; DOI 10.15129/df7cc895-1091-4cd6-bf2c-7b5ebd203e55",
        license="CC-BY-4.0",
        limitations=(
            "Uses only Object Detection/Fold 0 train_fold0 and val_fold0; folds are repeated partitions.",
            "Does not combine the separate Segmentation partition or unlabeled Test Images directory.",
            "No original test split is provided in the selected fold; not test-evaluation-ready.",
        ),
        source_layout="OHL-UK.zip + manifest.json (relative to --archive-root)",
        collection_paths=("OHL-UK.zip", "manifest.json"),
    ),
    "utility_pole_y8w7k_v3": SourceSpec(
        source_id="utility_pole_y8w7k_v3",
        title="Roboflow utility-pole-y8w7k v3",
        kind="roboflow_zip",
        classes=("Compromised-Pole", "Stable"),
        provenance="Roboflow utility-pole-y8w7k v3; source manifest SHA-256 1f621fac775109c6dfa51b9142baf0027a9f3b390ce59295adfb3e1b81950a4f",
        license="CC-BY-4.0",
        limitations=(
            "Roboflow exports mix boxes and polygon rows; polygons are explicitly converted to enclosing boxes.",
            "Augmented-family grouping uses the filename prefix before _jpg.rf.; this is not scene or near-duplicate detection.",
            "Compromised-Pole/Stable labels are not merged with broken/normal or other datasets.",
        ),
        source_layout="roboflow/export-1.zip + roboflow/utility-pole-y8w7k.json (relative to --archive-root)",
        collection_paths=(
            "roboflow/utility-pole-y8w7k/v3/dataset.zip",
            "roboflow/utility-pole-y8w7k/v3/SOURCE.json",
        ),
    ),
    "broken_poles_v2": SourceSpec(
        source_id="broken_poles_v2",
        title="Roboflow broken-poles v2",
        kind="roboflow_zip",
        classes=("broken", "normal"),
        provenance="Roboflow broken-poles-1-efa9c v2; source manifest SHA-256 50ff7ed26bf154ea4bf8bd82c7309046ab5772bf9968372b0180195c81e8727d",
        license="CC-BY-4.0",
        limitations=(
            "Train-only source; the normalized output remains train-only and is not evaluation-ready.",
            "Roboflow exports mix boxes and polygon rows; polygons are explicitly converted to enclosing boxes.",
            "Augmented-family grouping uses the filename prefix before _jpg.rf.; this is not scene or near-duplicate detection.",
            "broken/normal labels are not merged with Compromised-Pole/Stable or other datasets.",
        ),
        source_layout="roboflow/export-2.zip + roboflow/broken-poles-1-efa9c.json (relative to --archive-root)",
        collection_paths=(
            "roboflow/broken-poles-1-efa9c/v2/dataset.zip",
            "roboflow/broken-poles-1-efa9c/v2/SOURCE.json",
        ),
    ),
    "pd_defect": SourceSpec(
        source_id="pd_defect",
        title="PD-Defect pole lean assessment",
        kind="yolo_directory",
        classes=("Leaned_Pole", "Straight_Pole"),
        provenance="EPDCL/pd-defect @ b9c64b2f9615ef5ade71fceade7d9d31b0dc9416",
        license="CC-BY-4.0",
        limitations=(
            "Head-on smartphone capture; transfer README says moving-car imagery has not been validated.",
            "Lean assessment classes are separate from damage/fault classes.",
        ),
        source_layout="pd-defect/pole_lean_assessment/object_detection",
        collection_paths=(
            "pd-defect/SOURCE.json",
            "pd-defect/pole_lean_assessment/object_detection/**",
        ),
    ),
    "streetlevel_poles": SourceSpec(
        source_id="streetlevel_poles",
        title="Street-level poles and towers",
        kind="streetlevel_parquet",
        classes=("pole", "tower"),
        provenance="hotosm/streetlevel-poles @ 0352f0b2b067439ca3467994cb9938a42310a09e",
        license="CC-BY-SA-4.0",
        limitations=(
            "Object localization only, not defect labels; train split is heavily negative.",
            "Source geography and filename/source identifiers do not prove scene independence.",
        ),
        source_layout="streetlevel-poles/data/{train,val,test}/*.parquet",
        collection_paths=(
            "streetlevel-poles/SOURCE.json",
            "streetlevel-poles/README.md",
            "streetlevel-poles/data/**/*.parquet",
        ),
    ),
    "powerline_faults": SourceSpec(
        source_id="powerline_faults",
        title="Powerline components and faults",
        kind="powerline_parquet",
        classes=("Broken Cable", "Broken Insulator", "Cable", "Insulators", "Tower", "Vegetation"),
        provenance="docmhvr/powerline-components-and-faults @ 79a307bc40b0ccb9cc6bebd99d549e1b6b651be0",
        license="MIT (per source README)",
        limitations=(
            "Class IDs map to names from the pinned Parquet ClassLabel metadata; each file is checked against this mapping.",
            "XYXY boxes outside image bounds are rejected by default; --quarantine-invalid excludes whole records without clipping.",
            "Source is drone imagery with mosaic augmentation; it is not scene/near-duplicate audited.",
        ),
        source_layout="powerline-faults/data/{train,validation,test}-*.parquet",
        collection_paths=(
            "powerline-faults/SOURCE.json",
            "powerline-faults/README.md",
            "powerline-faults/data/*.parquet",
        ),
    ),
}

SOURCE_IDS = tuple(SOURCE_SPECS)
LOCAL_SOURCES = frozenset(("ohl_uk", "utility_pole_y8w7k_v3", "broken_poles_v2"))
HF_SOURCES = frozenset(SOURCE_IDS) - LOCAL_SOURCES


def source_ids(values: list[str] | tuple[str, ...]) -> list[str]:
    if "all" in values:
        if len(values) != 1:
            raise ValueError("'all' cannot be combined with individual source IDs")
        return list(SOURCE_IDS)
    if not values:
        return list(SOURCE_IDS)
    ordered = list(dict.fromkeys(values))
    unknown = sorted(set(ordered) - set(SOURCE_SPECS))
    if unknown:
        raise ValueError(f"unknown source IDs: {', '.join(unknown)}")
    return ordered
