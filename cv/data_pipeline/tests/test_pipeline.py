from __future__ import annotations

import json
import math
import stat
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from PIL import Image
from io import BytesIO

from mgts_data_pipeline.adapters import (
    iter_ohl_samples,
    iter_parquet_samples,
    iter_roboflow_samples,
    iter_yolo_directory_samples,
    parse_coco_box,
    parse_yolo_row,
    parse_xyxy_box,
    roboflow_family_splits,
)
from mgts_data_pipeline.errors import PipelineError
from mgts_data_pipeline.models import Annotation, Sample
from mgts_data_pipeline.normalize import normalize_records, validate_dataset
from mgts_data_pipeline.safeio import validate_zip


def jpeg_bytes(size: tuple[int, int] = (32, 24)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, color=(5, 20, 90)).save(stream, format="JPEG")
    return stream.getvalue()


def make_coco_json(image_name: str = "p.jpg", image_id: int = 1) -> bytes:
    return json.dumps(
        {
            "images": [{"id": image_id, "file_name": image_name, "width": 32, "height": 24}],
            "categories": [{"id": 7, "name": "pole"}],
            "annotations": [
                {"id": 1, "image_id": image_id, "category_id": 7, "bbox": [4, 2, 12, 16]}
            ],
        }
    ).encode()


def write_parquet(path: Path, table: pa.Table) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path)


def test_parse_yolo_bbox_and_polygon_to_normalized_boxes() -> None:
    bbox, bbox_format = parse_yolo_row("0 0.5 0.5 0.25 0.5", class_count=2)
    polygon, polygon_format = parse_yolo_row(
        "1 0.25 0.25 0.75 0.25 0.5 0.75", class_count=2
    )

    assert bbox == Annotation(0, 0.5, 0.5, 0.25, 0.5)
    assert bbox_format == "bbox"
    assert polygon == Annotation(1, 0.5, 0.5, 0.5, 0.5)
    assert polygon_format == "polygon_to_bbox"


@pytest.mark.parametrize(
    "row",
    [
        "0 nan 0.5 0.2 0.2",
        "2 0.5 0.5 0.2 0.2",
        "0 0.5 0.5 2 0.2",
        "0 0.2 0.2 1.2 0.2 0.5 0.8",  # out-of-bounds polygon
        "0 0.5 0.5 0.2",  # malformed
    ],
)
def test_yolo_parser_rejects_bad_class_values_and_geometry(row: str) -> None:
    with pytest.raises(PipelineError):
        parse_yolo_row(row, class_count=2)


def test_coco_xywh_and_powerline_xyxy_convert_without_clipping() -> None:
    assert parse_coco_box([4, 2, 12, 16], width=32, height=24, class_id=0) == Annotation(
        0, 0.3125, 0.4166666666666667, 0.375, 0.6666666666666666
    )
    assert parse_xyxy_box([4, 2, 16, 18], width=32, height=24, class_id=3) == Annotation(
        3, 0.3125, 0.4166666666666667, 0.375, 0.6666666666666666
    )
    with pytest.raises(PipelineError, match="out of bounds"):
        parse_xyxy_box([-1, 2, 16, 18], width=32, height=24, class_id=0)


def test_safe_zip_rejects_traversal_symlinks_and_bombs(tmp_path: Path) -> None:
    traversal = tmp_path / "traversal.zip"
    with zipfile.ZipFile(traversal, "w") as archive:
        archive.writestr("../outside.txt", b"x")
    with pytest.raises(PipelineError, match="unsafe archive path"):
        validate_zip(traversal)

    link = tmp_path / "link.zip"
    info = zipfile.ZipInfo("safe/link")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(link, "w") as archive:
        archive.writestr(info, "target")
    with pytest.raises(PipelineError, match="symlink"):
        validate_zip(link)

    bomb = tmp_path / "bomb.zip"
    with zipfile.ZipFile(bomb, "w") as archive:
        archive.writestr("huge.txt", b"0" * 40_000)
    with pytest.raises(PipelineError, match="expansion limit"):
        validate_zip(bomb, max_uncompressed_bytes=10_000)


