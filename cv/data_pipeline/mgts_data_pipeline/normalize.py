from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
from collections import Counter
from pathlib import Path
from typing import Iterable

import yaml

from .adapters import normalize_split, parse_yolo_row
from .errors import PipelineError
from .models import Annotation, Sample
from .safeio import IMAGE_EXTENSIONS, hash_bytes, image_dimensions


def _number(value: float) -> str:
    return repr(float(value))


def _annotation_line(annotation: Annotation) -> str:
    return " ".join(
        (
            str(annotation.class_id),
            _number(annotation.x_center),
            _number(annotation.y_center),
            _number(annotation.width),
            _number(annotation.height),
        )
    )


def _validate_annotation(annotation: Annotation, class_count: int, source_path: str) -> None:
    values = (annotation.x_center, annotation.y_center, annotation.width, annotation.height)
    if not 0 <= annotation.class_id < class_count:
        raise PipelineError(f"class ID out of bounds in {source_path}")
    if not all(math.isfinite(value) for value in values):
        raise PipelineError(f"non-finite annotation in {source_path}")
    x_center, y_center, width, height = values
    if width <= 0 or height <= 0:
        raise PipelineError(f"annotation has non-positive area in {source_path}")
    if x_center < 0 or y_center < 0 or x_center > 1 or y_center > 1:
        raise PipelineError(f"annotation center is out of bounds in {source_path}")
    if width > 1 or height > 1 or x_center - width / 2 < 0 or y_center - height / 2 < 0:
        raise PipelineError(f"annotation is out of bounds in {source_path}")
    if x_center + width / 2 > 1 or y_center + height / 2 > 1:
        raise PipelineError(f"annotation is out of bounds in {source_path}")


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def normalize_records(
    source_id: str,
    class_names: list[str] | tuple[str, ...],
    samples: Iterable[Sample],
    output_dir: Path,
    *,
    source_metadata: dict[str, object] | None = None,
    rejected_records: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if not class_names or any(not name.strip() for name in class_names):
        raise PipelineError("at least one non-empty class name is required")
    if output_dir.exists() or output_dir.is_symlink():
        raise PipelineError(f"output already exists; refusing overwrite: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = Path(tempfile.mkdtemp(prefix=f".{output_dir.name}.tmp-", dir=output_dir.parent))
    counts: Counter[str] = Counter()
    images_by_split: Counter[str] = Counter()
    annotations_by_class: Counter[int] = Counter()
    formats: Counter[str] = Counter()
    flags: Counter[str] = Counter()
    orientations: Counter[str] = Counter()
    seen_images: dict[str, tuple[str, str, str]] = {}
    written_sources: list[dict[str, object]] = []
    removed_duplicates: list[dict[str, object]] = []
    try:
        for sample in samples:
            split = normalize_split(sample.split)
            width, height, image_format, orientation = image_dimensions(sample.image_bytes)
            if (width, height) != (sample.width, sample.height):
                raise PipelineError(f"declared image dimensions differ from image bytes: {sample.source_path}")
            for annotation in sample.boxes:
                _validate_annotation(annotation, len(class_names), sample.source_path)
            lines = sorted(_annotation_line(annotation) for annotation in sample.boxes)
            annotation_hash = hash_bytes("\n".join(lines).encode("utf-8"))
            image_hash = hash_bytes(sample.image_bytes)
            extension = IMAGE_EXTENSIONS[image_format]
            filename = f"{image_hash}{extension}"
            if image_hash in seen_images:
                prior_annotation_hash, prior_split, prior_filename = seen_images[image_hash]
                if prior_annotation_hash != annotation_hash:
                    raise PipelineError(
                        f"exact duplicate image has conflicting labels: {sample.source_path} and {prior_filename}"
                    )
                counts["exact_duplicates_removed"] += 1
                counts[f"duplicates_removed_from_{split}"] += 1
                if prior_split != split:
                    counts["exact_duplicates_cross_split"] += 1
                removed_duplicates.append(
                    {
                        "source_path": sample.source_path,
                        "source_split": sample.split,
                        "kept_file": prior_filename,
                        "kept_split": prior_split,
                        "sha256": image_hash,
                    }
                )
                continue
            seen_images[image_hash] = (annotation_hash, split, filename)
            image_dir = temp_dir / "images" / split
            label_dir = temp_dir / "labels" / split
            image_dir.mkdir(parents=True, exist_ok=True)
            label_dir.mkdir(parents=True, exist_ok=True)
            (image_dir / filename).write_bytes(sample.image_bytes)
            (label_dir / f"{image_hash}.txt").write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            counts["images_written"] += 1
            counts["label_files_written"] += 1
            counts["annotations_written"] += len(sample.boxes)
            images_by_split[split] += 1
            annotations_by_class.update(annotation.class_id for annotation in sample.boxes)
            formats.update(sample.format_counts)
            flags.update(sample.source_flags)
            orientations[str(orientation or 1)] += 1
            written_sources.append(
                {
                    "source_path": sample.source_path,
                    "source_split": sample.split,
                    "output_split": split,
                    "output_image": f"images/{split}/{filename}",
                    "sha256": image_hash,
                    "annotation_count": len(sample.boxes),
                    "family_id": sample.family_id,
                    "annotation_formats": dict(sorted(sample.format_counts.items())),
                    "exif_orientation": orientation,
                }
            )
        if not counts["images_written"]:
            rejected_count = len(rejected_records or [])
            raise PipelineError(
                f"source {source_id!r} contains no valid images after rejecting {rejected_count} records"
            )

        split_config = {"train": "images/train", "nc": len(class_names), "names": list(class_names)}
        if images_by_split["val"]:
            split_config["val"] = "images/val"
        if images_by_split["test"]:
            split_config["test"] = "images/test"
        (temp_dir / "data.yaml").write_text(
            yaml.safe_dump(split_config, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        (temp_dir / "samples.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in written_sources),
            encoding="utf-8",
        )
        (temp_dir / "deduplicated.jsonl").write_text(
            "".join(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n" for row in removed_duplicates),
            encoding="utf-8",
        )
        if rejected_records:
            ordered_rejects = sorted(rejected_records, key=lambda row: str(row.get("source_path", "")))
            _write_json(temp_dir / "rejects.json", ordered_rejects)
        rejected_annotation_count = sum(
            int(item.get("rejected_annotation_count", 0)) for item in (rejected_records or [])
        )
        evaluation_missing = [split for split in ("val", "test") if not images_by_split[split]]
        report: dict[str, object] = {
            "schema_version": 1,
            "source_id": source_id,
            "source_metadata": source_metadata or {},
            "class_mapping": [
                {"source_class_id": index, "source_class_name": name, "output_class_id": index, "output_class_name": name}
                for index, name in enumerate(class_names)
            ],
            "counts": {
                **dict(sorted(counts.items())),
                "images_by_split": dict(sorted(images_by_split.items())),
                "annotations_by_class_id": {str(key): value for key, value in sorted(annotations_by_class.items())},
                "annotation_formats": dict(sorted(formats.items())),
                "source_flags": dict(sorted(flags.items())),
                "exif_orientation_counts": dict(sorted(orientations.items())),
                "rejected_records": len(rejected_records or []),
                "rejected_annotations": rejected_annotation_count,
            },
            "rejected_records": len(rejected_records or []),
            "rejected_annotations": rejected_annotation_count,
            "conversion": {
                "coordinates": "normalized YOLO xywh",
                "polygon_to_bbox": "explicit enclosing axis-aligned bounds; see annotation_formats count",
                "images": "original encoded image bytes copied unchanged; no EXIF transpose or re-encoding",
                "exact_duplicate_policy": "same SHA-256 and same normalized annotations keep first deterministic record; conflicting labels fail",
            },
            "evaluation_ready": not evaluation_missing,
            "evaluation_missing_splits": evaluation_missing,
            "scene_independence_claim": False,
        }
        _write_json(temp_dir / "SOURCE.json", report)
        validation = validate_dataset(temp_dir)
        if not validation["valid"]:
            raise PipelineError("normalization output failed validation: " + "; ".join(validation["errors"][:5]))
        if output_dir.exists() or output_dir.is_symlink():
            raise PipelineError(f"output appeared during normalization; refusing overwrite: {output_dir}")
        os.rename(temp_dir, output_dir)
        return report
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def validate_dataset(dataset_dir: Path) -> dict[str, object]:
    errors: list[str] = []
    if dataset_dir.is_symlink() or not dataset_dir.is_dir():
        return {"valid": False, "image_count": 0, "annotation_count": 0, "errors": ["dataset directory is missing or unsafe"]}
    try:
        config = yaml.safe_load((dataset_dir / "data.yaml").read_text(encoding="utf-8"))
        manifest = json.loads((dataset_dir / "SOURCE.json").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError, json.JSONDecodeError) as exc:
        return {"valid": False, "image_count": 0, "annotation_count": 0, "errors": [f"cannot read data.yaml or SOURCE.json: {type(exc).__name__}"]}
    if not isinstance(config, dict) or not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return {"valid": False, "image_count": 0, "annotation_count": 0, "errors": ["invalid dataset metadata"]}
    names = config.get("names")
    if isinstance(names, dict):
        names = [names.get(index) for index in range(len(names))]
    if not isinstance(names, list) or not names or config.get("nc") != len(names):
        errors.append("data.yaml class names/nc are inconsistent")
        names = []
    if "path" in config or config.get("train") != "images/train":
        errors.append("data.yaml paths must be local relative image paths")
    if manifest.get("class_mapping") and len(manifest["class_mapping"]) != len(names):
        errors.append("SOURCE.json class mapping does not match data.yaml")
    seen_hashes: dict[str, str] = {}
    image_count = 0
    annotation_count = 0
    for split in ("train", "val", "test"):
        image_dir = dataset_dir / "images" / split
        label_dir = dataset_dir / "labels" / split
        if not image_dir.exists():
            if config.get(split) is not None:
                errors.append(f"data.yaml references missing {split} images")
            continue
        if image_dir.is_symlink() or label_dir.is_symlink() or not image_dir.is_dir() or not label_dir.is_dir():
            errors.append(f"unsafe or missing image/label directory for {split}")
            continue
        if config.get(split) != f"images/{split}":
            errors.append(f"data.yaml path for {split} is inconsistent")
        image_files = sorted(path for path in image_dir.iterdir() if path.suffix.lower() in IMAGE_EXTENSIONS.values())
        label_files = {path.stem: path for path in label_dir.glob("*.txt")}
        for image_path in image_files:
            if image_path.is_symlink() or not image_path.is_file():
                errors.append(f"unsafe image file: {image_path.relative_to(dataset_dir)}")
                continue
            try:
                data = image_path.read_bytes()
                image_dimensions(data)
            except (OSError, PipelineError) as exc:
                errors.append(f"invalid image {image_path.relative_to(dataset_dir)}: {exc}")
                continue
            image_hash = hash_bytes(data)
            if image_hash in seen_hashes:
                errors.append(f"exact duplicate image remains in {image_path.relative_to(dataset_dir)}")
            seen_hashes[image_hash] = image_path.relative_to(dataset_dir).as_posix()
            label_path = label_files.pop(image_path.stem, None)
            if label_path is None:
                errors.append(f"missing label file for {image_path.relative_to(dataset_dir)}")
                continue
            if label_path.is_symlink() or not label_path.is_file():
                errors.append(f"unsafe label file: {label_path.relative_to(dataset_dir)}")
                continue
            for line_number, line in enumerate(label_path.read_text(encoding="utf-8").splitlines(), 1):
                if not line.strip():
                    continue
                try:
                    _, row_format = parse_yolo_row(line, len(names))
                    if row_format != "bbox":
                        raise PipelineError("normalized labels must contain boxes only")
                except PipelineError as exc:
                    errors.append(f"invalid label {label_path.relative_to(dataset_dir)}:{line_number}: {exc}")
                    continue
                annotation_count += 1
            image_count += 1
        for label_path in label_files.values():
            errors.append(f"orphan label file: {label_path.relative_to(dataset_dir)}")
    expected_counts = manifest.get("counts", {})
    if isinstance(expected_counts, dict) and expected_counts.get("images_written") != image_count:
        errors.append("SOURCE.json image count does not match files")
    if isinstance(expected_counts, dict) and expected_counts.get("annotations_written") != annotation_count:
        errors.append("SOURCE.json annotation count does not match labels")
    return {
        "valid": not errors,
        "image_count": image_count,
        "annotation_count": annotation_count,
        "errors": errors,
    }
