"""Compare frozen cabinet embeddings with grouped, cross-fitted shallow heads.

This experiment consumes only the local JSON embedding index. It never opens
photos, consults detector outputs, fine-tunes a backbone, or tunes a method on
the reported predictions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any

from mgts_data_pipeline import cabinet_baseline

OBJECT_TYPE_LABELS = ("РЩ", "ТКШ")
CONDITION_LABELS = ("coating_damage", "mechanical_damage", "normal")
RIDGE_ALPHA = 1.0
KNN_K = 5
MLP_HIDDEN_UNITS = 16
MLP_EPOCHS = 80
MLP_LEARNING_RATE = 0.01
MLP_WEIGHT_DECAY = 0.001
MLP_SEED = 20261126
MLP_ADAM_BETA1 = 0.9
MLP_ADAM_BETA2 = 0.999
MLP_ADAM_EPSILON = 1e-8
INDEX_KIND = "mgts-cabinet-reference-index"
REPORT_KIND = "mgts-frozen-head-comparison"
PREDICTIONS_KIND = "mgts-cabinet-cross-fitted-predictions"
HEAD_KIND = "mgts-cabinet-frozen-feature-mlp-head"


class ComparisonError(RuntimeError):
    """Raised when the reference index cannot support a valid comparison."""


def _numpy() -> Any:
    try:
        import numpy as np
    except ImportError as error:
        raise ComparisonError(
            "Frozen-head comparison requires NumPy from the optional inference environment."
        ) from error
    return np


def _validated_records(index: dict[str, Any]) -> list[dict[str, Any]]:
    records = index.get("records") if isinstance(index, dict) else None
    if (
        not isinstance(index, dict)
        or index.get("kind") != INDEX_KIND
        or not isinstance(records, list)
    ):
        raise ComparisonError("Unsupported cabinet reference index.")
    normalized: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            raise ComparisonError("Reference index contains a non-object record.")
        if (
            record.get("object_type") not in OBJECT_TYPE_LABELS
            or record.get("condition") not in CONDITION_LABELS
            or not isinstance(record.get("image_path"), str)
            or not isinstance(record.get("object_id"), str)
            or not isinstance(record.get("sha256"), str)
            or len(record["sha256"]) != 64
            or not isinstance(record.get("group_id"), str)
        ):
            raise ComparisonError("Reference index contains invalid target metadata.")
        copy = dict(record)
        try:
            copy["embedding"] = cabinet_baseline._unit_embedding(record.get("embedding"))
        except cabinet_baseline.InferenceError as error:
            raise ComparisonError("Reference index contains an invalid embedding.") from error
        normalized.append(copy)

    expected_groups = cabinet_baseline._groups(normalized)
    actual_groups = [record["group_id"] for record in normalized]
    if actual_groups != expected_groups:
        raise ComparisonError(
            "Index group IDs do not match the object-id and exact-SHA closure."
        )
    dimensions = {len(record["embedding"]) for record in normalized}
    if len(dimensions) > 1:
        raise ComparisonError("Reference index has inconsistent embedding dimensions.")
    return normalized


def _one_hot(values: list[str], labels: tuple[str, ...], np: Any) -> Any:
    positions = {label: position for position, label in enumerate(labels)}
    targets = np.zeros((len(values), len(labels)), dtype=np.float64)
    for row, value in enumerate(values):
        try:
            targets[row, positions[value]] = 1.0
        except KeyError as error:
            raise ComparisonError(f"Unsupported target label: {value}") from error
    return targets


def _ridge_scores(
    train_x: Any,
    test_x: Any,
    train_y: Any,
    *,
    alpha: float,
    np: Any,
) -> Any:
    """Solve centered multi-output ridge through the smaller dual system."""
    x_mean = train_x.mean(axis=0)
    y_mean = train_y.mean(axis=0)
    centered_x = train_x - x_mean
    centered_y = train_y - y_mean
    gram = centered_x @ centered_x.T
    dual = np.linalg.solve(gram + alpha * np.eye(len(train_x)), centered_y)
    return y_mean + ((test_x - x_mean) @ centered_x.T) @ dual


def _softmax(logits: Any, np: Any) -> Any:
    shifted = logits - logits.max(axis=1, keepdims=True)
    exponentials = np.exp(shifted)
    return exponentials / exponentials.sum(axis=1, keepdims=True)


def _train_mlp_head(
    train_x: Any,
    train_labels: list[str],
    test_x: Any,
    class_labels: tuple[str, ...],
    *,
    seed: int,
    np: Any,
) -> tuple[Any, dict[str, Any]]:
    """Fit one fixed one-hidden-layer softmax MLP and return scores/weights."""
    feature_mean = train_x.mean(axis=0)
    scale = math.sqrt(train_x.shape[1])
    x_train = (train_x - feature_mean) * scale
    x_test = (test_x - feature_mean) * scale
    target = _one_hot(train_labels, class_labels, np)

    rng = np.random.default_rng(seed)
    input_weights = rng.normal(
        0.0, math.sqrt(2.0 / x_train.shape[1]), (x_train.shape[1], MLP_HIDDEN_UNITS)
    )
    input_bias = np.zeros(MLP_HIDDEN_UNITS, dtype=np.float64)
    output_weights = rng.normal(
        0.0, math.sqrt(2.0 / MLP_HIDDEN_UNITS), (MLP_HIDDEN_UNITS, len(class_labels))
    )
    output_bias = np.zeros(len(class_labels), dtype=np.float64)
    parameters = [input_weights, input_bias, output_weights, output_bias]
    first_moments = [np.zeros_like(parameter) for parameter in parameters]
    second_moments = [np.zeros_like(parameter) for parameter in parameters]

    for epoch in range(1, MLP_EPOCHS + 1):
        hidden_pre_activation = x_train @ input_weights + input_bias
        hidden = np.maximum(hidden_pre_activation, 0.0)
        probabilities = _softmax(hidden @ output_weights + output_bias, np)
        output_gradient = (probabilities - target) / len(x_train)
        grad_output_weights = hidden.T @ output_gradient + MLP_WEIGHT_DECAY * output_weights
        grad_output_bias = output_gradient.sum(axis=0)
        hidden_gradient = (output_gradient @ output_weights.T) * (hidden_pre_activation > 0)
        grad_input_weights = x_train.T @ hidden_gradient + MLP_WEIGHT_DECAY * input_weights
        grad_input_bias = hidden_gradient.sum(axis=0)
        gradients = [
            grad_input_weights,
            grad_input_bias,
            grad_output_weights,
            grad_output_bias,
        ]
        for position, (parameter, gradient) in enumerate(zip(parameters, gradients)):
            first_moments[position] = (
                MLP_ADAM_BETA1 * first_moments[position]
                + (1.0 - MLP_ADAM_BETA1) * gradient
            )
            second_moments[position] = (
                MLP_ADAM_BETA2 * second_moments[position]
                + (1.0 - MLP_ADAM_BETA2) * gradient * gradient
            )
            corrected_first = first_moments[position] / (1.0 - MLP_ADAM_BETA1**epoch)
            corrected_second = second_moments[position] / (1.0 - MLP_ADAM_BETA2**epoch)
            parameter -= MLP_LEARNING_RATE * corrected_first / (
                np.sqrt(corrected_second) + MLP_ADAM_EPSILON
            )

    hidden = np.maximum(x_test @ input_weights + input_bias, 0.0)
    scores = hidden @ output_weights + output_bias
    parameters_json = {
        "labels": list(class_labels),
        "feature_mean": feature_mean.tolist(),
        "input_scale": scale,
        "input_weights": input_weights.tolist(),
        "input_bias": input_bias.tolist(),
        "output_weights": output_weights.tolist(),
        "output_bias": output_bias.tolist(),
    }
    return scores, parameters_json


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0


def _classification_metrics(
    true_values: list[str], predicted_values: list[str | None]
) -> dict[str, Any]:
    labels = sorted(set(true_values) | {value for value in predicted_values if value is not None})
    columns = labels + (["unretrieved"] if any(value is None for value in predicted_values) else [])
    confusion = {label: {predicted: 0 for predicted in columns} for label in labels}
    for actual, predicted in zip(true_values, predicted_values):
        confusion[actual][predicted if predicted is not None else "unretrieved"] += 1

    count = len(true_values)
    correct = sum(actual == predicted for actual, predicted in zip(true_values, predicted_values))
    per_class: dict[str, dict[str, int | float]] = {}
    for label in labels:
        tp = confusion[label][label]
        fp = sum(confusion[other][label] for other in labels if other != label)
        fn = sum(
            confusion[label][other] for other in columns if other != label
        )
        tn = count - tp - fp - fn
        precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
        per_class[label] = {
            "support": sum(confusion[label].values()),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "precision": precision,
            "recall": recall,
            "f1": _ratio(2 * tp, 2 * tp + fp + fn),
        }
    f1_values = [float(values["f1"]) for values in per_class.values()]
    return {
        "count": count,
        "covered_count": sum(value is not None for value in predicted_values),
        "unretrieved_count": sum(value is None for value in predicted_values),
        "correct": correct,
        "accuracy": _ratio(correct, count),
        "macro_f1": _ratio(sum(f1_values), len(f1_values)),
        "labels": labels,
        "confusion_matrix": confusion,
        "per_class": per_class,
        "zero_division": 0,
    }


def _binary_damage_metrics(
    true_values: list[str], predicted_values: list[str | None]
) -> dict[str, Any]:
    tp = fp = fn = tn = abstained = 0
    for actual, predicted in zip(true_values, predicted_values):
        if predicted is None:
            abstained += 1
            continue
        actual_damage = actual != "normal"
        predicted_damage = predicted != "normal"
        if actual_damage and predicted_damage:
            tp += 1
        elif predicted_damage:
            fp += 1
        elif actual_damage:
            fn += 1
        else:
            tn += 1
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    covered_count = tp + fp + fn + tn
    return {
        "positive_label": "any_damage",
        "negative_label": "normal",
        "damage_labels": ["coating_damage", "mechanical_damage"],
        "count": len(true_values),
        "covered_count": covered_count,
        "abstained_count": abstained,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": _ratio(2 * tp, 2 * tp + fp + fn),
        "abstentions_excluded_from_binary_confusion": True,
    }


def _method_metrics(
    rows: list[dict[str, Any]], method: str
) -> dict[str, Any]:
    true_type = [row["true"]["object_type"] for row in rows]
    true_condition = [row["true"]["condition"] for row in rows]
    predicted_type = [row["predicted"][method]["object_type"] for row in rows]
    predicted_condition = [row["predicted"][method]["condition"] for row in rows]
    return {
        "object_type": _classification_metrics(true_type, predicted_type),
        "condition": _classification_metrics(true_condition, predicted_condition),
        "condition_binary_damage_vs_normal": _binary_damage_metrics(
            true_condition, predicted_condition
        ),
    }


def compare_index(
    index: dict[str, Any],
    *,
    index_path: str | None = None,
    index_sha256: str | None = None,
) -> dict[str, Any]:
    """Produce deterministic OOF comparison rows for the verified local index."""
    np = _numpy()
    records = _validated_records(index)
    record_count = len(records)
    group_count = len({record["group_id"] for record in records})
    clean_index = {**index, "records": records}
    knn_report = cabinet_baseline.evaluate_leave_group_out(clean_index, top_k=KNN_K)
    knn_rows = knn_report["folds"]
    if len(knn_rows) != record_count:
        raise ComparisonError("kNN baseline did not emit one prediction per index record.")

    if records:
        all_x = np.asarray([record["embedding"] for record in records], dtype=np.float64)
    else:
        all_x = np.empty((0, 0), dtype=np.float64)
    truth_type = [record["object_type"] for record in records]
    truth_condition = [record["condition"] for record in records]
    ridge_type_scores: list[Any | None] = [None] * record_count
    ridge_condition_scores: list[Any | None] = [None] * record_count
    mlp_type_scores: list[Any | None] = [None] * record_count
    mlp_condition_scores: list[Any | None] = [None] * record_count
    folds: list[dict[str, Any]] = []
    by_group: dict[str, list[int]] = defaultdict(list)
    for position, record in enumerate(records):
        by_group[record["group_id"]].append(position)

    for fold_position, excluded_group in enumerate(sorted(by_group)):
        test_positions = by_group[excluded_group]
        train_positions = [
            position
            for position, record in enumerate(records)
            if record["group_id"] != excluded_group
        ]
        train_group_ids = sorted(
            {records[position]["group_id"] for position in train_positions}
        )
        if excluded_group in train_group_ids:
            raise ComparisonError("Held-out group leaked into the training partition.")

        if train_positions:
            train_x = all_x[train_positions]
            test_x = all_x[test_positions]
            train_type_y = _one_hot(
                [truth_type[position] for position in train_positions],
                OBJECT_TYPE_LABELS,
                np,
            )
            train_condition_y = _one_hot(
                [truth_condition[position] for position in train_positions],
                CONDITION_LABELS,
                np,
            )
            # One shared multi-output ridge head predicts the two fixed targets.
            ridge_y = np.concatenate((train_type_y, train_condition_y), axis=1)
            ridge_score = _ridge_scores(
                train_x, test_x, ridge_y, alpha=RIDGE_ALPHA, np=np
            )
            for local_position, index_position in enumerate(test_positions):
                ridge_type_scores[index_position] = ridge_score[local_position, : len(OBJECT_TYPE_LABELS)]
                ridge_condition_scores[index_position] = ridge_score[
                    local_position, len(OBJECT_TYPE_LABELS) :
                ]

            type_score, _ = _train_mlp_head(
                train_x,
                [truth_type[position] for position in train_positions],
                test_x,
                OBJECT_TYPE_LABELS,
                seed=MLP_SEED + 2 * fold_position,
                np=np,
            )
            condition_score, _ = _train_mlp_head(
                train_x,
                [truth_condition[position] for position in train_positions],
                test_x,
                CONDITION_LABELS,
                seed=MLP_SEED + 2 * fold_position + 1,
                np=np,
            )
            for local_position, index_position in enumerate(test_positions):
                mlp_type_scores[index_position] = type_score[local_position]
                mlp_condition_scores[index_position] = condition_score[local_position]

        knn_matches = {
            group_id
            for index_position in test_positions
            for group_id in knn_rows[index_position]["matched_group_ids"]
        }
        if excluded_group in knn_matches:
            raise ComparisonError("Held-out group leaked into the kNN references.")

        predictions: list[dict[str, Any]] = []
        for index_position in test_positions:
            record = records[index_position]
            baseline_row = knn_rows[index_position]
            ridge_type = ridge_type_scores[index_position]
            ridge_condition = ridge_condition_scores[index_position]
            mlp_type = mlp_type_scores[index_position]
            mlp_condition = mlp_condition_scores[index_position]
            predictions.append(
                {
                    "image_path": record["image_path"],
                    "sha256": record["sha256"],
                    "object_id": record["object_id"],
                    "group_id": record["group_id"],
                    "excluded_group_id": excluded_group,
                    "true": {
                        "object_type": record["object_type"],
                        "condition": record["condition"],
                    },
                    "predicted": {
                        "knn_k5": baseline_row["predicted"],
                        "linear_ridge": {
                            "object_type": (
                                OBJECT_TYPE_LABELS[int(np.argmax(ridge_type))]
                                if ridge_type is not None
                                else None
                            ),
                            "condition": (
                                CONDITION_LABELS[int(np.argmax(ridge_condition))]
                                if ridge_condition is not None
                                else None
                            ),
                        },
                        "supervised_mlp": {
                            "object_type": (
                                OBJECT_TYPE_LABELS[int(np.argmax(mlp_type))]
                                if mlp_type is not None
                                else None
                            ),
                            "condition": (
                                CONDITION_LABELS[int(np.argmax(mlp_condition))]
                                if mlp_condition is not None
                                else None
                            ),
                        },
                    },
                    "knn_matched_group_ids": baseline_row["matched_group_ids"],
                    "ridge_training_example_count": len(train_positions),
                    "mlp_training_example_count": len(train_positions),
                }
            )
        folds.append(
            {
                "excluded_group_id": excluded_group,
                "training_example_count": len(train_positions),
                "training_group_count": len(train_group_ids),
                "training_group_ids": train_group_ids,
                "ridge_training_group_ids": train_group_ids,
                "mlp_training_group_ids": train_group_ids,
                "knn_matched_group_ids": sorted(knn_matches),
                "predictions": predictions,
            }
        )

    rows = [
        row
        for fold in folds
        for row in fold["predictions"]
    ]
    metrics = {
        method: _method_metrics(rows, method)
        for method in ("knn_k5", "linear_ridge", "supervised_mlp")
    }
    provenance = index.get("provenance", {})
    if not isinstance(provenance, dict):
        provenance = {}
    feature_dimensions = len(records[0]["embedding"]) if records else 0
    return {
        "schema_version": 1,
        "kind": REPORT_KIND,
        "source_index": {
            "path": index_path,
            "sha256": index_sha256,
            "record_count": record_count,
            "group_count": group_count,
            "embedding_dimensions": feature_dimensions,
        },
        "evaluation": "leave-one-object-id-or-exact-sha256-group-out",
        "group_isolation": "object_id_or_exact_sha256",
        "independence": {
            "independent_test_set": False,
            "claim": "exploratory grouped cross-validation, not an independent test",
            "scope": "each example is predicted by a model fit without its full object-id/exact-SHA group",
        },
        "features": {
            "method": provenance.get("feature_method"),
            "checkpoint_sha256": provenance.get("checkpoint_sha256"),
            "checkpoint_task": provenance.get("checkpoint_task"),
            "frozen": True,
            "detector_outputs_used": False,
            "new_backbone_training": False,
            "trained_on_cabinets_or_damage": provenance.get(
                "trained_on_cabinets_or_damage"
            ),
        },
        "methods": {
            "knn_k5": {
                "kind": "cosine k-nearest-neighbor label vote",
                "k": KNN_K,
                "implementation": "existing cabinet_baseline.evaluate_leave_group_out",
            },
            "linear_ridge": {
                "kind": "one centered multi-output linear ridge head",
                "alpha": RIDGE_ALPHA,
                "regularization_selection": "fixed predeclared; not tuned on these results",
                "feature_centering": "training-fold mean only",
                "target_centering": "training-fold target mean only",
                "solver": "dual ridge with unpenalized centered intercept",
                "outputs": {
                    "object_type": list(OBJECT_TYPE_LABELS),
                    "condition": list(CONDITION_LABELS),
                },
            },
            "supervised_mlp": {
                "kind": "two supervised MLP classification heads on frozen embeddings",
                "architecture": f"{feature_dimensions}-d frozen features -> 16-unit ReLU -> separate softmax heads",
                "hidden_units": MLP_HIDDEN_UNITS,
                "activation": "ReLU",
                "epochs": MLP_EPOCHS,
                "optimizer": "Adam full-batch",
                "learning_rate": MLP_LEARNING_RATE,
                "weight_decay": MLP_WEIGHT_DECAY,
                "seed": MLP_SEED,
                "per_fold_seed": "base seed + 2 * sorted-fold-index + target-offset",
                "feature_centering": "training-fold mean only",
                "input_scale": "sqrt(feature dimension), fixed",
                "regularization_selection": "fixed predeclared; not tuned on these results",
                "new_backbone_training": False,
            },
        },
        "metrics": metrics,
        "ranking_claim": "no best-method claim; architecture and hyperparameters were not tuned on these results",
        "fold_count": len(folds),
        "prediction_count": len(rows),
        "folds": folds,
    }


def cross_fitted_predictions(report: dict[str, Any]) -> dict[str, Any]:
    """Return the compact identity-keyed prediction artifact for the review UI."""
    rows = [
        {
            key: row[key]
            for key in (
                "image_path",
                "sha256",
                "object_id",
                "group_id",
                "true",
                "predicted",
                "excluded_group_id",
                "ridge_training_example_count",
                "mlp_training_example_count",
            )
        }
        for fold in report["folds"]
        for row in fold["predictions"]
    ]
    rows.sort(key=lambda row: (row["image_path"], row["sha256"]))
    return {
        "schema_version": 1,
        "kind": PREDICTIONS_KIND,
        "evaluation": report["evaluation"],
        "group_isolation": report["group_isolation"],
        "independent_test_set": False,
        "source_index": report["source_index"],
        "row_count": len(rows),
        "join_key": ["image_path", "sha256"],
        "rows": rows,
    }


def fit_full_data_mlp(index: dict[str, Any]) -> dict[str, Any]:
    """Fit fixed MLP heads on all labeled rows for later local inference only."""
    np = _numpy()
    records = _validated_records(index)
    if not records:
        raise ComparisonError("Cannot fit a full-data head without labeled examples.")
    all_x = np.asarray([record["embedding"] for record in records], dtype=np.float64)
    heads: dict[str, Any] = {}
    for offset, (target_name, labels) in enumerate(
        (("object_type", OBJECT_TYPE_LABELS), ("condition", CONDITION_LABELS))
    ):
        _, parameters = _train_mlp_head(
            all_x,
            [record[target_name] for record in records],
            all_x[:0],
            labels,
            seed=MLP_SEED + offset,
            np=np,
        )
        heads[target_name] = parameters
    provenance = index.get("provenance", {})
    return {
        "schema_version": 1,
        "kind": HEAD_KIND,
        "purpose": "future local inference only; these fitted weights are not held-out evaluation weights",
        "training_scope": {
            "example_count": len(records),
            "group_count": len({record["group_id"] for record in records}),
            "independent_test_set": False,
        },
        "features": {
            "method": provenance.get("feature_method"),
            "checkpoint_sha256": provenance.get("checkpoint_sha256"),
            "checkpoint_task": provenance.get("checkpoint_task"),
            "frozen": True,
            "new_backbone_training": False,
        },
        "architecture": {
            "input_dimension": len(records[0]["embedding"]),
            "hidden_units": MLP_HIDDEN_UNITS,
            "activation": "ReLU",
            "outputs": "separate softmax heads for object_type and condition",
            "epochs": MLP_EPOCHS,
            "optimizer": "Adam full-batch",
            "learning_rate": MLP_LEARNING_RATE,
            "weight_decay": MLP_WEIGHT_DECAY,
            "seed": MLP_SEED,
        },
        "heads": heads,
    }


def _json_bytes(value: dict[str, Any]) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ComparisonError("Report contains a non-JSON or non-finite value.") from error


def _write_new_json(path: Path, value: dict[str, Any]) -> str:
    path = path.expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise ComparisonError(f"Output already exists; refusing overwrite: {path}")
    contents = _json_bytes(value)
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=path.parent, prefix=f".{path.name}.tmp-", delete=False
        ) as handle:
            temporary = handle.name
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except FileExistsError as error:
        raise ComparisonError(f"Output already exists; refusing overwrite: {path}") from error
    except OSError as error:
        raise ComparisonError(f"Could not write report output: {path}") from error
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return hashlib.sha256(contents).hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare frozen-feature kNN, ridge, and tiny MLP grouped OOF heads."
    )
    parser.add_argument("index", type=Path, help="verified local cabinet embedding index JSON")
    parser.add_argument("--output", type=Path, required=True, help="new comparison report JSON")
    parser.add_argument(
        "--predictions-output",
        type=Path,
        required=True,
        help="new identity-keyed cross-fitted prediction JSON",
    )
    parser.add_argument(
        "--head-output",
        type=Path,
        required=True,
        help="new safe JSON with full-data MLP head weights for later local inference",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    outputs = (args.output.expanduser(), args.predictions_output.expanduser(), args.head_output.expanduser())
    if len(set(outputs)) != len(outputs) or any(path.exists() or path.is_symlink() for path in outputs):
        print("error: output path exists or output paths collide; refusing overwrite", file=sys.stderr)
        return 2
    source = args.index.expanduser().resolve()
    try:
        source_bytes = source.read_bytes()
        index = cabinet_baseline.load_reference_index(source)
        report = compare_index(
            index,
            index_path=str(source),
            index_sha256=hashlib.sha256(source_bytes).hexdigest(),
        )
        predictions = cross_fitted_predictions(report)
        head = fit_full_data_mlp(index)
        predictions_sha256 = _write_new_json(args.predictions_output, predictions)
        head_sha256 = _write_new_json(args.head_output, head)
        report["artifacts"] = {
            "cross_fitted_predictions": {
                "path": str(args.predictions_output.expanduser()),
                "sha256": predictions_sha256,
                "kind": PREDICTIONS_KIND,
                "join_key": ["image_path", "sha256"],
            },
            "full_data_mlp_head": {
                "path": str(args.head_output.expanduser()),
                "sha256": head_sha256,
                "kind": HEAD_KIND,
                "purpose": "future local inference only; not evaluated as an independent test",
            },
        }
        report_sha256 = _write_new_json(args.output, report)
    except (ComparisonError, cabinet_baseline.InferenceError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "report": str(args.output.expanduser()),
                "report_sha256": report_sha256,
                "records": report["source_index"]["record_count"],
                "groups": report["source_index"]["group_count"],
                "folds": report["fold_count"],
                "predictions": report["prediction_count"],
                "metrics": report["metrics"],
                "artifacts": report["artifacts"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
