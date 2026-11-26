"""Local cabinet photo retrieval baseline, not a trained cabinet or damage detector.

The existing pole detector checkpoint is used only as a source of generic image
embeddings. Similarity is not a probability; every result remains a review hint.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from pathlib import Path, PurePosixPath
from typing import Any

from .inference import IMAGE_SUFFIXES, MAX_IMAGE_BYTES, InferenceError, _decode_image

OBJECT_TYPES = {"РЩ", "ТКШ", "unknown"}
CONDITIONS = {"normal", "mechanical_damage", "coating_damage", "unknown"}
MAX_REFERENCE_SAMPLES = 61
MAX_MANIFEST_SAMPLES = MAX_REFERENCE_SAMPLES + 1
EMBEDDING_IMAGE_SIZE = 640
INDEX_KIND = "mgts-cabinet-reference-index"


def _as_list(value: Any) -> Any:
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "tolist"):
        value = value.tolist()
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_bounded(path: Path, description: str) -> bytes:
    try:
        with path.open("rb") as handle:
            contents = handle.read(MAX_IMAGE_BYTES + 1)
    except OSError as error:
        raise InferenceError(f"Could not read {description}.") from error
    if len(contents) > MAX_IMAGE_BYTES:
        raise InferenceError(f"{description.capitalize()} exceeds the 10 MB limit.")
    return contents


def _unit_embedding(value: Any) -> list[float]:
    raw = _as_list(value)
    if (
        isinstance(raw, (tuple, list))
        and len(raw) == 1
        and isinstance(raw[0], (tuple, list))
    ):
        raw = raw[0]
    if not isinstance(raw, (tuple, list)) or not raw:
        raise InferenceError(
            "The local model returned an empty or non-vector embedding."
        )
    try:
        vector = [float(item) for item in raw]
    except (TypeError, ValueError) as error:
        raise InferenceError(
            "The local model returned an invalid embedding vector."
        ) from error
    if not all(math.isfinite(value) for value in vector):
        raise InferenceError(
            "The local model embedding must contain only finite non-zero values."
        )
    norm = math.sqrt(sum(value * value for value in vector))
    if not math.isfinite(norm) or norm <= 0:
        raise InferenceError(
            "The local model embedding must contain only finite non-zero values."
        )
    return [value / norm for value in vector]


def load_embedder(
    checkpoint_path: str | Path,
    embedder_factory: Callable[[str], Any] | None = None,
) -> Any:
    """Load only an explicitly present local detection checkpoint for embeddings."""
    checkpoint = Path(checkpoint_path).expanduser()
    if checkpoint.suffix.lower() != ".pt" or not checkpoint.is_file():
        raise InferenceError(
            "The configured local model checkpoint is missing; provide a trusted detection .pt file."
        )
    checkpoint = checkpoint.resolve()
    if embedder_factory is None:
        try:
            from ultralytics import YOLO
        except ImportError as error:
            raise InferenceError(
                "Cabinet embeddings require the optional CPU dependency; install the `inference` extra."
            ) from error
        embedder_factory = YOLO
    try:
        model = embedder_factory(str(checkpoint))
    except Exception as error:
        raise InferenceError(
            "Could not load the configured local embedding checkpoint."
        ) from error
    if getattr(model, "task", None) != "detect":
        raise InferenceError(
            "The configured checkpoint must be an existing detection checkpoint."
        )
    return model


def embed_photo(model: Any, filename: str, contents: bytes) -> list[float]:
    """Embed one bounded image on CPU; no detector boxes/classes are consulted."""
    image = _decode_image(filename, contents)
    if getattr(model, "task", None) != "detect":
        raise InferenceError(
            "The configured checkpoint must be an existing detection checkpoint."
        )
    try:
        vectors = model.embed(
            source=image,
            device="cpu",
            imgsz=EMBEDDING_IMAGE_SIZE,
            save=False,
            verbose=False,
        )
    except Exception as error:
        raise InferenceError(
            "The local checkpoint failed to extract an image embedding."
        ) from error
    vectors = _as_list(vectors)
    if not isinstance(vectors, (tuple, list)) or len(vectors) != 1:
        raise InferenceError(
            "The local model returned an unexpected number of embeddings."
        )
    return _unit_embedding(vectors[0])


def _manifest_records(manifest_path: Path) -> list[dict[str, Any]]:
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InferenceError("Could not read the cabinet manifest JSON.") from error
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise InferenceError("Cabinet manifest schema_version must be 1.")
    samples = manifest.get("samples")
    if not isinstance(samples, list):
        raise InferenceError("Cabinet manifest samples must be an array.")
    if len(samples) > MAX_MANIFEST_SAMPLES:
        raise InferenceError(
            f"Cabinet manifest cannot exceed {MAX_MANIFEST_SAMPLES} photo records."
        )
    root = manifest_path.parent.resolve()
    validated: list[dict[str, Any]] = []
    for position, item in enumerate(samples):
        if not isinstance(item, dict):
            raise InferenceError(
                f"Cabinet manifest sample {position} must be an object."
            )
        image_path = item.get("image_path")
        if not isinstance(image_path, str) or not image_path or "\\" in image_path:
            raise InferenceError(
                f"Cabinet manifest sample {position} has an invalid image_path."
            )
        relative = PurePosixPath(image_path)
        if (
            relative.is_absolute()
            or ".." in relative.parts
            or relative.parts in {(), (".",)}
        ):
            raise InferenceError(
                "Cabinet image_path must be a safe manifest-relative path."
            )
        image = root.joinpath(*relative.parts)
        try:
            resolved = image.resolve(strict=True)
        except OSError as error:
            raise InferenceError(f"Cabinet image is missing: {image_path}") from error
        if not resolved.is_relative_to(root) or not resolved.is_file():
            raise InferenceError(
                "Cabinet image_path resolves outside the manifest directory or is not a file."
            )
        if resolved.suffix.lower() not in IMAGE_SUFFIXES:
            raise InferenceError(
                "Cabinet references must be JPEG, PNG, or WebP images."
            )
        if resolved.stat().st_size > MAX_IMAGE_BYTES:
            raise InferenceError("A cabinet reference exceeds the 10 MB limit.")
        object_type, condition = item.get("object_type"), item.get("condition")
        object_id, sha256 = item.get("object_id"), item.get("sha256")
        if (
            not isinstance(object_type, str)
            or object_type not in OBJECT_TYPES
            or not isinstance(condition, str)
            or condition not in CONDITIONS
        ):
            raise InferenceError(
                f"Cabinet manifest sample {position} has an unsupported label."
            )
        if not isinstance(object_id, str) or not object_id.strip():
            raise InferenceError(
                f"Cabinet manifest sample {position} has an invalid object_id."
            )
        if (
            not isinstance(sha256, str)
            or len(sha256) != 64
            or any(c not in "0123456789abcdef" for c in sha256.lower())
        ):
            raise InferenceError(
                f"Cabinet manifest sample {position} has an invalid sha256."
            )
        digest = hashlib.sha256()
        bytes_read = 0
        try:
            with resolved.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    bytes_read += len(chunk)
                    if bytes_read > MAX_IMAGE_BYTES:
                        raise InferenceError(
                            f"A cabinet reference exceeds the 10 MB limit: {image_path}"
                        )
                    digest.update(chunk)
        except InferenceError:
            raise
        except OSError as error:
            raise InferenceError(
                f"Could not read cabinet image: {image_path}"
            ) from error
        if digest.hexdigest() != sha256.lower():
            raise InferenceError(
                f"Cabinet image SHA-256 does not match the manifest: {image_path}"
            )
        validated.append(
            {
                "image_path": image_path,
                "resolved_path": resolved,
                "object_type": object_type,
                "condition": condition,
                "object_id": object_id,
                "sha256": sha256.lower(),
            }
        )
    return validated


def _groups(records: list[dict[str, Any]]) -> list[str]:
    """Connect samples sharing object_id OR exact bytes before assigning holdout groups."""
    parent = list(range(len(records)))

    def find(value: int) -> int:
        while parent[value] != value:
            parent[value] = parent[parent[value]]
            value = parent[value]
        return value

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[max(left_root, right_root)] = min(left_root, right_root)

    owners: dict[tuple[str, str], int] = {}
    for index, record in enumerate(records):
        for key in (("object_id", record["object_id"]), ("sha256", record["sha256"])):
            if key in owners:
                union(index, owners[key])
            else:
                owners[key] = index
    members: dict[int, list[int]] = defaultdict(list)
    for index in range(len(records)):
        members[find(index)].append(index)
    group_ids: dict[int, str] = {}
    for root, indices in members.items():
        identity = "\n".join(
            sorted(
                f"{records[index]['object_id']}\0{records[index]['sha256']}"
                for index in indices
            )
        )
        group_ids[root] = hashlib.sha256(identity.encode()).hexdigest()[:16]
    return [group_ids[find(index)] for index in range(len(records))]


def build_reference_index(
    manifest_path: str | Path,
    output_path: str | Path,
    checkpoint_path: str | Path,
    *,
    embedder_factory: Callable[[str], Any] | None = None,
    max_samples: int = MAX_REFERENCE_SAMPLES,
) -> dict[str, Any]:
    """Create a JSON-only local feature index, never training or writing image copies."""
    if (
        isinstance(max_samples, bool)
        or not isinstance(max_samples, int)
        or max_samples < 1
    ):
        raise InferenceError("max_samples must be a positive integer.")
    if max_samples > MAX_REFERENCE_SAMPLES:
        raise InferenceError(
            f"max_samples cannot exceed the {MAX_REFERENCE_SAMPLES}-image CPU limit."
        )
    checkpoint = Path(checkpoint_path).expanduser()
    if checkpoint.suffix.lower() != ".pt" or not checkpoint.is_file():
        raise InferenceError(
            "The configured local model checkpoint is missing; provide a trusted detection .pt file."
        )
    checkpoint = checkpoint.resolve()
    checkpoint_digest = _sha256_file(checkpoint)
    manifest_file = Path(manifest_path).expanduser().resolve()
    validated = _manifest_records(manifest_file)
    # Samples marked unknown are not valid references. A label remains eligible only
    # when both targets have verified values, keeping retrieval votes interpretable.
    candidates = [
        sample
        for sample in validated
        if sample["object_type"] != "unknown" and sample["condition"] != "unknown"
    ]
    selected = candidates[:max_samples]
    for sample, group_id in zip(selected, _groups(selected)):
        sample["group_id"] = group_id
    model = load_embedder(checkpoint, embedder_factory)
    records: list[dict[str, Any]] = []
    for sample in selected:
        contents = _read_bounded(
            sample["resolved_path"], f"Cabinet reference {sample['image_path']}"
        )
        if hashlib.sha256(contents).hexdigest() != sample["sha256"]:
            raise InferenceError(
                f"Cabinet image SHA-256 does not match the manifest: {sample['image_path']}"
            )
        embedding = embed_photo(model, sample["image_path"], contents)
        records.append(
            {
                "image_path": sample["image_path"],
                "object_type": sample["object_type"],
                "condition": sample["condition"],
                "object_id": sample["object_id"],
                "sha256": sample["sha256"],
                "group_id": sample["group_id"],
                "embedding": embedding,
            }
        )
        del contents
    dimensions = {len(record["embedding"]) for record in records}
    if len(dimensions) > 1:
        raise InferenceError(
            "The local model returned inconsistent embedding dimensions."
        )
    index: dict[str, Any] = {
        "schema_version": 1,
        "kind": INDEX_KIND,
        "provenance": {
            "checkpoint_path": str(checkpoint),
            "checkpoint_sha256": checkpoint_digest,
            "checkpoint_task": "detect",
            "feature_method": "Ultralytics YOLO.embed, device=cpu, imgsz=640",
            "detector_outputs_used": False,
            "trained_on_cabinets_or_damage": False,
            "similarity_is_probability": False,
        },
        "build": {
            "manifest_path": str(manifest_file),
            "candidate_count": len(candidates),
            "record_count": len(records),
            "unknown_samples_excluded": len(validated) - len(candidates),
            "max_samples": max_samples,
            "truncated": len(candidates) > len(records),
            "embedding_dimensions": next(iter(dimensions), 0),
        },
        "records": records,
        "limitations": [
            "Checkpoint was trained for pole detection, not cabinets or cabinet damage.",
            "Nearest-neighbour similarity is not a calibrated probability.",
            "The index is an exploratory reference retrieval baseline, not an automated repair decision.",
        ],
    }
    _write_new_json(Path(output_path).expanduser(), index)
    return {"output": str(Path(output_path).expanduser()), **index}


def _write_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise InferenceError(f"Index output already exists; refusing overwrite: {path}")
    temporary: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.tmp-",
            delete=False,
        ) as handle:
            temporary = handle.name
            json.dump(
                value,
                handle,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            )
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, path)
    except FileExistsError as error:
        raise InferenceError(
            f"Index output already exists; refusing overwrite: {path}"
        ) from error
    except (OSError, TypeError, ValueError) as error:
        raise InferenceError(
            f"Could not write cabinet reference index: {path}"
        ) from error
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def load_reference_index(index_path: str | Path) -> dict[str, Any]:
    path = Path(index_path).expanduser()
    try:
        index = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise InferenceError("Could not read cabinet reference index JSON.") from error
    if (
        not isinstance(index, dict)
        or index.get("schema_version") != 1
        or index.get("kind") != INDEX_KIND
    ):
        raise InferenceError("Unsupported cabinet reference index schema.")
    records = index.get("records")
    if not isinstance(records, list):
        raise InferenceError("Cabinet reference index records must be an array.")
    dimensions: int | None = None
    for record in records:
        if not isinstance(record, dict):
            raise InferenceError("Cabinet reference index contains an invalid record.")
        vector = _unit_embedding(record.get("embedding"))
        if dimensions is not None and len(vector) != dimensions:
            raise InferenceError(
                "Cabinet reference index has inconsistent embedding dimensions."
            )
        dimensions = len(vector)
        record["embedding"] = vector
        image_path = record.get("image_path")
        relative = (
            PurePosixPath(image_path)
            if isinstance(image_path, str)
            else PurePosixPath("/")
        )
        object_type, condition = record.get("object_type"), record.get("condition")
        if (
            not isinstance(object_type, str)
            or object_type not in OBJECT_TYPES - {"unknown"}
            or not isinstance(condition, str)
            or condition not in CONDITIONS - {"unknown"}
            or not isinstance(record.get("object_id"), str)
            or not record["object_id"].strip()
            or not isinstance(record.get("sha256"), str)
            or len(record["sha256"]) != 64
            or any(char not in "0123456789abcdef" for char in record["sha256"].lower())
            or not isinstance(record.get("group_id"), str)
            or not record["group_id"]
            or not isinstance(image_path, str)
            or "\\" in image_path
            or relative.is_absolute()
            or ".." in relative.parts
            or relative.parts in {(), (".",)}
        ):
            raise InferenceError(
                "Cabinet reference index contains invalid reference metadata."
            )
    if [record.get("group_id") for record in records] != _groups(records):
        raise InferenceError(
            "Cabinet reference index group IDs do not match object IDs and exact SHA-256s."
        )
    return index


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right):
        raise InferenceError(
            "Query embedding dimension does not match the cabinet reference index."
        )
    return sum(a * b for a, b in zip(left, right))


def _vote(matches: list[dict[str, Any]], field: str) -> str | None:
    if not matches:
        return None
    counts: Counter[str] = Counter(match[field] for match in matches)
    similarity_sums: dict[str, float] = defaultdict(float)
    for match in matches:
        similarity_sums[match[field]] += match["similarity"]
    return min(
        counts, key=lambda label: (-counts[label], -similarity_sums[label], label)
    )


def retrieve(
    index: dict[str, Any],
    embedding: Any,
    *,
    top_k: int = 5,
    exclude_sha256: str | None = None,
    exclude_object_id: str | None = None,
    exclude_group_id: str | None = None,
) -> dict[str, Any]:
    """Return similar known references and a tentative label that always needs review."""
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise InferenceError("top_k must be a positive integer.")
    if (
        not isinstance(index, dict)
        or index.get("kind") != INDEX_KIND
        or not isinstance(index.get("records"), list)
    ):
        raise InferenceError("Unsupported cabinet reference index.")
    query = _unit_embedding(embedding)
    matches: list[dict[str, Any]] = []
    for record in index["records"]:
        reference_embedding = _unit_embedding(record.get("embedding"))
        if len(query) != len(reference_embedding):
            raise InferenceError(
                "Query embedding dimension does not match the cabinet reference index."
            )
        if (
            (exclude_sha256 and record.get("sha256") == exclude_sha256)
            or (exclude_object_id and record.get("object_id") == exclude_object_id)
            or (exclude_group_id and record.get("group_id") == exclude_group_id)
        ):
            continue
        if (
            record.get("object_type") == "unknown"
            or record.get("condition") == "unknown"
        ):
            continue
        matches.append(
            {
                key: record[key]
                for key in (
                    "image_path",
                    "object_type",
                    "condition",
                    "object_id",
                    "sha256",
                    "group_id",
                )
                if key in record
            }
            | {"similarity": _cosine(query, reference_embedding)}
        )
    matches.sort(
        key=lambda match: (
            -match["similarity"],
            match["sha256"],
            match.get("image_path", ""),
        )
    )
    nearest = matches[:top_k]
    return {
        "matches": nearest,
        "tentative": {
            "object_type": _vote(nearest, "object_type"),
            "condition": _vote(nearest, "condition"),
        },
        "needs_review": True,
        "similarity_is_probability": False,
        "automated_repair": False,
        "message": "Exploratory similarity only; verify the photo and labels manually before any action.",
    }


def _classification_metrics(
    true_values: list[str], predicted_values: list[str | None]
) -> dict[str, Any]:
    labels = sorted(
        set(true_values) | {value for value in predicted_values if value is not None}
    )
    columns = labels + (
        ["unretrieved"] if any(value is None for value in predicted_values) else []
    )
    confusion: dict[str, dict[str, int]] = {
        label: {pred: 0 for pred in columns} for label in labels
    }
    correct = 0
    f1_values: list[float] = []
    for actual, predicted in zip(true_values, predicted_values):
        if predicted is None:
            confusion[actual]["unretrieved"] += 1
        else:
            confusion[actual][predicted] += 1
            correct += actual == predicted
    for label in labels:
        tp = confusion[label][label]
        fp = sum(confusion[other][label] for other in labels if other != label)
        fn = sum(confusion[label][other] for other in columns if other != label)
        denominator = 2 * tp + fp + fn
        f1_values.append(2 * tp / denominator if denominator else 0.0)
    total = len(true_values)
    return {
        "count": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "macro_f1": sum(f1_values) / len(f1_values) if f1_values else 0.0,
        "labels": labels,
        "confusion_matrix": confusion,
        "no_independent_reference": sum(value is None for value in predicted_values),
    }


def evaluate_leave_group_out(
    index: dict[str, Any] | str | Path, *, top_k: int = 5
) -> dict[str, Any]:
    """Exploratory leave-object/exact-image-group-out retrieval evaluation."""
    if isinstance(index, (str, Path)):
        index = load_reference_index(index)
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
        raise InferenceError("top_k must be a positive integer.")
    records = index.get("records") if isinstance(index, dict) else None
    if (
        not isinstance(index, dict)
        or index.get("kind") != INDEX_KIND
        or not isinstance(records, list)
    ):
        raise InferenceError("Unsupported cabinet reference index.")
    folds: list[dict[str, Any]] = []
    true_type: list[str] = []
    pred_type: list[str | None] = []
    true_condition: list[str] = []
    pred_condition: list[str | None] = []
    for record in records:
        result = retrieve(
            index, record["embedding"], top_k=top_k, exclude_group_id=record["group_id"]
        )
        object_prediction = result["tentative"]["object_type"]
        condition_prediction = result["tentative"]["condition"]
        true_type.append(record["object_type"])
        pred_type.append(object_prediction)
        true_condition.append(record["condition"])
        pred_condition.append(condition_prediction)
        folds.append(
            {
                "image_path": record["image_path"],
                "object_id": record["object_id"],
                "excluded_group_id": record["group_id"],
                "match_count": len(result["matches"]),
                "matched_group_ids": sorted(
                    {match["group_id"] for match in result["matches"]}
                ),
                "true": {
                    "object_type": record["object_type"],
                    "condition": record["condition"],
                },
                "predicted": {
                    "object_type": object_prediction,
                    "condition": condition_prediction,
                },
            }
        )
    return {
        "evaluation": "leave-one-object-id-or-exact-sha256-group-out",
        "group_isolation": "object_id_or_exact_sha256",
        "reference_count": len(records),
        "groups": len({record["group_id"] for record in records}),
        "top_k": top_k,
        "metrics": {
            "object_type": _classification_metrics(true_type, pred_type),
            "condition": _classification_metrics(true_condition, pred_condition),
        },
        "targets": {"object_type": len(true_type), "condition": len(true_condition)},
        "folds": folds,
        "limitations": [
            "Exploratory metrics on a tiny, non-independent photo collection; not a generalization claim.",
            "Checkpoint embeddings come from a pole detector, not cabinet or damage training.",
            "Similarities and tentative labels are not calibrated; review is required for every case.",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m mgts_data_pipeline.cabinet_baseline",
        description="Build and inspect an explicitly local cabinet photo embedding retrieval baseline.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser(
        "build", help="embed labeled manifest images into a new JSON index"
    )
    build.add_argument("manifest", type=Path)
    build.add_argument("output", type=Path)
    build.add_argument("checkpoint", type=Path)
    build.add_argument("--max-samples", type=int, default=MAX_REFERENCE_SAMPLES)
    evaluate = commands.add_parser(
        "evaluate", help="run leave-object-group-out retrieval evaluation"
    )
    evaluate.add_argument("index", type=Path)
    evaluate.add_argument("--top-k", type=int, default=5)
    query = commands.add_parser(
        "query", help="compare one photo to an existing reference index"
    )
    query.add_argument("index", type=Path)
    query.add_argument("image", type=Path)
    query.add_argument("--checkpoint", required=True, type=Path)
    query.add_argument("--top-k", type=int, default=5)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_reference_index(
                args.manifest,
                args.output,
                args.checkpoint,
                max_samples=args.max_samples,
            )
        elif args.command == "evaluate":
            result = evaluate_leave_group_out(args.index, top_k=args.top_k)
        else:
            index = load_reference_index(args.index)
            model = load_embedder(args.checkpoint)
            image = args.image.expanduser()
            contents = _read_bounded(image, "Query image")
            result = retrieve(
                index,
                embed_photo(model, image.name, contents),
                top_k=args.top_k,
                exclude_sha256=hashlib.sha256(contents).hexdigest(),
            )
    except (InferenceError, OSError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
