"""Bounded, read-only review helpers for the editable ML workbench.

The supplied final photo inventory contains image-level spreadsheet labels, not
object bounding boxes.  These helpers preserve that distinction and only load
the manifest or the single sample explicitly selected by a user.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, UnidentifiedImageError
import yaml

from .adapters import parse_yolo_row
from .errors import PipelineError
from .registry import SOURCE_SPECS


MAX_MANIFEST_BYTES = 5_000_000
MAX_MATERIAL_SAMPLES = 5_000
MAX_IMAGE_BYTES = 10_000_000
MAX_IMAGE_PIXELS = 20_000_000
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
IMAGE_FORMATS = {"JPEG", "PNG", "WEBP"}
MAX_DATASET_IMAGES = 20_000
MAX_METADATA_BYTES = 2_000_000
MAX_PREVIEW_EDGE = 1_600
MAX_PREVIEW_BYTES = 1_000_000
GROUND_TRUTH_COLOR = (20, 210, 100)
PREDICTION_COLOR = (255, 150, 20)


class ResearchError(ValueError):
    """Invalid manifest, dataset sample, or experiment configuration."""


def _read_json(path: Path, *, maximum_bytes: int, label: str) -> dict[str, Any]:
    if path.is_symlink():
        raise ResearchError(f"{label} cannot be a symlink")
    if not path.is_file():
        raise ResearchError(f"{label} does not exist: {path}")
    try:
        size = path.stat().st_size
        if size > maximum_bytes:
            raise ResearchError(f"{label} exceeds the {maximum_bytes} byte size limit")
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except ResearchError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ResearchError(f"cannot read {label}: {type(error).__name__}") from error
    if not isinstance(parsed, dict):
        raise ResearchError(f"{label} must contain a JSON object")
    return parsed


def _validate_material_samples(raw_samples: object) -> list[dict[str, Any]]:
    if not isinstance(raw_samples, list) or len(raw_samples) > MAX_MATERIAL_SAMPLES:
        raise ResearchError(f"manifest samples must be a list with at most {MAX_MATERIAL_SAMPLES} rows")
    required = ("image_path", "object_type", "condition", "source_folder", "object_id", "status", "description")
    seen_paths: set[str] = set()
    samples: list[dict[str, Any]] = []
    for index, item in enumerate(raw_samples):
        if not isinstance(item, dict):
            raise ResearchError(f"manifest sample {index} must be an object")
        missing = [field for field in required if field not in item]
        if missing:
            raise ResearchError(f"manifest sample {index} is missing {', '.join(missing)}")
        sample = dict(item)
        for field in required:
            value = sample[field]
            if not isinstance(value, str) or (field not in {"status", "description"} and not value.strip()):
                raise ResearchError(f"manifest sample {index} has invalid {field}")
        image_path = sample["image_path"]
        relative = PurePosixPath(image_path)
        raw_parts = image_path.split("/")
        if (
            not image_path
            or "\\" in image_path
            or relative.is_absolute()
            or any(part in {"", ".", ".."} for part in raw_parts)
            or relative.suffix.lower() not in IMAGE_SUFFIXES
        ):
            raise ResearchError(f"manifest sample {index} image_path must be a safe relative image path")
        if image_path in seen_paths:
            raise ResearchError(f"manifest contains duplicate image_path {image_path!r}")
        seen_paths.add(image_path)
        digest = sample.get("sha256")
        if digest is not None and (
            not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest.lower())
        ):
            raise ResearchError(f"manifest sample {index} has invalid sha256")
        samples.append(sample)
    return samples


def load_material_manifest(path: str | Path) -> dict[str, Any]:
    """Read bounded manifest metadata and summarize labels without opening photos."""
    manifest_path = Path(path).expanduser()
    raw = _read_json(manifest_path, maximum_bytes=MAX_MANIFEST_BYTES, label="materials manifest")
    if raw.get("schema_version") != 1:
        raise ResearchError("materials manifest schema_version must be 1")
    samples = _validate_material_samples(raw.get("samples"))
    warnings = raw.get("warnings", [])
    if not isinstance(warnings, list) or any(not isinstance(warning, str) for warning in warnings):
        raise ResearchError("manifest warnings must be a list of strings")
    supplied_counts = raw.get("counts", {})
    if not isinstance(supplied_counts, dict):
        raise ResearchError("manifest counts must be an object")
    return {
        "path": manifest_path.resolve(),
        "sample_count": len(samples),
        "samples": samples,
        "warnings": warnings,
        "counts": supplied_counts,
        "summary": {
            "object_type": dict(sorted(Counter(sample["object_type"] for sample in samples).items())),
            "condition": dict(sorted(Counter(sample["condition"] for sample in samples).items())),
            "split": dict(sorted(Counter(str(sample.get("split", "unassigned")) for sample in samples).items())),
        },
    }


def _safe_material_image_path(manifest_path: Path, sample: Mapping[str, Any]) -> Path:
    relative = PurePosixPath(str(sample["image_path"]))
    root = manifest_path.parent.resolve()
    candidate = root.joinpath(*relative.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
    except (OSError, ValueError) as error:
        raise ResearchError("manifest image_path must resolve to an existing file beneath the manifest directory") from error
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ResearchError("manifest image sample cannot be a symlink")
    if not resolved.is_file():
        raise ResearchError("manifest image_path does not name a regular image file")
    return resolved


def _decode_bounded_image(path: Path) -> tuple[Image.Image, bytes]:
    try:
        size = path.stat().st_size
        if size > MAX_IMAGE_BYTES:
            raise ResearchError(f"image exceeds the {MAX_IMAGE_BYTES} byte size limit")
        content = path.read_bytes()
        if not content:
            raise ResearchError("image file is empty")
        with Image.open(path) as image:
            if image.format not in IMAGE_FORMATS:
                raise ResearchError("image must be JPEG, PNG, or WebP")
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ResearchError(f"image exceeds the {MAX_IMAGE_PIXELS // 1_000_000} MP limit")
            image.verify()
        with Image.open(path) as image:
            image.load()
            return image.convert("RGB"), content
    except ResearchError:
        raise
    except (Image.DecompressionBombError, OSError, UnidentifiedImageError, ValueError) as error:
        raise ResearchError("image file could not be decoded") from error


def load_material_sample(path: str | Path, index: int) -> dict[str, Any]:
    """Load one explicitly selected cabinet photo and preserve its original labels."""
    manifest_path = Path(path).expanduser()
    manifest = load_material_manifest(manifest_path)
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < manifest["sample_count"]:
        raise ResearchError("sample index is outside the manifest")
    sample = manifest["samples"][index]
    image_path = _safe_material_image_path(manifest_path, sample)
    image, content = _decode_bounded_image(image_path)
    expected_digest = sample.get("sha256")
    actual_digest = hashlib.sha256(content).hexdigest()
    if expected_digest and actual_digest.lower() != expected_digest.lower():
        raise ResearchError("image SHA-256 does not match the manifest")
    boxes = sample.get("bbox_annotations")
    if boxes not in (None, []):
        raise ResearchError("final-materials bbox_annotations must be empty; spreadsheet labels are image-level only")
    return {
        "sample": sample,
        "image": image,
        "image_bytes": content,
        "width": image.width,
        "height": image.height,
        "sha256": actual_digest,
        "ground_truth_boxes": None,
        "warning": "No bounding-box labels were supplied; conditions are original image-level spreadsheet labels, not model predictions.",
    }


def preview_image_bytes(
    image: Image.Image,
    *,
    max_edge: int = MAX_PREVIEW_EDGE,
    max_bytes: int = MAX_PREVIEW_BYTES,
) -> bytes:
    """Encode a compact notebook display copy without changing the source photo."""
    if not isinstance(image, Image.Image):
        raise ResearchError("preview input must be a decoded image")
    if (
        isinstance(max_edge, bool)
        or not isinstance(max_edge, int)
        or max_edge < 1
        or isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or max_bytes < 1
    ):
        raise ResearchError("preview limits must be positive integers")
    edge = min(max_edge, MAX_PREVIEW_EDGE)
    preview = image.copy().convert("RGB")
    preview.thumbnail((edge, edge), Image.Resampling.LANCZOS)
    quality = 85
    while True:
        buffer = BytesIO()
        preview.save(buffer, format="JPEG", quality=quality, optimize=True)
        encoded = buffer.getvalue()
        if len(encoded) <= max_bytes:
            return encoded
        if quality > 55:
            quality -= 10
        elif edge > 256:
            edge = max(256, edge * 3 // 4)
            preview = image.copy().convert("RGB")
            preview.thumbnail((edge, edge), Image.Resampling.LANCZOS)
            quality = 85
        else:
            raise ResearchError("preview cannot fit within the requested byte limit")


def _class_names(config: Mapping[str, Any]) -> list[str]:
    names = config.get("names")
    if isinstance(names, dict):
        try:
            ordered = [str(names[index]) for index in range(len(names))]
        except KeyError as error:
            raise ResearchError("data.yaml class IDs must be contiguous from zero") from error
    elif isinstance(names, list):
        ordered = [str(name) for name in names]
    else:
        raise ResearchError("data.yaml must declare class names")
    if not ordered or any(not name.strip() for name in ordered):
        raise ResearchError("data.yaml class names cannot be empty")
    if config.get("nc", len(ordered)) != len(ordered):
        raise ResearchError("data.yaml nc does not match its class names")
    return ordered


def _split_directory(data_yaml: Path, config: Mapping[str, Any], split: str) -> Path:
    configured = config.get(split)
    if not isinstance(configured, str) or not configured.strip():
        raise ResearchError(f"data.yaml does not declare a {split} split directory")
    dataset_root_value = config.get("path", data_yaml.parent)
    if not isinstance(dataset_root_value, (str, Path)):
        raise ResearchError("data.yaml path must be a local directory")
    dataset_root = Path(dataset_root_value).expanduser()
    if not dataset_root.is_absolute():
        dataset_root = data_yaml.parent / dataset_root
    directory = Path(configured).expanduser()
    if not directory.is_absolute():
        directory = dataset_root / directory
    if directory.is_symlink():
        raise ResearchError(f"{split} image directory cannot be a symlink")
    directory = directory.resolve()
    if not directory.is_dir():
        raise ResearchError(f"{split} image directory is missing or unsafe")
    return directory


def _labels_directory(image_dir: Path) -> Path:
    parts = list(image_dir.parts)
    try:
        image_component = parts.index("images")
    except ValueError as error:
        raise ResearchError("YOLO image split path must contain an 'images' directory component") from error
    parts[image_component] = "labels"
    return Path(*parts)


def _dataset_source_metadata(data_yaml: Path) -> dict[str, Any]:
    metadata_path = data_yaml.parent / "SOURCE.json"
    if not metadata_path.exists():
        return {}
    return _read_json(metadata_path, maximum_bytes=MAX_METADATA_BYTES, label="dataset SOURCE.json")


def _source_warnings(source_metadata: Mapping[str, Any], class_names: Sequence[str], config: Mapping[str, Any]) -> list[str]:
    warnings: list[str] = []
    source_id = source_metadata.get("source_id")
    if isinstance(source_id, str) and source_id in SOURCE_SPECS:
        warnings.extend(SOURCE_SPECS[source_id].limitations)
    if source_metadata.get("evaluation_ready") is False:
        missing = source_metadata.get("evaluation_missing_splits", [])
        warnings.append(f"This normalized dataset is not evaluation-ready; missing held-out splits: {missing}.")
    if source_metadata.get("scene_independence_claim") is False:
        warnings.append("No scene/near-duplicate independence claim is recorded; split names alone do not prove an independent holdout.")
    if len(class_names) == 1 and class_names[0].casefold() == "odn_pole":
        warnings.append("odn_pole is generic pole-object localization only; it does not classify damage, health, or repair urgency.")
    for split in ("val", "test"):
        if config.get(split) is None:
            warnings.append(f"No {split} split is declared in data.yaml.")
    if not warnings:
        warnings.append("Class meanings remain dataset-specific; do not merge or reinterpret them without a human-approved mapping.")
    return list(dict.fromkeys(warnings))


def inspect_yolo_sample(data_yaml_path: str | Path, split: str, index: int) -> dict[str, Any]:
    """Read one YOLO image, its original normalized rows, and pixel-space boxes."""
    yaml_path = Path(data_yaml_path).expanduser()
    if yaml_path.is_symlink() or not yaml_path.is_file():
        raise ResearchError("data.yaml does not exist or is unsafe")
    if split not in {"train", "val", "test"}:
        raise ResearchError("split must be one of train, val, or test")
    try:
        config = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as error:
        raise ResearchError("cannot read data.yaml") from error
    if not isinstance(config, dict):
        raise ResearchError("data.yaml must contain a mapping")
    class_names = _class_names(config)
    image_dir = _split_directory(yaml_path, config, split)
    try:
        labels_dir = _labels_directory(image_dir)
    except ResearchError:
        raise
    if labels_dir.is_symlink():
        raise ResearchError("label directory cannot be a symlink")
    image_paths = sorted(path for path in image_dir.iterdir() if path.suffix.lower() in IMAGE_SUFFIXES)
    if len(image_paths) > MAX_DATASET_IMAGES:
        raise ResearchError(f"split exceeds the {MAX_DATASET_IMAGES} image browse limit")
    if not image_paths:
        raise ResearchError(f"{split} split contains no supported images")
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(image_paths):
        raise ResearchError("sample index is outside the selected split")
    image_path = image_paths[index]
    if image_path.is_symlink():
        raise ResearchError("selected image cannot be a symlink")
    if not image_path.is_file():
        raise ResearchError("selected image is missing or unsafe")
    image, content = _decode_bounded_image(image_path)
    label_path = labels_dir / f"{image_path.stem}.txt"
    warnings: list[str] = []
    rows: list[dict[str, Any]] = []
    if label_path.is_symlink():
        raise ResearchError("selected label file cannot be a symlink")
    if label_path.exists():
        if not label_path.is_file() or label_path.stat().st_size > 1_000_000:
            raise ResearchError("selected label file is unsafe or exceeds the 1 MB limit")
        try:
            text = label_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise ResearchError("selected label file is not valid UTF-8") from error
        for line_number, raw_line in enumerate(text.splitlines(), 1):
            if not raw_line.strip():
                continue
            try:
                annotation, kind = parse_yolo_row(raw_line, len(class_names))
            except PipelineError as error:
                raise ResearchError(f"invalid YOLO label at line {line_number}: {error}") from error
            if kind != "bbox":
                raise ResearchError(f"normalized label at line {line_number} is not a box")
            x1 = (annotation.x_center - annotation.width / 2) * image.width
            y1 = (annotation.y_center - annotation.height / 2) * image.height
            x2 = (annotation.x_center + annotation.width / 2) * image.width
            y2 = (annotation.y_center + annotation.height / 2) * image.height
            rows.append(
                {
                    "line_number": line_number,
                    "raw": raw_line,
                    "class_id": annotation.class_id,
                    "class_name": class_names[annotation.class_id],
                    "normalized_xywh": [annotation.x_center, annotation.y_center, annotation.width, annotation.height],
                    "bbox_xyxy_px": [round(value, 3) for value in (x1, y1, x2, y2)],
                }
            )
    else:
        warnings.append("The selected image has no matching normalized label file.")
    source_metadata = _dataset_source_metadata(yaml_path)
    warnings.extend(_source_warnings(source_metadata, class_names, config))
    return {
        "data_yaml": yaml_path.resolve(),
        "split": split,
        "index": index,
        "image_path": image_path,
        "image_bytes": content,
        "image": image,
        "width": image.width,
        "height": image.height,
        "class_names": class_names,
        "label_rows": rows,
        "source_metadata": source_metadata,
        "warnings": list(dict.fromkeys(warnings)),
    }


def _checked_box(value: object, *, image_size: tuple[int, int]) -> tuple[float, float, float, float]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise ResearchError("box coordinates must contain four finite pixel values")
    try:
        box = tuple(float(coordinate) for coordinate in value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ResearchError("box coordinates must contain four finite pixel values") from error
    width, height = image_size
    if (
        not all(math.isfinite(coordinate) for coordinate in box)
        or box[0] < 0
        or box[1] < 0
        or box[2] > width
        or box[3] > height
        or box[2] <= box[0]
        or box[3] <= box[1]
    ):
        raise ResearchError("box coordinates must be finite and within the image bounds")
    return box


def draw_box_overlay(
    image: Image.Image,
    *,
    ground_truth: Sequence[Mapping[str, Any]] = (),
    predictions: Sequence[Mapping[str, Any]] = (),
) -> Image.Image:
    """Return a human-display overlay with distinct colors for labels/predictions."""
    if not isinstance(image, Image.Image):
        raise ResearchError("overlay input must be a decoded image")
    overlay = image.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    for group, color, prefix in (
        (ground_truth, GROUND_TRUTH_COLOR, "GT"),
        (predictions, PREDICTION_COLOR, "PRED"),
    ):
        for item in group:
            if not isinstance(item, Mapping):
                raise ResearchError("overlay boxes must be mappings")
            box = _checked_box(item.get("bbox_xyxy_px"), image_size=overlay.size)
            label = str(item.get("class_name", item.get("class", ""))).strip()
            confidence = item.get("confidence")
            if confidence is not None:
                try:
                    score = float(confidence)
                except (TypeError, ValueError, OverflowError) as error:
                    raise ResearchError("prediction confidence must be finite and between 0 and 1") from error
                if not math.isfinite(score) or not 0 <= score <= 1:
                    raise ResearchError("prediction confidence must be finite and between 0 and 1")
                label = f"{label} {score:.2f}".strip()
            caption = f"{prefix} {label}".strip()
            draw.rectangle(box, outline=color, width=3)
            if caption:
                left, top, _, _ = box
                draw.text((left, max(0, top - 12)), caption, fill=color)
    return overlay


def binary_damage_summary(condition_metrics: Mapping[str, Any]) -> dict[str, Any] | None:
    """Collapse the supplied condition confusion matrix into damage-vs-normal counts."""
    damage_classes = {"coating_damage", "mechanical_damage"}
    normal_class = "normal"
    labels = condition_metrics.get("labels")
    if not isinstance(labels, list) or set(labels) != damage_classes | {normal_class}:
        return None
    confusion = condition_metrics.get("confusion_matrix")
    if not isinstance(confusion, Mapping):
        raise ResearchError("condition metrics must include a confusion matrix")
    unretrieved = sum(
        int(confusion[actual].get("unretrieved", 0)) for actual in labels
    )
    true_positive = sum(
        int(confusion[actual][predicted])
        for actual in damage_classes
        for predicted in damage_classes
    )
    false_negative = sum(
        int(confusion[actual][normal_class]) for actual in damage_classes
    )
    false_positive = sum(
        int(confusion[normal_class][predicted]) for predicted in damage_classes
    )
    true_negative = int(confusion[normal_class][normal_class])
    precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": true_positive,
        "fp": false_positive,
        "fn": false_negative,
        "tn": true_negative,
        "unclassified": unretrieved,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def validate_training_plan(
    samples: Sequence[Mapping[str, Any]],
    assignments: Mapping[str, str],
    *,
    target: str,
) -> dict[str, Any]:
    """Validate a human-assigned image-classification holdout; never train here."""
    if target not in {"condition", "object_type"}:
        raise ResearchError("target must be condition or object_type; keep object and condition semantics separate")
    if not samples:
        raise ResearchError("training plan has no samples")
    sample_paths: set[str] = set()
    split_counts: Counter[str] = Counter()
    labels_by_split: dict[str, set[str]] = {"train": set(), "validation": set(), "test": set()}
    hashes_by_split: dict[str, dict[str, str]] = {"train": {}, "validation": {}, "test": {}}
    groups_by_split: dict[str, dict[str, str]] = {"train": {}, "validation": {}, "test": {}}
    normalized_assignment: dict[str, str] = {}
    valid_splits = {"train", "validation", "val", "test", "exclude"}
    for sample in samples:
        path = sample.get("image_path")
        if not isinstance(path, str) or not path:
            raise ResearchError("every sample must have a unique image_path")
        if path in sample_paths:
            raise ResearchError(f"training plan contains duplicate image_path {path!r}")
        sample_paths.add(path)
        assigned = assignments.get(path)
        if not isinstance(assigned, str) or assigned not in valid_splits:
            raise ResearchError("every sample needs an explicit train/validation/test/exclude assignment")
        assigned = "validation" if assigned == "val" else assigned
        normalized_assignment[path] = assigned
        split_counts[assigned] += 1
        if assigned == "exclude":
            continue
        label = sample.get(target)
        if not isinstance(label, str) or not label.strip() or label.casefold() == "unknown":
            raise ResearchError("unknown samples must be excluded from a supervised experiment")
        labels_by_split[assigned].add(label)
        digest = sample.get("sha256")
        if isinstance(digest, str) and digest:
            digest = digest.lower()
            prior_split = next((split for split, seen in hashes_by_split.items() if digest in seen), None)
            if prior_split is not None and prior_split != assigned:
                raise ResearchError(f"exact-image leakage across {prior_split} and {assigned} splits")
            hashes_by_split[assigned][digest] = path
        object_id = sample.get("object_id")
        if isinstance(object_id, str) and object_id:
            # Source folders/types may be inconsistent for repeated filenames;
            # the supplied inventory requires identical IDs to stay grouped globally.
            group = object_id
            prior_split = next((split for split, seen in groups_by_split.items() if group in seen), None)
            if prior_split is not None and prior_split != assigned:
                raise ResearchError(f"object-family leakage across {prior_split} and {assigned} splits")
            groups_by_split[assigned][group] = path
    unknown_assignments = sorted(set(assignments) - sample_paths)
    if unknown_assignments:
        raise ResearchError("assignments contain paths not present in the manifest")
    if not all(split_counts[split] for split in ("train", "validation", "test")):
        raise ResearchError("a supervised experiment requires non-empty train, validation, and test splits")
    warnings = [
        "Image-level spreadsheet labels contain no object bounding boxes; this plan is image classification, not detection.",
        "A sample-level holdout does not prove scene, location, or acquisition-session independence; verify groups with a human.",
        "This validates a reproducible split only; it does not train, download, or claim model accuracy.",
    ]
    missing_classes = {
        split: sorted(labels_by_split["train"] - labels_by_split[split])
        for split in ("validation", "test")
        if labels_by_split["train"] - labels_by_split[split]
    }
    if missing_classes:
        warnings.append(f"Some training classes are absent from held-out splits: {missing_classes}.")
    return {
        "task": "image_classification",
        "target": target,
        "split_counts": {split: split_counts[split] for split in ("train", "validation", "test", "exclude")},
        "classes_by_split": {split: sorted(labels) for split, labels in labels_by_split.items()},
        "missing_training_classes": missing_classes,
        "evaluation_ready": True,
        "assignments": normalized_assignment,
        "warnings": warnings,
        "training_executed": False,
    }
