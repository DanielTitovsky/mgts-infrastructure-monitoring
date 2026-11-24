from __future__ import annotations

import json
import math
import re
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Iterator

import pyarrow as pa
import pyarrow.parquet as parquet
import yaml

from .errors import PipelineError
from .models import Annotation, Sample
from .safeio import ensure_regular_file, image_dimensions, safe_member_name, validate_zip


_SPLITS = {"train": "train", "valid": "val", "val": "val", "validation": "val", "test": "test"}
_SPLIT_PRIORITY = ("train", "val", "test")
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


def normalize_split(split: str) -> str:
    try:
        return _SPLITS[split.lower()]
    except KeyError as exc:
        raise PipelineError(f"unsupported dataset split: {split!r}") from exc


def _finite_number(value: object, context: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PipelineError(f"invalid numeric value in {context}") from exc
    if not math.isfinite(result):
        raise PipelineError(f"non-finite numeric value in {context}")
    return result


def _class_id(value: object, class_count: int, context: str) -> int:
    if isinstance(value, bool):
        raise PipelineError(f"invalid class ID in {context}")
    try:
        numeric = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PipelineError(f"invalid class ID in {context}") from exc
    if not math.isfinite(numeric) or not numeric.is_integer():
        raise PipelineError(f"invalid class ID in {context}")
    class_id = int(numeric)
    if not 0 <= class_id < class_count:
        raise PipelineError(f"class ID {value!r} is outside 0..{class_count - 1} in {context}")
    return class_id


def _reject_invalid_sample(
    rejected_records: list[dict[str, object]] | None,
    *,
    source_path: str,
    split: str,
    reason: str,
    rejected_annotation_count: int,
    strict_invalid: bool,
) -> None:
    message = f"invalid annotation at {source_path}: {reason}"
    if strict_invalid or rejected_records is None:
        raise PipelineError(message)
    rejected_records.append(
        {
            "source_path": source_path,
            "split": split,
            "reason": reason,
            "rejected_annotation_count": rejected_annotation_count,
        }
    )


def parse_yolo_row(row: str, class_count: int) -> tuple[Annotation, str]:
    tokens = row.split()
    if not tokens:
        raise PipelineError("empty YOLO annotation row")
    class_id = _class_id(tokens[0], class_count, "YOLO row")
    coordinates = [_finite_number(value, "YOLO row") for value in tokens[1:]]
    if len(coordinates) == 4:
        x_center, y_center, width, height = coordinates
        values = (x_center, y_center, width, height)
        if not 0 <= x_center <= 1 or not 0 <= y_center <= 1 or width <= 0 or height <= 0:
            raise PipelineError("invalid YOLO bounding-box geometry")
        if width > 1 or height > 1 or x_center - width / 2 < 0 or y_center - height / 2 < 0:
            raise PipelineError("YOLO bounding box is out of bounds")
        if x_center + width / 2 > 1 or y_center + height / 2 > 1:
            raise PipelineError("YOLO bounding box is out of bounds")
        return Annotation(class_id, *values), "bbox"
    if len(coordinates) < 6 or len(coordinates) % 2:
        raise PipelineError("YOLO polygon must contain at least three x/y points")
    xs, ys = coordinates[0::2], coordinates[1::2]
    if any(not 0 <= value <= 1 for value in coordinates):
        raise PipelineError("YOLO polygon is out of bounds")
    left, right, top, bottom = min(xs), max(xs), min(ys), max(ys)
    if right <= left or bottom <= top:
        raise PipelineError("YOLO polygon has zero-area bounds")
    return Annotation(class_id, (left + right) / 2, (top + bottom) / 2, right - left, bottom - top), "polygon_to_bbox"


def parse_coco_box(
    bbox: object, *, width: int, height: int, class_id: int
) -> Annotation:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise PipelineError("COCO bbox must contain x, y, width, height")
    x, y, box_width, box_height = (_finite_number(value, "COCO bbox") for value in bbox)
    if box_width <= 0 or box_height <= 0 or x < 0 or y < 0:
        raise PipelineError("invalid COCO bbox geometry")
    if width <= 0 or height <= 0 or x + box_width > width or y + box_height > height:
        raise PipelineError("COCO bbox is out of bounds")
    return Annotation(
        class_id,
        (x + box_width / 2) / width,
        (y + box_height / 2) / height,
        box_width / width,
        box_height / height,
    )


def parse_xyxy_box(
    bbox: object, *, width: int, height: int, class_id: int
) -> Annotation:
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise PipelineError("XYXY bbox must contain x1, y1, x2, y2")
    x1, y1, x2, y2 = (_finite_number(value, "XYXY bbox") for value in bbox)
    if width <= 0 or height <= 0 or x1 < 0 or y1 < 0 or x2 > width or y2 > height:
        raise PipelineError("XYXY bbox is out of bounds")
    if x2 <= x1 or y2 <= y1:
        raise PipelineError("invalid XYXY bbox geometry")
    return Annotation(
        class_id,
        (x1 + x2) / (2 * width),
        (y1 + y2) / (2 * height),
        (x2 - x1) / width,
        (y2 - y1) / height,
    )


def _names_from_yaml(text: str, expected: list[str] | tuple[str, ...] | None = None) -> list[str]:
    try:
        config = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise PipelineError("invalid data.yaml") from exc
    if not isinstance(config, dict):
        raise PipelineError("data.yaml must contain a mapping")
    raw_names = config.get("names")
    if isinstance(raw_names, dict):
        try:
            names = [str(raw_names[index]) for index in range(len(raw_names))]
        except KeyError as exc:
            raise PipelineError("data.yaml class IDs must be contiguous from zero") from exc
    elif isinstance(raw_names, list):
        names = [str(name) for name in raw_names]
    else:
        raise PipelineError("data.yaml must declare class names")
    if not names or any(not name for name in names):
        raise PipelineError("data.yaml class names cannot be empty")
    if config.get("nc", len(names)) != len(names):
        raise PipelineError("data.yaml nc does not match its names")
    if expected is not None and names != list(expected):
        raise PipelineError("source class names differ from the pinned source manifest")
    return names


def _archive_split_and_name(path: str) -> tuple[str, str, str] | None:
    parts = PurePosixPath(path).parts
    for image_index, part in enumerate(parts):
        if part != "images" or image_index < 1 or image_index + 1 >= len(parts):
            continue
        if parts[image_index - 1].lower() not in _SPLITS:
            continue
        source_split = parts[image_index - 1].lower()
        relative_name = PurePosixPath(*parts[image_index + 1 :]).as_posix()
        if PurePosixPath(relative_name).suffix.lower() in _IMAGE_SUFFIXES:
            return source_split, relative_name, PurePosixPath(path).suffix.lower()
    return None


def _family_for_image(relative_name: str) -> str:
    stem = PurePosixPath(relative_name).stem
    match = re.match(r"^(.*?)_jpg\.rf\.[^.]+$", stem, flags=re.IGNORECASE)
    return match.group(1) if match else stem


def roboflow_family_splits(archive_path: Path) -> dict[str, str]:
    entries = validate_zip(archive_path)
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    for info in entries:
        if info.is_dir():
            continue
        split_and_name = _archive_split_and_name(info.filename)
        if split_and_name:
            split, relative_name, _ = split_and_name
            counts[_family_for_image(relative_name)][normalize_split(split)] += 1
    result: dict[str, str] = {}
    for family_id, by_split in counts.items():
        result[family_id] = sorted(
            by_split,
            key=lambda split: (-by_split[split], _SPLIT_PRIORITY.index(split)),
        )[0]
    return result


def iter_roboflow_samples(
    archive_path: Path,
    expected_classes: list[str] | tuple[str, ...],
    family_splits: dict[str, str] | None = None,
    *,
    rejected_records: list[dict[str, object]] | None = None,
    strict_invalid: bool = False,
) -> Iterator[Sample]:
    entries = validate_zip(archive_path)
    by_name = {info.filename: info for info in entries if not info.is_dir()}
    configs = [name for name in by_name if PurePosixPath(name).name.lower() == "data.yaml"]
    if len(configs) != 1:
        raise PipelineError("Roboflow archive must contain exactly one data.yaml")
    with zipfile.ZipFile(archive_path) as archive:
        class_names = _names_from_yaml(archive.read(configs[0]).decode("utf-8"), expected_classes)
        images: list[tuple[str, str, str, str]] = []
        for name in by_name:
            if not PurePosixPath(name).parts:
                continue
            parsed = _archive_split_and_name(name)
            if parsed:
                source_split, relative_name, _ = parsed
                source_path = PurePosixPath(name)
                image_index = source_path.parts.index("images")
                label_parts = (*source_path.parts[:image_index], "labels", *source_path.parts[image_index + 1 :])
                label_path = PurePosixPath(*label_parts).with_suffix(".txt").as_posix()
                family_id = _family_for_image(relative_name)
                images.append((name, label_path, source_split, family_id))
        if not images:
            raise PipelineError("Roboflow archive contains no split/images files")
        for image_path, label_path, source_split, family_id in sorted(images, key=lambda row: (normalize_split(row[2]), row[0])):
            image = archive.read(image_path)
            width, height, _, _ = image_dimensions(image)
            boxes: list[Annotation] = []
            format_counts: Counter[str] = Counter()
            source_flags: Counter[str] = Counter()
            if label_path in by_name:
                label_text = archive.read(label_path).decode("utf-8-sig")
                first_error: str | None = None
                annotation_count = 0
                for line_number, line in enumerate(label_text.splitlines(), 1):
                    if not line.strip():
                        continue
                    annotation_count += 1
                    try:
                        annotation, annotation_format = parse_yolo_row(line, len(class_names))
                    except PipelineError as exc:
                        if strict_invalid or rejected_records is None:
                            raise PipelineError(f"invalid YOLO row {line_number} in {label_path}: {exc}") from exc
                        first_error = first_error or f"invalid YOLO row {line_number}: {exc}"
                        continue
                    boxes.append(annotation)
                    format_counts[annotation_format] += 1
                if first_error:
                    _reject_invalid_sample(
                        rejected_records,
                        source_path=image_path,
                        split=normalize_split(source_split),
                        reason=first_error,
                        rejected_annotation_count=annotation_count,
                        strict_invalid=strict_invalid,
                    )
                    continue
                if not boxes:
                    source_flags["empty_labels"] = 1
            else:
                source_flags["missing_labels"] = 1
            assigned_split = (family_splits or {}).get(family_id, normalize_split(source_split))
            yield Sample(
                source_path=image_path,
                split=assigned_split,
                image_bytes=image,
                width=width,
                height=height,
                boxes=boxes,
                family_id=family_id,
                format_counts=dict(format_counts),
                source_flags=dict(source_flags),
            )


def iter_ohl_samples(
    archive_path: Path,
    *,
    rejected_records: list[dict[str, object]] | None = None,
    strict_invalid: bool = False,
) -> Iterator[Sample]:
    entries = validate_zip(archive_path)
    by_name = {info.filename: info for info in entries if not info.is_dir()}
    annotation_paths: dict[str, str] = {}
    for name in by_name:
        match = re.fullmatch(
            r"(.+/Dataset/Object Detection/Fold 0)/annotations/(train_fold0|val_fold0)\.json",
            name,
        )
        if match:
            split = "train" if match.group(2).startswith("train") else "val"
            if split in annotation_paths:
                raise PipelineError(f"multiple OHL Fold 0 {split} annotations found")
            annotation_paths[split] = name
    if set(annotation_paths) != {"train", "val"}:
        raise PipelineError("OHL archive needs Fold 0 object-detection train and val COCO files")
    with zipfile.ZipFile(archive_path) as archive:
        documents = {split: json.loads(archive.read(path)) for split, path in annotation_paths.items()}
        categories: list[dict] | None = None
        for split in ("train", "val"):
            document = documents[split]
            current_categories = document.get("categories")
            if not isinstance(current_categories, list) or not current_categories:
                raise PipelineError(f"OHL {split} COCO file has no categories")
            if categories is None:
                categories = sorted(current_categories, key=lambda item: item["id"])
            elif sorted(current_categories, key=lambda item: item["id"]) != categories:
                raise PipelineError("OHL Fold 0 class categories differ between train and val")
        category_map = {category["id"]: index for index, category in enumerate(categories or [])}
        for split in ("train", "val"):
            document = documents[split]
            base = annotation_paths[split].rsplit("/annotations/", 1)[0]
            image_split = "train_fold0" if split == "train" else "val_fold0"
            boxes_by_image: dict[object, list[Annotation]] = defaultdict(list)
            image_ids = {image.get("id") for image in document.get("images", [])}
            if None in image_ids or len(image_ids) != len(document.get("images", [])):
                raise PipelineError(f"OHL {split} COCO image IDs must be unique")
            for row in document.get("annotations", []):
                image_id = row.get("image_id")
                if image_id not in image_ids:
                    raise PipelineError(f"OHL annotation refers to unknown image ID {image_id!r}")
                try:
                    class_id = category_map[row.get("category_id")]
                except KeyError as exc:
                    raise PipelineError("OHL annotation refers to an unknown category") from exc
                # Dimensions are checked against the actual image below.
                boxes_by_image[image_id].append((row, class_id))  # type: ignore[arg-type]
            for image_meta in sorted(document.get("images", []), key=lambda item: str(item.get("file_name"))):
                file_name = safe_member_name(str(image_meta.get("file_name", "")))
                image_path = f"{base}/images/{image_split}/{file_name}"
                if image_path not in by_name:
                    raise PipelineError(f"OHL COCO image is missing from archive: {image_path}")
                image = archive.read(image_path)
                width, height, _, _ = image_dimensions(image)
                if image_meta.get("width") != width or image_meta.get("height") != height:
                    raise PipelineError(f"OHL COCO dimensions do not match image bytes: {image_path}")
                converted: list[Annotation] = []
                first_error: str | None = None
                image_annotations = boxes_by_image[image_meta["id"]]
                for original, class_id in image_annotations:
                    try:
                        converted.append(
                            parse_coco_box(original.get("bbox"), width=width, height=height, class_id=class_id)
                        )
                    except PipelineError as exc:
                        if strict_invalid or rejected_records is None:
                            raise PipelineError(f"invalid COCO annotation in {image_path}: {exc}") from exc
                        first_error = first_error or str(exc)
                if first_error:
                    _reject_invalid_sample(
                        rejected_records,
                        source_path=image_path,
                        split=split,
                        reason=first_error,
                        rejected_annotation_count=len(image_annotations),
                        strict_invalid=strict_invalid,
                    )
                    continue
                yield Sample(image_path, split, image, width, height, converted, format_counts={"coco_xywh": len(converted)})


def iter_yolo_directory_samples(
    source_dir: Path,
    expected_classes: list[str] | tuple[str, ...],
    *,
    rejected_records: list[dict[str, object]] | None = None,
    strict_invalid: bool = False,
) -> Iterator[Sample]:
    if source_dir.is_symlink() or not source_dir.is_dir():
        raise PipelineError(f"expected dataset directory: {source_dir}")
    config_path = source_dir / "data.yaml"
    ensure_regular_file(config_path)
    class_names = _names_from_yaml(config_path.read_text(encoding="utf-8"), expected_classes)
    for path in sorted(source_dir.rglob("*")):
        if path.is_symlink():
            raise PipelineError(f"source directory contains symlink: {path}")
    image_paths = []
    for path in source_dir.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _IMAGE_SUFFIXES:
            continue
        relative = path.relative_to(source_dir)
        parts = relative.parts
        if "images" not in parts:
            continue
        image_index = parts.index("images")
        if image_index < 1 or parts[image_index - 1].lower() not in _SPLITS:
            continue
        image_paths.append(path)
    if not image_paths:
        raise PipelineError("YOLO directory contains no images under split/images")
    image_paths.sort(key=lambda path: (normalize_split(path.relative_to(source_dir).parts[path.relative_to(source_dir).parts.index("images") - 1]), path.as_posix()))
    for image_path in image_paths:
        relative = image_path.relative_to(source_dir)
        parts = relative.parts
        image_index = parts.index("images")
        source_split = parts[image_index - 1].lower()
        label_path = source_dir.joinpath(*parts[:image_index], "labels", *parts[image_index + 1 :]).with_suffix(".txt")
        image = image_path.read_bytes()
        width, height, _, _ = image_dimensions(image)
        boxes: list[Annotation] = []
        format_counts: Counter[str] = Counter()
        source_flags: Counter[str] = Counter()
        if label_path.exists():
            ensure_regular_file(label_path)
            first_error: str | None = None
            annotation_count = 0
            for line_number, line in enumerate(label_path.read_text(encoding="utf-8-sig").splitlines(), 1):
                if not line.strip():
                    continue
                annotation_count += 1
                try:
                    annotation, annotation_format = parse_yolo_row(line, len(class_names))
                except PipelineError as exc:
                    if strict_invalid or rejected_records is None:
                        raise PipelineError(f"invalid YOLO row {line_number} in {label_path}: {exc}") from exc
                    first_error = first_error or f"invalid YOLO row {line_number}: {exc}"
                    continue
                boxes.append(annotation)
                format_counts[annotation_format] += 1
            if first_error:
                _reject_invalid_sample(
                    rejected_records,
                    source_path=relative.as_posix(),
                    split=normalize_split(source_split),
                    reason=first_error,
                    rejected_annotation_count=annotation_count,
                    strict_invalid=strict_invalid,
                )
                continue
            if not boxes:
                source_flags["empty_labels"] = 1
        else:
            source_flags["missing_labels"] = 1
        yield Sample(
            source_path=relative.as_posix(),
            split=normalize_split(source_split),
            image_bytes=image,
            width=width,
            height=height,
            boxes=boxes,
            format_counts=dict(format_counts),
            source_flags=dict(source_flags),
        )


def iter_parquet_samples(
    parquet_path: Path,
    data_format: str,
    split: str,
    class_names: list[str] | tuple[str, ...],
    *,
    quarantine_invalid: bool = False,
    strict_invalid: bool = False,
) -> tuple[Iterator[Sample], list[dict[str, object]]]:
    ensure_regular_file(parquet_path)
    rejects: list[dict[str, object]] = []
    normalized_split = normalize_split(split)

    def generate() -> Iterator[Sample]:
        try:
            reader = parquet.ParquetFile(parquet_path)
        except (OSError, pa.ArrowException) as exc:
            raise PipelineError(f"invalid Parquet file: {parquet_path.name}") from exc
        required = {"image", "objects"} if data_format == "streetlevel" else {"image", "bboxes", "labels"}
        if data_format not in {"streetlevel", "powerline"} or not required.issubset(reader.schema_arrow.names):
            raise PipelineError(f"unexpected {data_format} Parquet schema in {parquet_path.name}")
        columns = [name for name in ("image", "objects", "bboxes", "labels", "width", "height", "image_id") if name in reader.schema_arrow.names]
        row_index = 0
        for batch in reader.iter_batches(batch_size=64, columns=columns):
            for row in batch.to_pylist():
                current_index = row_index
                row_index += 1
                source_path = f"{parquet_path.name}#row-{current_index}"
                image_struct = row.get("image") or {}
                image = image_struct.get("bytes") if isinstance(image_struct, dict) else None
                if not isinstance(image, (bytes, bytearray)) or not image:
                    raise PipelineError(f"missing embedded image bytes at {source_path}")
                image = bytes(image)
                decoded_width, decoded_height, _, _ = image_dimensions(image)
                width = row.get("width", decoded_width)
                height = row.get("height", decoded_height)
                if not isinstance(width, int) or not isinstance(height, int) or width != decoded_width or height != decoded_height:
                    raise PipelineError(f"Parquet image dimensions do not match bytes at {source_path}")
                boxes: list[Annotation] = []
                try:
                    if data_format == "streetlevel":
                        objects = row.get("objects") or {}
                        xywh_boxes = objects.get("bbox", [])
                        categories = objects.get("category", [])
                        if len(xywh_boxes) != len(categories):
                            raise PipelineError("bbox/category count mismatch")
                        for bbox, class_value in zip(xywh_boxes, categories, strict=True):
                            class_id = _class_id(class_value, len(class_names), "streetlevel category")
                            boxes.append(parse_coco_box(bbox, width=width, height=height, class_id=class_id))
                        annotation_format = "coco_xywh"
                    else:
                        xyxy_boxes = row.get("bboxes", [])
                        labels = row.get("labels", [])
                        if len(xyxy_boxes) != len(labels):
                            raise PipelineError("bbox/label count mismatch")
                        for bbox, class_value in zip(xyxy_boxes, labels, strict=True):
                            class_id = _class_id(class_value, len(class_names), "powerline label")
                            boxes.append(parse_xyxy_box(bbox, width=width, height=height, class_id=class_id))
                        annotation_format = "xyxy"
                except PipelineError as exc:
                    if strict_invalid or (data_format == "powerline" and not quarantine_invalid):
                        raise PipelineError(f"invalid annotation at {source_path}: {exc}") from exc
                    rejects.append(
                        {
                            "source_path": source_path,
                            "split": normalized_split,
                            "reason": str(exc),
                            "rejected_annotation_count": max(
                                len(row.get("objects", {}).get("bbox", []))
                                if data_format == "streetlevel" and isinstance(row.get("objects"), dict)
                                else 0,
                                len(row.get("bboxes", [])),
                                len(row.get("labels", [])),
                            ),
                        }
                    )
                    continue
                yield Sample(
                    source_path=source_path,
                    split=normalized_split,
                    image_bytes=image,
                    width=width,
                    height=height,
                    boxes=boxes,
                    format_counts={annotation_format: len(boxes)},
                )

    return generate(), rejects
