from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).parents[1]))
from experiments import localize_cabinets as localize  # noqa: E402
from experiments.localize_cabinets import (  # noqa: E402
    detections_to_boxes,
    load_verified_manifest,
    make_sample_result,
)


def _write_manifest(root: Path, *, image_path: str = "photos/cabinet.png") -> tuple[Path, dict]:
    photo = root / image_path
    photo.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (18, 12), color=(50, 80, 100)).save(photo, format="PNG")
    sample = {
        "image_path": image_path,
        "sha256": hashlib.sha256(photo.read_bytes()).hexdigest(),
        "width": 18,
        "height": 12,
        "bbox_annotations": None,
    }
    manifest = root / "final-materials.json"
    manifest.write_text(json.dumps({"schema_version": 1, "samples": [sample]}), encoding="utf-8")
    return manifest, sample


def test_verified_manifest_binds_exact_file_hash_dimensions_and_manifest_digest(tmp_path: Path) -> None:
    manifest, sample = _write_manifest(tmp_path)

    document, manifest_digest, entries = load_verified_manifest(manifest, tmp_path, expected_samples=1)

    assert len(document["samples"]) == 1
    assert manifest_digest == hashlib.sha256(manifest.read_bytes()).hexdigest()
    assert entries == [(sample, tmp_path / sample["image_path"])]


def test_verified_manifest_rejects_traversal_and_content_or_dimension_drift(tmp_path: Path) -> None:
    manifest, sample = _write_manifest(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["samples"][0]["image_path"] = "../outside.png"
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="unsafe or duplicate"):
        load_verified_manifest(manifest, tmp_path, expected_samples=1)

    manifest, sample = _write_manifest(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["samples"][0]["width"] = sample["width"] + 1
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="dimensions mismatch"):
        load_verified_manifest(manifest, tmp_path, expected_samples=1)

    manifest, sample = _write_manifest(tmp_path)
    document = json.loads(manifest.read_text(encoding="utf-8"))
    document["samples"][0]["sha256"] = "0" * 64
    manifest.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        load_verified_manifest(manifest, tmp_path, expected_samples=1)


def test_no_model_detections_remain_explicit_negative_without_using_annotations() -> None:
    sample = {
        "sha256": "a" * 64,
        "image_path": "cabinet.png",
        "width": 100,
        "height": 80,
        # Even a populated annotation field is never treated as a detector output.
        "bbox_annotations": [{"label": "fabricated", "xyxy": [1, 2, 3, 4]}],
    }

    result = make_sample_result(sample, {"scores": [], "labels": [], "boxes": []})

    assert result["detection_status"] == "not_detected"
    assert result["boxes"] == []


def test_detector_boxes_are_thresholded_clipped_deduplicated_and_capped() -> None:
    results = detections_to_boxes(
        [0.9, 0.8, 0.7, 0.6, 0.2],
        ["electrical cabinet", "electrical panel", "switchboard", "panel", "cabinet"],
        [
            [1, 1, 11, 11],
            [2, 2, 12, 12],  # Same object as the higher-scored first candidate.
            [15, 2, 20, 8],
            [-4, -4, 5, 5],
            [30, 30, 40, 40],  # Below the explicit score threshold.
        ],
        width=18,
        height=12,
        threshold=0.25,
        iou_threshold=0.5,
        max_detections=10,
    )

    assert results == [
        {"label": "electrical cabinet", "score": 0.9, "xyxy": [1.0, 1.0, 11.0, 11.0]},
        {"label": "switchboard", "score": 0.7, "xyxy": [15.0, 2.0, 18.0, 8.0]},
        {"label": "panel", "score": 0.6, "xyxy": [0.0, 0.0, 5.0, 5.0]},
    ]
    assert len(
        detections_to_boxes(
            [0.9, 0.8],
            ["one", "two"],
            [[1, 1, 4, 4], [5, 5, 8, 8]],
            width=18,
            height=12,
            max_detections=1,
        )
    ) == 1


def test_detector_output_array_mismatch_fails_closed() -> None:
    with pytest.raises(ValueError, match="mismatched"):
        detections_to_boxes([0.9], [], [[1, 1, 4, 4]], width=18, height=12)


def test_local_model_path_must_match_the_pinned_public_checkpoint(tmp_path: Path, monkeypatch) -> None:
    weights = tmp_path / "model.safetensors"
    weights.write_bytes(b"verified official model bytes")
    monkeypatch.setattr(localize, "MODEL_WEIGHTS_SHA256", hashlib.sha256(weights.read_bytes()).hexdigest())

    assert localize._verify_local_model_path(tmp_path) == weights
    weights.write_bytes(b"unrelated checkpoint")
    with pytest.raises(ValueError, match="pinned Grounding DINO"):
        localize._verify_local_model_path(tmp_path)
