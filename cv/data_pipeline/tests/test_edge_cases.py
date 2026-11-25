from __future__ import annotations

import json
import zipfile
from io import BytesIO
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import yaml
from PIL import Image

from mgts_data_pipeline.adapters import (
    _names_from_yaml,
    iter_ohl_samples,
    iter_parquet_samples,
    iter_roboflow_samples,
    iter_yolo_directory_samples,
    normalize_split,
    parse_coco_box,
    parse_xyxy_box,
)
from mgts_data_pipeline.errors import PipelineError
from mgts_data_pipeline.models import Annotation, Sample
from mgts_data_pipeline.normalize import normalize_records, validate_dataset
from mgts_data_pipeline.safeio import ensure_regular_file, hash_bytes, image_dimensions, safe_member_name, validate_zip


def jpeg_bytes(*, orientation: int | None = None) -> bytes:
    stream = BytesIO()
    image = Image.new("RGB", (30, 20), color=(10, 20, 30))
    if orientation:
        exif = Image.Exif()
        exif[274] = orientation
        image.save(stream, format="JPEG", exif=exif)
    else:
        image.save(stream, format="JPEG")
    return stream.getvalue()


def test_archive_and_image_primitives_reject_unsafe_inputs(tmp_path: Path) -> None:
    for unsafe in ("/absolute", "C:/drive", "a/../b", "a\\b", ""):
        with pytest.raises(PipelineError):
            safe_member_name(unsafe)
    assert safe_member_name("folder/image.jpg") == "folder/image.jpg"
    assert hash_bytes(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert image_dimensions(jpeg_bytes(orientation=6))[0:2] == (30, 20)
    assert image_dimensions(jpeg_bytes(orientation=6))[3] == 6
    with pytest.raises(PipelineError, match="corrupt image"):
        image_dimensions(b"not image bytes")

    gif = BytesIO()
    Image.new("RGB", (2, 2)).save(gif, format="GIF")
    with pytest.raises(PipelineError, match="unsupported image format"):
        image_dimensions(gif.getvalue())

    duplicate = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(duplicate, "w") as archive:
        archive.writestr("same.txt", b"first")
        with pytest.warns(UserWarning, match="Duplicate name"):
            archive.writestr("same.txt", b"second")
    with pytest.raises(PipelineError, match="duplicate archive member"):
        validate_zip(duplicate)

    oversized = tmp_path / "oversized.zip"
    with zipfile.ZipFile(oversized, "w") as archive:
        archive.writestr("large", b"x" * 20)
    with pytest.raises(PipelineError, match="member size limit"):
        validate_zip(oversized, max_member_bytes=10)
    with pytest.raises(PipelineError, match="file-count limit"):
        validate_zip(oversized, max_files=0)

    target = tmp_path / "regular"
    target.write_bytes(b"ok")
    ensure_regular_file(target)
    with pytest.raises(PipelineError, match="regular file"):
        ensure_regular_file(tmp_path / "absent")
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(PipelineError, match="regular file"):
        ensure_regular_file(link)


def test_yaml_class_mapping_and_split_aliases_are_checked() -> None:
    assert _names_from_yaml("nc: 2\nnames: {0: pole, 1: tower}\n") == ["pole", "tower"]
    with pytest.raises(PipelineError, match="contiguous"):
        _names_from_yaml("nc: 2\nnames: {0: pole, 2: tower}\n")
    with pytest.raises(PipelineError, match="nc does not match"):
        _names_from_yaml("nc: 3\nnames: [pole, tower]\n")
    with pytest.raises(PipelineError, match="class names differ"):
        _names_from_yaml("nc: 1\nnames: [normal]\n", ["broken"])
    with pytest.raises(PipelineError, match="class names"):
        _names_from_yaml("nc: 0\nnames: []\n")
    with pytest.raises(PipelineError, match="data.yaml"):
        _names_from_yaml("!!python/object/apply:os.system ['true']")
    assert [normalize_split(split) for split in ("train", "valid", "validation", "test")] == [
        "train",
        "val",
        "val",
        "test",
    ]
    with pytest.raises(PipelineError, match="unsupported dataset split"):
        normalize_split("unknown")


def test_coco_xywh_and_xyxy_bad_geometry_reject_without_clipping() -> None:
    for bad in ([], [0, 0, 0, 1], [0, 0, float("nan"), 1], [-1, 0, 1, 1], [31, 0, 2, 1]):
        with pytest.raises(PipelineError):
            parse_coco_box(bad, width=30, height=20, class_id=0)
    for bad in ([], [0, 0, 0, 1], [0, 0, float("inf"), 1], [2, 0, 1, 1], [0, 0, 31, 21]):
        with pytest.raises(PipelineError):
            parse_xyxy_box(bad, width=30, height=20, class_id=0)


def test_archive_adapters_fail_closed_on_missing_or_inconsistent_source_data(tmp_path: Path) -> None:
    no_fold = tmp_path / "no-fold.zip"
    with zipfile.ZipFile(no_fold, "w") as archive:
        archive.writestr("OHL-UK/Dataset/Segmentation/Fold 0/data.json", "{}")
    with pytest.raises(PipelineError, match="Fold 0 object-detection"):
        list(iter_ohl_samples(no_fold))

    no_config = tmp_path / "no-config.zip"
    with zipfile.ZipFile(no_config, "w") as archive:
        archive.writestr("train/images/a.jpg", jpeg_bytes())
    with pytest.raises(PipelineError, match="data.yaml"):
        list(iter_roboflow_samples(no_config, ["pole"]))

    empty = tmp_path / "empty-roboflow.zip"
    with zipfile.ZipFile(empty, "w") as archive:
        archive.writestr("data.yaml", "names: [pole]\nnc: 1\n")
        archive.writestr("train/images/not-an-image.txt", "text")
    with pytest.raises(PipelineError, match="no split/images"):
        list(iter_roboflow_samples(empty, ["pole"]))

    mismatch = tmp_path / "coco-mismatch.zip"
    with zipfile.ZipFile(mismatch, "w") as archive:
        for split, category in (("train", "Pole"), ("val", "Sign")):
            base = f"OHL-UK/Dataset/Object Detection/Fold 0"
            document = {
                "images": [{"id": 1, "file_name": "a.jpg", "width": 30, "height": 20}],
                "categories": [{"id": 0, "name": category}],
                "annotations": [],
            }
            archive.writestr(f"{base}/annotations/{split}_fold0.json", json.dumps(document))
            image_split = "train_fold0" if split == "train" else "val_fold0"
            archive.writestr(f"{base}/images/{image_split}/a.jpg", jpeg_bytes())
    with pytest.raises(PipelineError, match="categories differ"):
        list(iter_ohl_samples(mismatch))


def test_directory_and_parquet_adapters_reject_untrusted_shapes(tmp_path: Path) -> None:
    missing_config = tmp_path / "missing-config"
    missing_config.mkdir()
    with pytest.raises(PipelineError, match="unsafe or missing"):
        list(iter_yolo_directory_samples(missing_config, ["pole"]))

    no_images = tmp_path / "no-images"
    no_images.mkdir()
    (no_images / "data.yaml").write_text("nc: 1\nnames: [pole]\n")
    with pytest.raises(PipelineError, match="no images"):
        list(iter_yolo_directory_samples(no_images, ["pole"]))

    malformed = tmp_path / "bad.parquet"
    pq.write_table(pa.table({"not_image": [1]}), malformed)
    samples, _ = iter_parquet_samples(malformed, "streetlevel", "train", ["pole"])
    with pytest.raises(PipelineError, match="unexpected"):
        list(samples)

    mismatch = tmp_path / "bad-labels.parquet"
    pq.write_table(
        pa.table(
            {
                "image": [{"bytes": jpeg_bytes(), "path": "x.jpg"}],
                "bboxes": [[[1.0, 2.0, 5.0, 8.0]]],
                "labels": [[],],
            }
        ),
        mismatch,
    )
    samples, _ = iter_parquet_samples(mismatch, "powerline", "train", ["class_0"])
    with pytest.raises(PipelineError, match="bbox/label count mismatch"):
        list(samples)


def test_normalization_preserves_exif_orientation_and_rejects_conflicting_duplicates(tmp_path: Path) -> None:
    image = jpeg_bytes(orientation=6)
    sample = Sample("train/a.jpg", "train", image, 30, 20, [Annotation(0, 0.5, 0.5, 0.5, 0.5)])
    output = tmp_path / "oriented"
    report = normalize_records("oriented", ["pole"], [sample], output)
    output_image = next((output / "images/train").iterdir())
    assert output_image.read_bytes() == image
    assert report["counts"]["exif_orientation_counts"] == {"6": 1}

    conflict = Sample("val/b.jpg", "val", image, 30, 20, [])
    with pytest.raises(PipelineError, match="conflicting labels"):
        normalize_records("oriented", ["pole"], [sample, conflict], tmp_path / "conflict")
    assert not (tmp_path / "conflict").exists()


def test_normalized_validation_detects_metadata_labels_and_duplicate_failures(tmp_path: Path) -> None:
    bad_dir = tmp_path / "not-a-dataset"
    bad_dir.mkdir()
    assert validate_dataset(bad_dir)["valid"] is False

    image = jpeg_bytes()
    sample = Sample("train/a.jpg", "train", image, 30, 20, [Annotation(0, 0.5, 0.5, 0.5, 0.5)])
    output = tmp_path / "valid"
    normalize_records("fixture", ["pole"], [sample], output)
    config = yaml.safe_load((output / "data.yaml").read_text())
    config["train"] = "../outside"
    (output / "data.yaml").write_text(yaml.safe_dump(config))
    report = validate_dataset(output)
    assert report["valid"] is False
    assert any("paths must be local" in error for error in report["errors"])

    config["train"] = "images/train"
    (output / "data.yaml").write_text(yaml.safe_dump(config))
    label = next((output / "labels/train").glob("*.txt"))
    label.unlink()
    report = validate_dataset(output)
    assert any("missing label file" in error for error in report["errors"])


def test_normalization_records_rejects_and_source_splits(tmp_path: Path) -> None:
    samples = [
        Sample("train/a.jpg", "train", jpeg_bytes(), 30, 20, []),
        Sample("val/b.jpg", "val", jpeg_bytes(orientation=2), 30, 20, []),
        Sample("test/c.jpg", "test", jpeg_bytes(orientation=3), 30, 20, []),
    ]
    rejects = [
        {
            "source_path": "train/bad",
            "split": "train",
            "reason": "out of bounds",
            "rejected_annotation_count": 1,
        }
    ]
    output = tmp_path / "source-splits"
    report = normalize_records("fixture", ["pole"], samples, output, rejected_records=rejects)
    assert report["evaluation_ready"] is True
    assert report["counts"]["rejected_records"] == 1
    assert json.loads((output / "rejects.json").read_text())[0]["reason"] == "out of bounds"
    assert validate_dataset(output)["valid"] is True


def test_normalize_rejects_bad_source_split_class_and_annotation_values(tmp_path: Path) -> None:
    image = jpeg_bytes()
    base = dict(source_path="x.jpg", image_bytes=image, width=30, height=20)
    for sample in (
        Sample(split="other", boxes=[], **base),
        Sample(split="train", boxes=[Annotation(1, 0.5, 0.5, 0.5, 0.5)], **base),
        Sample(split="train", boxes=[Annotation(0, 0.5, 0.5, 0.0, 0.5)], **base),
        Sample(split="train", boxes=[Annotation(0, float("nan"), 0.5, 0.5, 0.5)], **base),
    ):
        with pytest.raises(PipelineError):
            normalize_records("fixture", ["pole"], [sample], tmp_path / f"bad-{len(list(tmp_path.iterdir()))}")