def test_ohl_selects_fold_zero_detection_only(tmp_path: Path) -> None:
    archive_path = tmp_path / "ohl.zip"
    image = jpeg_bytes()
    with zipfile.ZipFile(archive_path, "w") as archive:
        base = "OHL-UK/Dataset/Object Detection/Fold 0"
        for split in ("train", "val"):
            name = f"{base}/images/{split}_fold0/p.jpg"
            document = json.loads(make_coco_json().decode())
            document["images"][0]["file_name"] = "p.jpg"
            document["categories"] = [{"id": 7, "name": "Pole"}]
            archive.writestr(f"{base}/annotations/{split}_fold0.json", json.dumps(document))
            archive.writestr(name, image)
        archive.writestr(
            "OHL-UK/Dataset/Object Detection/Fold 1/annotations/train_fold1.json",
            make_coco_json(),
        )
        archive.writestr(
            "OHL-UK/Dataset/Segmentation/Fold 0/annotations/train_fold0.json",
            make_coco_json(),
        )

    samples = list(iter_ohl_samples(archive_path))
    assert [sample.split for sample in samples] == ["train", "val"]
    assert all(sample.source_path.startswith("OHL-UK/Dataset/Object Detection/Fold 0/") for sample in samples)


def test_ohl_rejects_only_invalid_coco_image_and_strict_mode_aborts(tmp_path: Path) -> None:
    archive_path = tmp_path / "ohl-invalid.zip"
    base = "OHL-UK/Dataset/Object Detection/Fold 0"
    with zipfile.ZipFile(archive_path, "w") as archive:
        train_doc = {
            "images": [
                {"id": 1, "file_name": "bad.jpg", "width": 32, "height": 24},
                {"id": 2, "file_name": "good.jpg", "width": 32, "height": 24},
            ],
            "categories": [{"id": 7, "name": "Pole"}],
            "annotations": [
                {"id": 1, "image_id": 1, "category_id": 7, "bbox": [30, 2, 10, 5]},
                {"id": 2, "image_id": 2, "category_id": 7, "bbox": [2, 2, 10, 5]},
            ],
        }
        val_doc = {
            "images": [{"id": 3, "file_name": "val.jpg", "width": 32, "height": 24}],
            "categories": [{"id": 7, "name": "Pole"}],
            "annotations": [],
        }
        archive.writestr(f"{base}/annotations/train_fold0.json", json.dumps(train_doc))
        archive.writestr(f"{base}/annotations/val_fold0.json", json.dumps(val_doc))
        for split, names in (("train_fold0", ["bad.jpg", "good.jpg"]), ("val_fold0", ["val.jpg"])):
            for name in names:
                archive.writestr(f"{base}/images/{split}/{name}", jpeg_bytes())

    rejected: list[dict[str, object]] = []
    samples = list(iter_ohl_samples(archive_path, rejected_records=rejected))

    assert [sample.source_path.rsplit("/", 1)[-1] for sample in samples] == ["good.jpg", "val.jpg"]
    assert rejected == [
        {
            "source_path": f"{base}/images/train_fold0/bad.jpg",
            "split": "train",
            "reason": "COCO bbox is out of bounds",
            "rejected_annotation_count": 1,
        }
    ]
    with pytest.raises(PipelineError, match="out of bounds"):
        list(iter_ohl_samples(archive_path, strict_invalid=True))


