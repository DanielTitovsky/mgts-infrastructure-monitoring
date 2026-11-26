from __future__ import annotations

import copy

import pytest
from PIL import Image

from mgts_data_pipeline.dataset_review import (
    AuditDataError,
    build_audit_rows,
    proposal_preview_bytes,
)


def _sample(path: str, digest: str, object_id: str, condition: str) -> dict:
    return {
        "image_path": path,
        "sha256": digest * 64,
        "object_id": object_id,
        "object_type": "РЩ",
        "condition": condition,
        "status": "fixture",
        "description": "description",
        "source_folder": "folder",
        "width": 40,
        "height": 30,
    }


def _artifacts() -> tuple[dict, dict, dict]:
    first = _sample("one/cabinet.jpg", "1", "same-stem", "mechanical_damage")
    second = _sample("two/cabinet.jpg", "2", "same-stem", "normal")
    third = _sample("three/known.jpg", "3", "known", "coating_damage")
    unknown = _sample("four/unknown.jpg", "4", "unknown", "unknown")
    manifest = {"schema_version": 1, "samples": [first, second, third, unknown]}

    index_rows = []
    oof_rows = []
    for position, sample in enumerate(manifest["samples"][:3], start=1):
        group_id = f"group-{position}"
        index_rows.append(
            {
                "image_path": sample["image_path"],
                "sha256": sample["sha256"],
                "object_id": sample["object_id"],
                "object_type": sample["object_type"],
                "condition": sample["condition"],
                "group_id": group_id,
                "embedding": [float(position), 1.0],
            }
        )
        predicted = {
            "knn_k5": {"object_type": "РЩ", "condition": "normal"},
            "linear_ridge": {"object_type": "РЩ", "condition": "normal"},
            "supervised_mlp": {"object_type": "РЩ", "condition": "normal"},
        }
        oof_rows.append(
            {
                "image_path": sample["image_path"],
                "sha256": sample["sha256"],
                "object_id": sample["object_id"],
                "group_id": group_id,
                "excluded_group_id": group_id,
                "true": {"object_type": "РЩ", "condition": sample["condition"]},
                "predicted": predicted,
                "ridge_training_example_count": 2,
                "mlp_training_example_count": 2,
            }
        )
    index = {"kind": "mgts-cabinet-reference-index", "records": index_rows}
    oof = {
        "kind": "mgts-cabinet-cross-fitted-predictions",
        "schema_version": 1,
        "join_key": ["image_path", "sha256"],
        "group_isolation": "object_id_or_exact_sha256",
        "independent_test_set": False,
        "row_count": len(oof_rows),
        "source_index": {"record_count": len(index_rows), "sha256": "b" * 64},
        "rows": oof_rows,
    }
    return manifest, index, oof


def _box_report(manifest: dict, *, boxes: list[dict] | None = None) -> dict:
    sample = manifest["samples"][0]
    return {
        "schema_version": 1,
        "manifest_sha256": "a" * 64,
        "model": {"id": "cabinet-board", "revision": "fixture", "threshold": 0.25},
        "samples": [
            {
                "image_path": sample["image_path"],
                "sha256": sample["sha256"],
                "width": 40,
                "height": 30,
                "detection_status": "not_detected" if boxes is None else "detected",
                "boxes": [] if boxes is None else boxes,
            }
        ],
    }


def test_audit_keeps_every_photo_and_joins_oof_by_exact_path_and_digest() -> None:
    manifest, index, oof = _artifacts()

    rows = build_audit_rows(
        manifest,
        index,
        oof,
        manifest_sha256="a" * 64,
    )

    assert len(rows) == 4
    assert [row["sample"]["image_path"] for row in rows[:2]] == [
        "one/cabinet.jpg",
        "two/cabinet.jpg",
    ]
    assert rows[0]["predictions"]["knn_k5"]["condition"] == "normal"
    assert rows[1]["predictions"]["knn_k5"]["condition"] == "normal"
    assert rows[3]["evaluation_status"] == "excluded"
    assert rows[3]["predictions"] == {
        "knn_k5": None,
        "linear_ridge": None,
        "supervised_mlp": None,
    }


