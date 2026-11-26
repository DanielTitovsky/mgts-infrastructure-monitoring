from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest
import yaml

from mgts_data_pipeline import research


def _image_bytes(size: tuple[int, int] = (32, 20), color: tuple[int, int, int] = (20, 30, 40)) -> bytes:
    from io import BytesIO

    output = BytesIO()
    Image.new("RGB", size, color=color).save(output, format="PNG")
    return output.getvalue()


def _record(root: Path, name: str = "sample.png", *, object_type: str = "РЩ", condition: str = "normal") -> dict[str, object]:
    image = root / name
    image.parent.mkdir(parents=True, exist_ok=True)
    contents = _image_bytes(color=(len(name) % 255, sum(name.encode()) % 255, 40))
    image.write_bytes(contents)
    return {
        "image_path": name,
        "object_type": object_type,
        "condition": condition,
        "source_folder": "source-a",
        "object_id": Path(name).stem,
        "status": "original spreadsheet labels",
        "description": "The original row text is shown for human review.",
        "sha256": hashlib.sha256(contents).hexdigest(),
        "split": "unassigned",
        "coordinates": None,
        "bbox_annotations": None,
    }


def _manifest(path: Path, samples: list[dict[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "samples": samples,
                "warnings": ["No bounding-box labels were supplied."],
                "counts": {"samples": len(samples)},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def test_manifest_summary_and_selected_human_review_sample(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    labeled = _record(root, "РЩ/board.png", object_type="РЩ", condition="mechanical_damage")
    unknown = _record(root, "unknown.png", object_type="unknown", condition="unknown")
    path = _manifest(root / "final-materials.json", [labeled, unknown])

    manifest = research.load_material_manifest(path)
    review = research.load_material_sample(path, 0)

    assert manifest["sample_count"] == 2
    assert manifest["summary"]["object_type"] == {"РЩ": 1, "unknown": 1}
    assert manifest["summary"]["condition"] == {"mechanical_damage": 1, "unknown": 1}
    assert manifest["warnings"] == ["No bounding-box labels were supplied."]
    assert review["sample"]["description"] == labeled["description"]
    assert review["width"] == 32 and review["height"] == 20
    assert review["image"].mode == "RGB"
    assert review["ground_truth_boxes"] is None
    assert "not supplied" in review["warning"] or "supplied" in review["warning"]


def test_display_preview_is_bounded_and_does_not_mutate_the_source_image() -> None:
    original = Image.new("RGB", (4608, 3456), color=(20, 30, 40))

    preview = research.preview_image_bytes(original)
    from io import BytesIO

    with Image.open(BytesIO(preview)) as displayed:
        assert displayed.format == "JPEG"
        assert max(displayed.size) <= research.MAX_PREVIEW_EDGE
        assert len(preview) <= research.MAX_PREVIEW_BYTES
    assert original.size == (4608, 3456)


def test_display_preview_rejects_invalid_type_or_limits() -> None:
    with pytest.raises(research.ResearchError, match="decoded image"):
        research.preview_image_bytes(b"not-image")  # type: ignore[arg-type]
    with pytest.raises(research.ResearchError, match="positive"):
        research.preview_image_bytes(Image.new("RGB", (2, 2)), max_edge=0)
    with pytest.raises(research.ResearchError, match="byte limit"):
        research.preview_image_bytes(Image.new("RGB", (2, 2)), max_bytes=1)


def test_binary_damage_summary_is_derived_from_the_condition_confusion_matrix() -> None:
    condition_metrics = {
        "labels": ["coating_damage", "mechanical_damage", "normal"],
        "no_independent_reference": 0,
        "confusion_matrix": {
            "coating_damage": {"coating_damage": 8, "mechanical_damage": 7, "normal": 5},
            "mechanical_damage": {"coating_damage": 6, "mechanical_damage": 11, "normal": 4},
            "normal": {"coating_damage": 3, "mechanical_damage": 2, "normal": 15},
        },
    }

    summary = research.binary_damage_summary(condition_metrics)

    assert summary == {
        "tp": 32,
        "fp": 5,
        "fn": 9,
        "tn": 15,
        "unclassified": 0,
        "precision": pytest.approx(32 / 37),
        "recall": pytest.approx(32 / 41),
        "f1": pytest.approx(64 / 78),
    }


def test_binary_damage_summary_requires_all_known_condition_classes() -> None:
    assert research.binary_damage_summary({"labels": ["normal"], "confusion_matrix": {}}) is None


def test_manifest_rejects_invalid_schema_oversized_file_and_symlink(tmp_path: Path) -> None:
    manifest = tmp_path / "bad.json"
    manifest.write_text('{"schema_version": 2, "samples": []}', encoding="utf-8")
    with pytest.raises(research.ResearchError, match="schema_version"):
        research.load_material_manifest(manifest)

    manifest.write_bytes(b" " * (research.MAX_MANIFEST_BYTES + 1))
    with pytest.raises(research.ResearchError, match="size limit"):
        research.load_material_manifest(manifest)

    target = tmp_path / "target.json"
    target.write_text('{"schema_version":1,"samples":[]}', encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(research.ResearchError, match="symlink"):
        research.load_material_manifest(link)


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("not-json", "cannot read materials manifest"),
        ("[]", "JSON object"),
        ('{"schema_version":1,"samples":{}}', "samples must be a list"),
        ('{"schema_version":1,"samples":[],"warnings":[2]}', "warnings must be a list"),
        ('{"schema_version":1,"samples":[],"counts":[]}', "counts must be an object"),
    ],
)
def test_manifest_rejects_invalid_json_and_top_level_shapes(tmp_path: Path, contents: str, message: str) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(research.ResearchError, match=message):
        research.load_material_manifest(path)


@pytest.mark.parametrize(
    "relative_path",
    ["/absolute.jpg", "folder\\bad.jpg", "./dot.jpg", "not-image.gif", "../escape.jpg", "folder//empty.jpg"],
)
def test_manifest_rejects_unsafe_or_non_image_paths(tmp_path: Path, relative_path: str) -> None:
    root = tmp_path / "materials"
    sample = _record(root, "valid.png")
    sample["image_path"] = relative_path
    path = _manifest(root / "manifest.json", [sample])
    with pytest.raises(research.ResearchError, match="safe relative image path"):
        research.load_material_manifest(path)


def test_manifest_rejects_bad_hashes_and_unbounded_sample_count(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    sample = _record(root, "one.png")
    sample["sha256"] = "not-a-digest"
    path = _manifest(root / "manifest.json", [sample])
    with pytest.raises(research.ResearchError, match="invalid sha256"):
        research.load_material_manifest(path)

    sample.pop("sha256")
    path = _manifest(root / "too-many.json", [sample] * (research.MAX_MATERIAL_SAMPLES + 1))
    with pytest.raises(research.ResearchError, match="at most"):
        research.load_material_manifest(path)


def test_manifest_sample_path_traversal_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    sample = _record(root, "safe.png")
    sample["image_path"] = "../outside.png"
    path = _manifest(root / "final-materials.json", [sample])

    with pytest.raises(research.ResearchError, match="relative image path"):
        research.load_material_sample(path, 0)


def test_manifest_rejects_missing_or_duplicate_sample_paths(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    first = _record(root, "same.png")
    second = dict(first)
    second["object_id"] = "other"
    path = _manifest(root / "final-materials.json", [first, second])
    with pytest.raises(research.ResearchError, match="duplicate image_path"):
        research.load_material_manifest(path)

    first.pop("description")
    path = _manifest(root / "missing.json", [first])
    with pytest.raises(research.ResearchError, match="description"):
        research.load_material_manifest(path)


def test_material_sample_guards_indices_symlinks_digest_and_boxes(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    sample = _record(root, "one.png")
    path = _manifest(root / "manifest.json", [sample])
    for invalid_index in (True, -1, 1, 0.5):
        with pytest.raises(research.ResearchError, match="sample index"):
            research.load_material_sample(path, invalid_index)  # type: ignore[arg-type]

    sample["sha256"] = "0" * 64
    path = _manifest(root / "wrong-hash.json", [sample])
    with pytest.raises(research.ResearchError, match="SHA-256"):
        research.load_material_sample(path, 0)

    sample["sha256"] = hashlib.sha256((root / "one.png").read_bytes()).hexdigest()
    sample["bbox_annotations"] = [{"bbox": [0, 0, 1, 1]}]
    path = _manifest(root / "boxes.json", [sample])
    with pytest.raises(research.ResearchError, match="bbox_annotations"):
        research.load_material_sample(path, 0)

    sample["bbox_annotations"] = None
    sample["image_path"] = "linked.png"
    (root / "linked.png").symlink_to(root / "one.png")
    path = _manifest(root / "linked.json", [sample])
    with pytest.raises(research.ResearchError, match="symlink"):
        research.load_material_sample(path, 0)

    sample["image_path"] = "missing.png"
    path = _manifest(root / "missing-image.json", [sample])
    with pytest.raises(research.ResearchError, match="resolve to an existing file"):
        research.load_material_sample(path, 0)


@pytest.mark.parametrize(
    ("suffix", "contents", "message"),
    [
        ("bad.png", b"not-image", "could not be decoded"),
        ("bad.gif", _image_bytes(), "safe relative image path"),
        ("too-large.png", b"x" * (research.MAX_IMAGE_BYTES + 1), "byte size limit"),
    ],
)
def test_material_sample_image_decode_guards(tmp_path: Path, suffix: str, contents: bytes, message: str) -> None:
    root = tmp_path / "materials"
    sample = _record(root, "seed.png")
    candidate = root / suffix
    candidate.write_bytes(contents)
    sample["image_path"] = suffix
    sample["sha256"] = hashlib.sha256(contents).hexdigest()
    path = _manifest(root / "manifest.json", [sample])
    with pytest.raises(research.ResearchError, match=message):
        research.load_material_sample(path, 0)


def _yolo_dataset(root: Path, *, labels: str = "0 0.5 0.5 0.5 0.5\n") -> Path:
    image = root / "images" / "train" / "a.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(_image_bytes((40, 20)))
    label = root / "labels" / "train" / "a.txt"
    label.parent.mkdir(parents=True)
    label.write_text(labels, encoding="utf-8")
    (root / "SOURCE.json").write_text(
        json.dumps(
            {
                "source_id": "broken_poles_v2",
                "evaluation_ready": False,
                "evaluation_missing_splits": ["val", "test"],
                "scene_independence_claim": False,
                "conversion": {"polygon_to_bbox": "enclosing axis-aligned bounds"},
            }
        ),
        encoding="utf-8",
    )
    yaml_path = root / "data.yaml"
    yaml_path.write_text(
        yaml.safe_dump({"train": "images/train", "nc": 1, "names": ["broken"]}),
        encoding="utf-8",
    )
    return yaml_path


def test_yolo_sample_inspection_shows_raw_normalized_label_and_pixel_box(tmp_path: Path) -> None:
    yaml_path = _yolo_dataset(tmp_path / "dataset")

    result = research.inspect_yolo_sample(yaml_path, "train", 0)

    assert result["class_names"] == ["broken"]
    assert result["image"].size == (40, 20)
    assert result["label_rows"][0]["raw"] == "0 0.5 0.5 0.5 0.5"
    assert result["label_rows"][0]["class_name"] == "broken"
    assert result["label_rows"][0]["bbox_xyxy_px"] == [10.0, 5.0, 30.0, 15.0]
    assert result["source_metadata"]["source_id"] == "broken_poles_v2"
    assert any("train-only" in item.lower() or "evaluation-ready" in item.lower() for item in result["warnings"])


def test_yolo_sample_index_split_yaml_and_label_errors_fail_closed(tmp_path: Path) -> None:
    yaml_path = _yolo_dataset(tmp_path / "dataset")
    with pytest.raises(research.ResearchError, match="index"):
        research.inspect_yolo_sample(yaml_path, "train", 1)
    with pytest.raises(research.ResearchError, match="split"):
        research.inspect_yolo_sample(yaml_path, "weird", 0)

    bad = _yolo_dataset(tmp_path / "bad", labels="0 2.0 0.5 0.5 0.5\n")
    with pytest.raises(research.ResearchError, match="invalid YOLO label"):
        research.inspect_yolo_sample(bad, "train", 0)


def test_yolo_sample_warns_when_labels_missing_and_rejects_symlinked_image(tmp_path: Path) -> None:
    yaml_path = _yolo_dataset(tmp_path / "dataset", labels="")
    label = yaml_path.parent / "labels" / "train" / "a.txt"
    label.unlink()
    result = research.inspect_yolo_sample(yaml_path, "train", 0)
    assert result["label_rows"] == []
    assert any("missing" in warning for warning in result["warnings"])

    image = yaml_path.parent / "images" / "train" / "a.png"
    image.unlink()
    image.symlink_to(_image_bytes_path(tmp_path))
    with pytest.raises(research.ResearchError, match="symlink"):
        research.inspect_yolo_sample(yaml_path, "train", 0)


def _image_bytes_path(tmp_path: Path) -> Path:
    path = tmp_path / "outside.png"
    path.write_bytes(_image_bytes())
    return path


def test_prediction_and_ground_truth_overlay_are_separate_numeric_layers() -> None:
    image = Image.new("RGB", (30, 20), color=(0, 0, 0))
    overlay = research.draw_box_overlay(
        image,
        ground_truth=[{"class_name": "actual", "bbox_xyxy_px": [2, 3, 12, 13]}],
        predictions=[{"class": "guess", "confidence": 0.8, "bbox_xyxy_px": [15, 3, 25, 13]}],
    )

    assert overlay.size == (30, 20)
    assert overlay.getpixel((2, 3)) == research.GROUND_TRUTH_COLOR
    assert overlay.getpixel((15, 3)) == research.PREDICTION_COLOR
    assert overlay.getpixel((0, 0)) == (0, 0, 0)

    with pytest.raises(research.ResearchError, match="box coordinates"):
        research.draw_box_overlay(image, predictions=[{"bbox_xyxy_px": [1, 2, float("nan"), 4]}])


def test_training_plan_requires_explicit_safe_split_and_does_not_claim_scene_holdout(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    train = _record(root, "one.png", condition="normal")
    validation = _record(root, "two.png", condition="normal")
    test = _record(root, "three.png", condition="mechanical_damage")
    samples = [train, validation, test]
    assignments = {"one.png": "train", "two.png": "validation", "three.png": "test"}

    result = research.validate_training_plan(samples, assignments, target="condition")

    assert result["task"] == "image_classification"
    assert result["split_counts"] == {"train": 1, "validation": 1, "test": 1, "exclude": 0}
    assert result["evaluation_ready"] is True
    assert any("scene" in warning.lower() for warning in result["warnings"])
    assert result["training_executed"] is False


def test_training_plan_rejects_unknown_labels_included_or_group_leakage(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    known = _record(root, "one.png", condition="normal")
    unknown = _record(root, "unknown.png", condition="unknown")
    with pytest.raises(research.ResearchError, match="unknown samples must be excluded"):
        research.validate_training_plan(
            [known, unknown], {"one.png": "train", "unknown.png": "validation"}, target="condition"
        )

    other = dict(_record(root, "two.png", condition="normal"))
    other["sha256"] = known["sha256"]
    with pytest.raises(research.ResearchError, match="exact-image leakage"):
        research.validate_training_plan(
            [known, other], {"one.png": "train", "two.png": "validation"}, target="condition"
        )


def test_training_plan_requires_all_choices_and_known_targets(tmp_path: Path) -> None:
    root = tmp_path / "materials"
    known = _record(root, "one.png")
    with pytest.raises(research.ResearchError, match="every sample"):
        research.validate_training_plan([known], {}, target="condition")
    with pytest.raises(research.ResearchError, match="target"):
        research.validate_training_plan([known], {"one.png": "train"}, target="health")
    with pytest.raises(research.ResearchError, match="train, validation, and test"):
        research.validate_training_plan([known], {"one.png": "train"}, target="condition")