def test_roboflow_zip_converts_polygons_and_groups_families(tmp_path: Path) -> None:
    archive_path = tmp_path / "roboflow.zip"
    image = jpeg_bytes()
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("data.yaml", "names: [Stable]\nnc: 1\n")
        for split, suffix in (("train", "a"), ("valid", "b"), ("test", "c")):
            filename = f"{split}/images/family_jpg.rf.{suffix}.jpg"
            label = filename.replace("/images/", "/labels/").rsplit(".", 1)[0] + ".txt"
            archive.writestr(filename, image)
            archive.writestr(label, "0 0.25 0.25 0.75 0.25 0.5 0.75\n")

    family_splits = roboflow_family_splits(archive_path)
    samples = list(iter_roboflow_samples(archive_path, ["Stable"], family_splits))
    assert {sample.family_id for sample in samples} == {"family"}
    assert {sample.split for sample in samples} == {"train"}
    assert all(sample.format_counts["polygon_to_bbox"] == 1 for sample in samples)


def test_roboflow_rejects_bad_image_record_and_reports_it_by_default(tmp_path: Path) -> None:
    archive_path = tmp_path / "roboflow-invalid.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("data.yaml", "names: [Stable]\nnc: 1\n")
        for name, label in (
            ("bad", "0 0.99 0.5 0.2 0.2\n0 0.5 0.5 0.25 0.25\n"),
            ("good", "0 0.5 0.5 0.25 0.25\n"),
        ):
            image = f"train/images/{name}.jpg"
            archive.writestr(image, jpeg_bytes())
            archive.writestr(image.replace("/images/", "/labels/").rsplit(".", 1)[0] + ".txt", label)

    rejected: list[dict[str, object]] = []
    samples = list(iter_roboflow_samples(archive_path, ["Stable"], rejected_records=rejected))

    assert [sample.source_path for sample in samples] == ["train/images/good.jpg"]
    assert rejected == [
        {
            "source_path": "train/images/bad.jpg",
            "split": "train",
            "reason": "invalid YOLO row 1: YOLO bounding box is out of bounds",
            "rejected_annotation_count": 2,
        }
    ]
    with pytest.raises(PipelineError, match="out of bounds"):
        list(iter_roboflow_samples(archive_path, ["Stable"], strict_invalid=True))


def test_yolo_directory_pairs_images_and_labels_without_orientation_rewrite(tmp_path: Path) -> None:
    source = tmp_path / "pd"
    image = jpeg_bytes()
    (source / "train/images").mkdir(parents=True)
    (source / "train/labels").mkdir(parents=True)
    (source / "data.yaml").write_text("nc: 1\nnames: [Leaned_Pole]\n")
    (source / "train/images/1.jpg").write_bytes(image)
    (source / "train/labels/1.txt").write_text("0 0.5 0.5 0.25 0.5\n")

    samples = list(iter_yolo_directory_samples(source, ["Leaned_Pole"]))
    assert len(samples) == 1
    assert samples[0].image_bytes == image
    assert samples[0].split == "train"


def test_yolo_directory_rejects_invalid_image_record_and_reports_it_by_default(tmp_path: Path) -> None:
    source = tmp_path / "pd"
    source.mkdir()
    (source / "data.yaml").write_text("nc: 1\nnames: [Leaned_Pole]\n")
    for name, label in (
        ("bad", "0 0.99 0.5 0.2 0.2\n0 0.5 0.5 0.25 0.25\n"),
        ("good", "0 0.5 0.5 0.25 0.25\n"),
    ):
        (source / "train/images").mkdir(parents=True, exist_ok=True)
        (source / "train/labels").mkdir(parents=True, exist_ok=True)
        (source / f"train/images/{name}.jpg").write_bytes(jpeg_bytes())
        (source / f"train/labels/{name}.txt").write_text(label)

    rejected: list[dict[str, object]] = []
    samples = list(iter_yolo_directory_samples(source, ["Leaned_Pole"], rejected_records=rejected))

    assert [sample.source_path for sample in samples] == ["train/images/good.jpg"]
    assert rejected == [
        {
            "source_path": "train/images/bad.jpg",
            "split": "train",
            "reason": "invalid YOLO row 1: YOLO bounding box is out of bounds",
            "rejected_annotation_count": 2,
        }
    ]
    with pytest.raises(PipelineError, match="out of bounds"):
        list(iter_yolo_directory_samples(source, ["Leaned_Pole"], strict_invalid=True))


