"""Exact-identity joins and bounded review helpers for organizer photos."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any

from PIL import Image, ImageDraw, UnidentifiedImageError


MAX_ARTIFACT_BYTES = 5_000_000
MAX_AUDIT_ROWS = 5_000
MAX_BOXES_PER_SAMPLE = 500
METHODS = ("knn_k5", "linear_ridge", "supervised_mlp")
OBJECT_TYPES = {"РЩ", "ТКШ", "unknown"}
CONDITIONS = {"normal", "mechanical_damage", "coating_damage", "unknown"}
DAMAGED_CONDITIONS = {"mechanical_damage", "coating_damage"}


class AuditDataError(ValueError):
    """A report, join, or proposed box does not match the organizer data."""


def _identity(item: Mapping[str, Any], *, label: str) -> tuple[str, str]:
    image_path, digest = item.get("image_path"), item.get("sha256")
    if not isinstance(image_path, str) or not image_path or "\\" in image_path:
        raise AuditDataError(f"{label} has an invalid image_path")
    relative = PurePosixPath(image_path)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in image_path.split("/")):
        raise AuditDataError(f"{label} image_path must be a safe relative path")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest.lower())
    ):
        raise AuditDataError(f"{label} has an invalid SHA-256")
    return image_path, digest.lower()


def _unique_map(items: Sequence[Mapping[str, Any]], *, label: str) -> dict[tuple[str, str], Mapping[str, Any]]:
    if len(items) > MAX_AUDIT_ROWS:
        raise AuditDataError(f"{label} exceeds the {MAX_AUDIT_ROWS}-row limit")
    result: dict[tuple[str, str], Mapping[str, Any]] = {}
    seen_paths: set[str] = set()
    for position, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise AuditDataError(f"{label} row {position} must be an object")
        key = _identity(item, label=f"{label} row {position}")
        if key in result or key[0] in seen_paths:
            raise AuditDataError(f"{label} contains a duplicate photo identity")
        result[key] = item
        seen_paths.add(key[0])
    return result


def _valid_label(item: Mapping[str, Any], *, label: str) -> tuple[str, str]:
    object_type, condition = item.get("object_type"), item.get("condition")
    if (
        not isinstance(object_type, str)
        or object_type not in OBJECT_TYPES
        or not isinstance(condition, str)
        or condition not in CONDITIONS
    ):
        raise AuditDataError(f"{label} has an unsupported organizer label")
    return object_type, condition


def _finite_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AuditDataError(f"{label} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise AuditDataError(f"{label} must be finite")
    return number


def _box_rows(
    manifest: Mapping[str, Any],
    report: Mapping[str, Any] | None,
    *,
    manifest_sha256: str | None,
) -> dict[tuple[str, str], list[dict[str, Any]]]:
    if report is None:
        return {}
    if not isinstance(manifest_sha256, str) or len(manifest_sha256) != 64:
        raise AuditDataError("box report validation requires the current manifest SHA-256")
    if report.get("schema_version") != 1:
        raise AuditDataError("unsupported box report schema_version")
    if report.get("manifest_sha256") != manifest_sha256:
        raise AuditDataError("box report was produced for a different manifest")
    model = report.get("model")
    if not isinstance(model, Mapping):
        raise AuditDataError("box report model metadata must be an object")
    if any(not isinstance(model.get(key), str) or not model[key].strip() for key in ("id", "revision")):
        raise AuditDataError("box report must identify its detector model and revision")
    threshold = _finite_number(model.get("threshold"), label="box report threshold")
    if not 0 <= threshold <= 1:
        raise AuditDataError("box report threshold must be between zero and one")

    manifest_rows = manifest.get("samples")
    if not isinstance(manifest_rows, list):
        raise AuditDataError("manifest samples must be a list")
    manifest_by_key = _unique_map(manifest_rows, label="manifest")
    report_rows = report.get("samples")
    if not isinstance(report_rows, list) or len(report_rows) > MAX_AUDIT_ROWS:
        raise AuditDataError("box report samples must be a bounded list")
    indexed = _unique_map(report_rows, label="box report")
    result: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for key, report_sample in indexed.items():
        source = manifest_by_key.get(key)
        if source is None:
            raise AuditDataError("box report photo identity is not in the current manifest")
        width, height = report_sample.get("width"), report_sample.get("height")
        source_width, source_height = source.get("width"), source.get("height")
        if (
            isinstance(width, bool)
            or isinstance(height, bool)
            or not isinstance(width, int)
            or not isinstance(height, int)
            or width < 1
            or height < 1
            or (source_width is not None and width != source_width)
            or (source_height is not None and height != source_height)
        ):
            raise AuditDataError("box report dimensions do not match the manifest photo")
        raw_boxes = report_sample.get("boxes")
        if not isinstance(raw_boxes, list) or len(raw_boxes) > MAX_BOXES_PER_SAMPLE:
            raise AuditDataError("box report boxes must be a bounded list")
        status = report_sample.get("detection_status")
        if status not in {"detected", "not_detected"}:
            raise AuditDataError("box report sample has an invalid detection_status")
        if bool(raw_boxes) != (status == "detected"):
            raise AuditDataError("box report detection_status contradicts its box list")
        boxes: list[dict[str, Any]] = []
        for position, box in enumerate(raw_boxes):
            if not isinstance(box, Mapping):
                raise AuditDataError(f"box report box {position} must be an object")
            label = box.get("label")
            if not isinstance(label, str) or not label.strip():
                raise AuditDataError(f"box report box {position} has an invalid label")
            score = _finite_number(box.get("score"), label="box score")
            coordinates = box.get("xyxy")
            if not isinstance(coordinates, list) or len(coordinates) != 4:
                raise AuditDataError(f"box report box {position} xyxy must have four coordinates")
            x1, y1, x2, y2 = (
                _finite_number(value, label="box coordinate") for value in coordinates
            )
            if not 0 <= score <= 1 or not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
                raise AuditDataError(f"box report box {position} is outside image bounds")
            boxes.append({"label": label, "score": score, "xyxy": [x1, y1, x2, y2]})
        result[key] = boxes
    return result


def _validated_oof_rows(
    index_records: Mapping[tuple[str, str], Mapping[str, Any]],
    oof: Mapping[str, Any] | None,
    *,
    index_sha256: str | None,
) -> dict[tuple[str, str], Mapping[str, Any]]:
    if oof is None:
        return {}
    if not index_records:
        raise AuditDataError("OOF predictions cannot be joined without the reference index")
    if (
        oof.get("schema_version") != 1
        or oof.get("kind") != "mgts-cabinet-cross-fitted-predictions"
        or oof.get("join_key") != ["image_path", "sha256"]
        or oof.get("group_isolation") != "object_id_or_exact_sha256"
        or oof.get("independent_test_set") is not False
    ):
        raise AuditDataError("unsupported or non-grouped OOF prediction artifact")
    rows = oof.get("rows")
    if (
        not isinstance(rows, list)
        or len(rows) != len(index_records)
        or oof.get("row_count") != len(rows)
    ):
        raise AuditDataError("OOF predictions must cover every labeled index record exactly once")
    source_index = oof.get("source_index")
    if not isinstance(source_index, Mapping) or source_index.get("record_count") != len(index_records):
        raise AuditDataError("OOF source index record count does not match the current index")
    source_digest = source_index.get("sha256")
    if (
        not isinstance(source_digest, str)
        or len(source_digest) != 64
        or any(character not in "0123456789abcdef" for character in source_digest.lower())
    ):
        raise AuditDataError("OOF artifact is missing the reference-index SHA-256")
    if index_sha256 is not None and source_digest != index_sha256:
        raise AuditDataError("OOF predictions were produced from a different reference index")

    result = _unique_map(rows, label="OOF predictions")
    if set(result) != set(index_records):
        raise AuditDataError("OOF predictions do not match the index photo identities")
    group_sizes = Counter(record.get("group_id") for record in index_records.values())
    for key, row in result.items():
        record = index_records[key]
        if (
            row.get("object_id") != record.get("object_id")
            or row.get("group_id") != record.get("group_id")
            or row.get("excluded_group_id") != record.get("group_id")
        ):
            raise AuditDataError("OOF row identity or held-out group does not match the index")
        true = row.get("true")
        if not isinstance(true, Mapping) or _valid_label(true, label="OOF truth") != _valid_label(
            record, label="index record"
        ):
            raise AuditDataError("OOF truth does not match the reference index labels")
        for method in METHODS:
            prediction = row.get("predicted", {}).get(method) if isinstance(row.get("predicted"), Mapping) else None
            if not isinstance(prediction, Mapping):
                raise AuditDataError(f"OOF row is missing the {method} prediction")
            object_type, condition = prediction.get("object_type"), prediction.get("condition")
            if object_type not in {*OBJECT_TYPES, None} or condition not in {*CONDITIONS, None}:
                raise AuditDataError(f"OOF {method} prediction has an unsupported label")
        for count_key in ("ridge_training_example_count", "mlp_training_example_count"):
            count = row.get(count_key)
            expected_count = len(index_records) - group_sizes[record["group_id"]]
            if isinstance(count, bool) or not isinstance(count, int) or count != expected_count:
                raise AuditDataError(f"OOF fold has an invalid {count_key} for its held-out group")
    return result


def build_audit_rows(
    manifest: Mapping[str, Any],
    index: Mapping[str, Any] | None,
    oof: Mapping[str, Any] | None,
    *,
    box_report: Mapping[str, Any] | None = None,
    manifest_sha256: str | None = None,
    index_sha256: str | None = None,
) -> list[dict[str, Any]]:
    """Join all manifest photos to grouped OOF data and optional proposal boxes."""
    if not isinstance(manifest, Mapping) or manifest.get("schema_version") != 1:
        raise AuditDataError("unsupported organizer manifest")
    samples = manifest.get("samples")
    if not isinstance(samples, list) or len(samples) > MAX_AUDIT_ROWS:
        raise AuditDataError("manifest samples must be a bounded list")
    manifest_by_key = _unique_map(samples, label="manifest")

    index_by_key: dict[tuple[str, str], Mapping[str, Any]] = {}
    if index is not None:
        records = index.get("records")
        if not isinstance(records, list):
            raise AuditDataError("reference index records must be a list")
        index_by_key = _unique_map(records, label="reference index")
        for key, record in index_by_key.items():
            sample = manifest_by_key.get(key)
            if sample is None:
                raise AuditDataError("reference index photo identity is not in the current manifest")
            if record.get("object_id") != sample.get("object_id"):
                raise AuditDataError("reference index object_id does not match the manifest")
            if _valid_label(record, label="reference index") != _valid_label(sample, label="manifest"):
                raise AuditDataError("reference index labels do not match the manifest")
            if not isinstance(record.get("group_id"), str) or not record["group_id"]:
                raise AuditDataError("reference index record is missing its group_id")

    oof_by_key = _validated_oof_rows(index_by_key, oof, index_sha256=index_sha256)
    box_by_key = _box_rows(manifest, box_report, manifest_sha256=manifest_sha256)
    rows: list[dict[str, Any]] = []
    for sample in samples:
        key = _identity(sample, label="manifest sample")
        index_record = index_by_key.get(key)
        oof_row = oof_by_key.get(key)
        known_labels = _valid_label(sample, label="manifest")
        excluded = known_labels[0] == "unknown" or known_labels[1] == "unknown"
        box_values = box_by_key.get(key)
        if box_report is None or key not in box_by_key:
            box_status = "not_run"
            box_values = []
        elif box_values:
            box_status = "proposals"
        else:
            box_status = "empty"
        predictions = {
            method: oof_row["predicted"][method] if oof_row is not None else None
            for method in METHODS
        }
        rows.append(
            {
                "sample": dict(sample),
                "identity": key,
                "index_record": index_record,
                "group_id": index_record.get("group_id") if index_record else None,
                "true": {
                    "object_type": known_labels[0],
                    "condition": known_labels[1],
                },
                "predictions": predictions,
                "false_normal_methods": [
                    method
                    for method, prediction in predictions.items()
                    if known_labels[1] in DAMAGED_CONDITIONS
                    and prediction is not None
                    and prediction.get("condition") == "normal"
                ],
                "evaluation_status": "excluded" if excluded else "evaluated" if oof_row else "unavailable",
                "excluded_group_id": oof_row.get("excluded_group_id") if oof_row else None,
                "box_status": box_status,
                "boxes": box_values or [],
            }
        )
    return rows


def load_optional_json(path: str | Path, *, label: str) -> dict[str, Any] | None:
    """Read a bounded, regular JSON artifact; a missing optional file is not an error."""
    artifact = Path(path).expanduser()
    if artifact.is_symlink():
        raise AuditDataError(f"{label} cannot be a symlink")
    if not artifact.exists():
        return None
    if not artifact.is_file():
        raise AuditDataError(f"{label} must be a regular file")
    try:
        if artifact.stat().st_size > MAX_ARTIFACT_BYTES:
            raise AuditDataError(f"{label} exceeds the {MAX_ARTIFACT_BYTES} byte limit")
        parsed = json.loads(artifact.read_text(encoding="utf-8"))
    except AuditDataError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AuditDataError(f"cannot read {label}: {type(error).__name__}") from error
    if not isinstance(parsed, dict):
        raise AuditDataError(f"{label} must contain a JSON object")
    return parsed


def sha256_file(path: str | Path) -> str:
    """Hash a local artifact without reading it all into memory."""
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
    except OSError as error:
        raise AuditDataError("cannot hash the required review artifact") from error
    return digest.hexdigest()


def proposal_preview_bytes(
    image: Image.Image,
    boxes: Sequence[Mapping[str, Any]],
    *,
    expected_size: tuple[int, int],
    max_edge: int = 360,
    max_bytes: int = 35_000,
) -> bytes:
    """Overlay proposal boxes in original coordinates, then encode a thumbnail."""
    if not isinstance(image, Image.Image):
        raise AuditDataError("proposal preview requires a decoded photo")
    if image.size != expected_size:
        raise AuditDataError("decoded photo dimensions do not match the detector report dimensions")
    if (
        isinstance(max_edge, bool)
        or not isinstance(max_edge, int)
        or max_edge < 1
        or isinstance(max_bytes, bool)
        or not isinstance(max_bytes, int)
        or max_bytes < 1
    ):
        raise AuditDataError("preview limits must be positive integers")
    rendered = image.copy().convert("RGB")
    draw = ImageDraw.Draw(rendered)
    for box in boxes:
        x1, y1, x2, y2 = box["xyxy"]
        draw.rectangle((x1, y1, x2, y2), outline=(180, 32, 24), width=max(2, rendered.width // 500))
        caption = f"{box['label']} {box['score']:.2f}"
        draw.text((x1, max(0, y1 - 14)), caption, fill=(180, 32, 24), stroke_width=1, stroke_fill="white")
    edge = max_edge
    while True:
        preview = rendered.copy()
        preview.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        buffer = BytesIO()
        preview.save(buffer, format="JPEG", quality=82, optimize=True)
        encoded = buffer.getvalue()
        if len(encoded) <= max_bytes:
            return encoded
        if edge <= 128:
            raise AuditDataError("proposal thumbnail cannot fit within the requested byte limit")
        edge = max(128, edge * 3 // 4)


def _per_class_metrics(
    labels: list[str], actual: list[str], predicted: list[str | None]
) -> dict[str, Any]:
    matrix = {label: {column: 0 for column in labels + ["не вычислено"]} for label in labels}
    for true_label, predicted_label in zip(actual, predicted):
        matrix[true_label][predicted_label or "не вычислено"] += 1
    per_class: dict[str, dict[str, Any]] = {}
    f1_scores: list[float] = []
    for label in labels:
        tp = matrix[label][label]
        support = sum(matrix[label].values())
        fp = sum(matrix[other][label] for other in labels if other != label)
        fn = support - tp
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / support if support else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        f1_scores.append(f1)
        per_class[label] = {
            "support": support,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": len(actual) - tp - fp - fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    covered = sum(label is not None for label in predicted)
    correct = sum(true == guess for true, guess in zip(actual, predicted))
    return {
        "count": len(actual),
        "coverage": covered / len(actual) if actual else 0.0,
        "covered_count": covered,
        "correct": correct,
        "accuracy": correct / len(actual) if actual else 0.0,
        "macro_f1": sum(f1_scores) / len(f1_scores) if f1_scores else 0.0,
        "labels": labels,
        "confusion_matrix": matrix,
        "per_class": per_class,
    }


def oof_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Summarize grouped OOF predictions; unknown organizer photos stay out."""
    evaluated = [row for row in rows if row.get("evaluation_status") == "evaluated"]
    if not evaluated:
        return None
    labels_by_target = {
        "object_type": ["РЩ", "ТКШ"],
        "condition": ["coating_damage", "mechanical_damage", "normal"],
    }
    result: dict[str, Any] = {}
    for method in METHODS:
        method_metrics: dict[str, Any] = {}
        for target, labels in labels_by_target.items():
            actual = [str(row["true"][target]) for row in evaluated]
            predicted = [
                (row["predictions"][method] or {}).get(target)
                for row in evaluated
            ]
            method_metrics[target] = _per_class_metrics(labels, actual, predicted)
        binary_actual = [
            "any_damage" if row["true"]["condition"] in DAMAGED_CONDITIONS else "normal"
            for row in evaluated
        ]
        binary_predicted = [
            None
            if (row["predictions"][method] or {}).get("condition") is None
            else "any_damage"
            if (row["predictions"][method] or {}).get("condition") in DAMAGED_CONDITIONS
            else "normal"
            for row in evaluated
        ]
        covered = [
            (actual, predicted)
            for actual, predicted in zip(binary_actual, binary_predicted)
            if predicted is not None
        ]
        tp = sum(actual == predicted == "any_damage" for actual, predicted in covered)
        fp = sum(actual == "normal" and predicted == "any_damage" for actual, predicted in covered)
        fn = sum(actual == "any_damage" and predicted == "normal" for actual, predicted in covered)
        tn = sum(actual == predicted == "normal" for actual, predicted in covered)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        method_metrics["condition_binary_damage_vs_normal"] = {
            "count": len(evaluated),
            "coverage": len(covered) / len(evaluated),
            "covered_count": len(covered),
            "abstained_count": len(evaluated) - len(covered),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "precision": precision,
            "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        }
        method_metrics["false_normal"] = sum(
            row["true"]["condition"] in DAMAGED_CONDITIONS
            and (row["predictions"][method] or {}).get("condition") == "normal"
            for row in evaluated
        )
        result[method] = method_metrics
    result["evaluated_count"] = len(evaluated)
    result["group_count"] = len({row.get("group_id") for row in evaluated})
    return result
