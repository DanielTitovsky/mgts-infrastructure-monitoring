from __future__ import annotations

import importlib.util
from copy import deepcopy
from pathlib import Path

from mgts_data_pipeline import cabinet_baseline

_SCRIPT = Path(__file__).resolve().parents[1] / "experiments" / "compare_frozen_heads.py"
_SPEC = importlib.util.spec_from_file_location("compare_frozen_heads", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
frozen_heads = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(frozen_heads)


def _index() -> dict[str, object]:
    records = [
        {
            "image_path": "photos/a.jpg",
            "object_type": "РЩ",
            "condition": "normal",
            "object_id": "shared-object",
            "sha256": "a" * 64,
            "embedding": [1.0, 0.0, 0.0],
        },
        {
            "image_path": "photos/b.jpg",
            "object_type": "ТКШ",
            "condition": "coating_damage",
            "object_id": "shared-object",
            "sha256": "b" * 64,
            "embedding": [0.9, 0.1, 0.0],
        },
        {
            "image_path": "photos/c.jpg",
            "object_type": "РЩ",
            "condition": "mechanical_damage",
            "object_id": "object-c",
            "sha256": "c" * 64,
            "embedding": [0.0, 1.0, 0.0],
        },
        {
            "image_path": "photos/d.jpg",
            "object_type": "ТКШ",
            "condition": "normal",
            "object_id": "object-d",
            "sha256": "d" * 64,
            "embedding": [0.0, 0.0, 1.0],
        },
        {
            "image_path": "photos/e.jpg",
            "object_type": "РЩ",
            "condition": "coating_damage",
            "object_id": "object-e",
            "sha256": "e" * 64,
            "embedding": [-1.0, 0.0, 0.0],
        },
    ]
    for record, group_id in zip(records, cabinet_baseline._groups(records)):
        record["group_id"] = group_id
    return {
        "schema_version": 1,
        "kind": cabinet_baseline.INDEX_KIND,
        "provenance": {
            "checkpoint_sha256": "f" * 64,
            "checkpoint_task": "detect",
            "feature_method": "Ultralytics YOLO.embed, device=cpu, imgsz=640",
            "detector_outputs_used": False,
            "trained_on_cabinets_or_damage": False,
        },
        "records": records,
    }


def test_comparison_uses_same_group_closed_knn_folds_without_leakage() -> None:
    index = _index()
    report = frozen_heads.compare_index(index)
    knn_report = cabinet_baseline.evaluate_leave_group_out(index, top_k=5)
    knn_by_path = {row["image_path"]: row["predicted"] for row in knn_report["folds"]}

    assert report["evaluation"] == "leave-one-object-id-or-exact-sha256-group-out"
    assert report["group_isolation"] == "object_id_or_exact_sha256"
    assert report["source_index"]["record_count"] == 5
    assert report["source_index"]["group_count"] == 4
    assert len(report["folds"]) == 4
    assert sum(len(fold["predictions"]) for fold in report["folds"]) == 5
    for fold in report["folds"]:
        assert fold["excluded_group_id"] not in fold["training_group_ids"]
        assert fold["training_group_count"] == len(fold["training_group_ids"])
        assert fold["excluded_group_id"] not in fold["knn_matched_group_ids"]
        assert fold["excluded_group_id"] not in fold["ridge_training_group_ids"]
        assert fold["excluded_group_id"] not in fold["mlp_training_group_ids"]
        for row in fold["predictions"]:
            assert row["excluded_group_id"] == fold["excluded_group_id"]
            assert row["predicted"]["knn_k5"] == knn_by_path[row["image_path"]]
            assert set(row["predicted"]["supervised_mlp"]) == {
                "object_type",
                "condition",
            }

    shared_fold = next(
        fold
        for fold in report["folds"]
        if any(row["object_id"] == "shared-object" for row in fold["predictions"])
    )
    assert len(shared_fold["predictions"]) == 2
    assert shared_fold["training_example_count"] == 3


def test_comparison_is_reproducible_and_reports_per_class_and_binary_metrics() -> None:
    index = _index()
    first = frozen_heads.compare_index(index)
    second = frozen_heads.compare_index(deepcopy(index))

    assert first == second
    for model in ("knn_k5", "linear_ridge", "supervised_mlp"):
        metrics = first["metrics"][model]
        for target in ("object_type", "condition"):
            target_metrics = metrics[target]
            assert target_metrics["count"] == 5
            assert sum(sum(row.values()) for row in target_metrics["confusion_matrix"].values()) == 5
            assert target_metrics["per_class"]
            for class_metrics in target_metrics["per_class"].values():
                assert {"tp", "fp", "fn", "tn", "precision", "recall", "f1"} <= set(class_metrics)
                assert class_metrics["tp"] + class_metrics["fp"] + class_metrics["fn"] + class_metrics["tn"] == 5

        binary = metrics["condition_binary_damage_vs_normal"]
        assert binary["positive_label"] == "any_damage"
        assert binary["tp"] + binary["fp"] + binary["fn"] + binary["tn"] == binary["covered_count"]
        assert {"precision", "recall", "f1"} <= set(binary)


def test_report_does_not_claim_independent_test_or_backbone_training() -> None:
    report = frozen_heads.compare_index(_index())

    assert report["independence"]["independent_test_set"] is False
    assert report["independence"]["claim"] == "exploratory grouped cross-validation, not an independent test"
    assert report["features"]["frozen"] is True
    assert report["features"]["new_backbone_training"] is False
    ridge = report["methods"]["linear_ridge"]
    assert ridge["alpha"] == frozen_heads.RIDGE_ALPHA
    assert ridge["regularization_selection"] == "fixed predeclared; not tuned on these results"
    assert ridge["feature_centering"] == "training-fold mean only"
    mlp = report["methods"]["supervised_mlp"]
    assert mlp["architecture"] == (
        f"{report['source_index']['embedding_dimensions']}-d frozen features -> "
        "16-unit ReLU -> separate softmax heads"
    )
    assert mlp["epochs"] == frozen_heads.MLP_EPOCHS
    assert mlp["seed"] == frozen_heads.MLP_SEED
    assert mlp["new_backbone_training"] is False