def test_streetlevel_parquet_reads_embedded_coco_xywh(tmp_path: Path) -> None:
    path = tmp_path / "train-00000.parquet"
    image = jpeg_bytes()
    write_parquet(
        path,
        pa.table(
            {
                "image": [{"bytes": image, "path": "fake.jpg"}],
                "image_id": ["pole-1"],
                "width": [32],
                "height": [24],
                "objects": [{"bbox": [[4.0, 2.0, 12.0, 16.0]], "category": [1]}],
            }
        ),
    )

    samples, rejects = iter_parquet_samples(path, "streetlevel", "train", ["pole", "tower"])
    assert rejects == []
    sample = next(iter(samples))
    assert sample.boxes == [Annotation(1, 0.3125, 0.4166666666666667, 0.375, 0.6666666666666666)]


def test_streetlevel_parquet_rejects_invalid_record_and_strict_mode_aborts(tmp_path: Path) -> None:
    path = tmp_path / "streetlevel-invalid.parquet"
    pq.write_table(
        pa.table(
            {
                "image": [
                    {"bytes": jpeg_bytes(), "path": "bad.jpg"},
                    {"bytes": jpeg_bytes(), "path": "good.jpg"},
                ],
                "width": [32, 32],
                "height": [24, 24],
                "objects": [
                    {"bbox": [[30.0, 2.0, 10.0, 5.0]], "category": [0]},
                    {"bbox": [[2.0, 2.0, 10.0, 5.0]], "category": [0]},
                ],
            }
        ),
        path,
    )

    samples, rejected = iter_parquet_samples(path, "streetlevel", "train", ["pole"])

    assert [sample.source_path for sample in samples] == [f"{path.name}#row-1"]
    assert rejected == [
        {
            "source_path": f"{path.name}#row-0",
            "split": "train",
            "reason": "COCO bbox is out of bounds",
            "rejected_annotation_count": 1,
        }
    ]
    strict_samples, _ = iter_parquet_samples(path, "streetlevel", "train", ["pole"], strict_invalid=True)
    with pytest.raises(PipelineError, match="out of bounds"):
        list(strict_samples)


def test_powerline_parquet_rejects_invalid_rows_or_quarantines_whole_record(tmp_path: Path) -> None:
    path = tmp_path / "powerline.parquet"
    image = jpeg_bytes()
    write_parquet(
        path,
        pa.table(
            {
                "image": [
                    {"bytes": image, "path": "good.jpg"},
                    {"bytes": jpeg_bytes((16, 16)), "path": "bad.jpg"},
                ],
                "bboxes": [[[1.0, 2.0, 8.0, 10.0]], [[-1.0, 2.0, 8.0, 10.0]]],
                "labels": [[2], [2]],
            }
        ),
    )
    strict_samples, _ = iter_parquet_samples(path, "powerline", "train", [f"class_{i}" for i in range(6)])
    with pytest.raises(PipelineError, match="out of bounds"):
        list(strict_samples)

    samples, rejects = iter_parquet_samples(
        path, "powerline", "train", [f"class_{i}" for i in range(6)], quarantine_invalid=True
    )
    accepted = list(samples)
    assert len(accepted) == 1
    assert len(rejects) == 1 and rejects[0]["source_path"].endswith("row-1")

    quarantined_samples, _ = iter_parquet_samples(
        path,
        "powerline",
        "train",
        [f"class_{i}" for i in range(6)],
        quarantine_invalid=True,
        strict_invalid=True,
    )
    with pytest.raises(PipelineError, match="out of bounds"):
        list(quarantined_samples)