def test_missing_oof_never_substitutes_knn_for_mlp() -> None:
    manifest, index, _oof = _artifacts()

    rows = build_audit_rows(manifest, index, None, manifest_sha256="a" * 64)

    assert rows[0]["predictions"]["knn_k5"] is None
    assert rows[0]["predictions"]["supervised_mlp"] is None
    assert rows[0]["evaluation_status"] == "unavailable"


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("excluded_group_id", "another-group"),
        ("group_id", "another-group"),
        ("object_id", "wrong-id"),
    ],
)
def test_invalid_oof_identity_or_group_fold_fails_closed(field: str, replacement: str) -> None:
    manifest, index, oof = _artifacts()
    invalid = copy.deepcopy(oof)
    invalid["rows"][0][field] = replacement

    with pytest.raises(AuditDataError):
        build_audit_rows(manifest, index, invalid, manifest_sha256="a" * 64)


def test_audit_requires_exact_index_and_oof_coverage_and_labels() -> None:
    manifest, index, oof = _artifacts()
    invalid = copy.deepcopy(oof)
    invalid["rows"][0]["sha256"] = "f" * 64

    with pytest.raises(AuditDataError):
        build_audit_rows(manifest, index, invalid, manifest_sha256="a" * 64)

    invalid = copy.deepcopy(oof)
    invalid["rows"][0]["mlp_training_example_count"] = 1
    with pytest.raises(AuditDataError, match="held-out group"):
        build_audit_rows(manifest, index, invalid, manifest_sha256="a" * 64)


def test_grouped_oof_metrics_keep_false_normal_counts_and_known_coverage() -> None:
    from mgts_data_pipeline.dataset_review import oof_metrics

    manifest, index, oof = _artifacts()
    rows = build_audit_rows(manifest, index, oof, manifest_sha256="a" * 64)

    metrics = oof_metrics(rows)

    assert metrics is not None
    assert metrics["evaluated_count"] == 3
    assert metrics["group_count"] == 3
    assert metrics["knn_k5"]["condition_binary_damage_vs_normal"]["count"] == 3
    assert metrics["knn_k5"]["false_normal"] == 2
    assert metrics["knn_k5"]["condition"]["confusion_matrix"]["normal"]["не вычислено"] == 0

    invalid = copy.deepcopy(oof)
    invalid["rows"][1]["true"]["condition"] = "coating_damage"
    with pytest.raises(AuditDataError):
        build_audit_rows(manifest, index, invalid, manifest_sha256="a" * 64)


def test_box_report_distinguishes_not_run_empty_and_positive_proposals() -> None:
    manifest, index, oof = _artifacts()
    missing = build_audit_rows(manifest, index, oof, manifest_sha256="a" * 64)
    empty = build_audit_rows(
        manifest,
        index,
        oof,
        box_report=_box_report(manifest),
        manifest_sha256="a" * 64,
    )
    found = build_audit_rows(
        manifest,
        index,
        oof,
        box_report=_box_report(
            manifest,
            boxes=[{"label": "cabinet", "score": 0.9, "xyxy": [1, 2, 20, 25]}],
        ),
        manifest_sha256="a" * 64,
    )

    assert missing[0]["box_status"] == "not_run"
    assert empty[0]["box_status"] == "empty"
    assert found[0]["box_status"] == "proposals"
    assert found[0]["boxes"][0]["xyxy"] == [1.0, 2.0, 20.0, 25.0]
    assert empty[1]["box_status"] == "not_run"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda report: report.update(manifest_sha256="b" * 64),
        lambda report: report["samples"][0].update(sha256="b" * 64),
        lambda report: report["samples"][0].update(width=41),
        lambda report: report["samples"][0].update(
            boxes=[{"label": "cabinet", "score": 0.9, "xyxy": [1, 2, 41, 25]}]
        ),
    ],
)
def test_invalid_box_provenance_identity_dimensions_or_bounds_fails_closed(mutate) -> None:
    manifest, index, oof = _artifacts()
    report = _box_report(manifest)
    mutate(report)

    with pytest.raises(AuditDataError):
        build_audit_rows(
            manifest,
            index,
            oof,
            box_report=report,
            manifest_sha256="a" * 64,
        )


def test_proposal_preview_rejects_mismatched_photo_dimensions() -> None:
    image = Image.new("RGB", (40, 30))
    boxes = [{"label": "cabinet", "score": 0.9, "xyxy": [1, 2, 20, 25]}]

    preview = proposal_preview_bytes(image, boxes, expected_size=(40, 30), max_edge=20)

    assert isinstance(preview, bytes)
    assert len(preview) < 10_000
    with pytest.raises(AuditDataError, match="dimensions"):
        proposal_preview_bytes(
            Image.new("RGB", (39, 30)), boxes, expected_size=(40, 30), max_edge=20
        )