def test_normalize_deduplicates_exact_bytes_deterministically_and_validates(tmp_path: Path) -> None:
    image = jpeg_bytes()
    sample = Sample("train/a.jpg", "train", image, 32, 24, [Annotation(0, 0.5, 0.5, 0.25, 0.5)])
    duplicate = Sample("val/b.jpg", "val", image, 32, 24, [Annotation(0, 0.5, 0.5, 0.25, 0.5)])
    output = tmp_path / "normalized"

    result = normalize_records(
        "fixture", ["pole"], [sample, duplicate], output, source_metadata={"revision": "fixture"}
    )
    assert result["counts"]["images_written"] == 1
    assert result["counts"]["exact_duplicates_removed"] == 1
    assert result["counts"]["images_by_split"] == {"train": 1}
    assert validate_dataset(output)["valid"] is True
    assert (output / "images/train").is_dir()
    assert not (output / "images/val").exists()

    second = tmp_path / "normalized-again"
    normalize_records("fixture", ["pole"], [sample, duplicate], second, source_metadata={"revision": "fixture"})
    first_hashes = sorted(p.name for p in output.rglob("*") if p.is_file())
    second_hashes = sorted(p.name for p in second.rglob("*") if p.is_file())
    assert first_hashes == second_hashes


def test_normalization_writes_rejected_record_audit(tmp_path: Path) -> None:
    sample = Sample("train/good.jpg", "train", jpeg_bytes(), 32, 24, [])
    rejected = [
        {
            "source_path": "train/bad.jpg",
            "split": "train",
            "reason": "YOLO bounding box is out of bounds",
            "rejected_annotation_count": 1,
        }
    ]

    report = normalize_records("fixture", ["pole"], [sample], tmp_path / "audited", rejected_records=rejected)

    assert report["counts"]["rejected_records"] == 1
    assert report["counts"]["rejected_annotations"] == 1
    assert json.loads((tmp_path / "audited/rejects.json").read_text()) == rejected
    manifest = json.loads((tmp_path / "audited/SOURCE.json").read_text())
    assert manifest["rejected_records"] == 1


def test_normalize_refuses_existing_output_and_invalid_sample_leaves_no_output(tmp_path: Path) -> None:
    image = jpeg_bytes()
    out = tmp_path / "existing"
    out.mkdir()
    with pytest.raises(PipelineError, match="already exists"):
        normalize_records("fixture", ["pole"], [], out)

    invalid = tmp_path / "invalid"
    sample = Sample("x.jpg", "train", b"not-an-image", 32, 24, [])
    with pytest.raises(PipelineError, match="image bytes"):
        normalize_records("fixture", ["pole"], [sample], invalid)
    assert not invalid.exists()


def test_validator_detects_corrupt_label_rows(tmp_path: Path) -> None:
    image = jpeg_bytes()
    sample = Sample("train/a.jpg", "train", image, 32, 24, [Annotation(0, 0.5, 0.5, 0.25, 0.5)])
    output = tmp_path / "normalized"
    normalize_records("fixture", ["pole"], [sample], output)
    label = next((output / "labels/train").glob("*.txt"))
    label.write_text("0 nan 0 1 1\n")

    report = validate_dataset(output)
    assert report["valid"] is False
    assert any("non-finite" in error for error in report["errors"])


def test_yaml_uses_its_own_directory_not_ultralytics_global_root(tmp_path: Path) -> None:
    import yaml
    output = tmp_path / 'portable'
    normalize_records('fixture', ['pole'], [Sample('a.jpg', 'train', jpeg_bytes(), 32, 24, [])], output)
    config = yaml.safe_load((output / 'data.yaml').read_text())
    # Ultralytics resolves an explicit relative path against its global datasets
    # directory; omitting it lets an absolute YAML filename determine the root.
    assert 'path' not in config
    assert validate_dataset(output)['valid']


def test_boundary_box_serialization_preserves_valid_float_geometry(tmp_path: Path) -> None:
    width = 21 / 10001
    sample = Sample('boundary.jpg', 'train', jpeg_bytes(), 32, 24,
                    [Annotation(0, width / 2, .5, width, .5)])
    output = tmp_path / 'boundary'
    normalize_records('fixture', ['pole'], [sample], output)
    assert validate_dataset(output)['valid']
