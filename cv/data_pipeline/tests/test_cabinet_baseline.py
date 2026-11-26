from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from mgts_data_pipeline import cabinet_baseline as baseline


class FakeEmbedder:
    task = "detect"

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def embed(self, **kwargs: object) -> list[list[float]]:
        self.calls.append(kwargs)
        image = kwargs["source"]
        pixel = image.getpixel((0, 0))
        if not isinstance(pixel, tuple):
            pixel = (pixel, pixel, pixel)
        return [[float(pixel[0]), float(pixel[1]), float(pixel[2]), 1.0]]


def _photo(path: Path, color: tuple[int, int, int]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 6), color=color).save(path, format="JPEG")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(root: Path, entries: list[dict[str, object]]) -> Path:
    path = root / "final-materials.json"
    path.write_text(
        json.dumps({"schema_version": 1, "samples": entries, "warnings": []}),
        encoding="utf-8",
    )
    return path


def _entry(
    root: Path,
    name: str,
    *,
    object_id: str,
    object_type: str,
    condition: str,
    color: tuple[int, int, int] | None = None,
) -> dict[str, object]:
    image_path = root / "photos" / name
    digest = _photo(image_path, color or (len(name) * 5 % 255, 80, 30))
    return {
        "image_path": f"photos/{name}",
        "object_type": object_type,
        "condition": condition,
        "object_id": object_id,
        "status": "ok",
        "description": "fixture",
        "sha256": digest,
        "split": "unassigned",
        "coordinates": None,
    }


def _build(
    tmp_path: Path,
    entries: list[dict[str, object]],
    *,
    model: FakeEmbedder | None = None,
    max_samples: int = 61,
) -> tuple[Path, FakeEmbedder]:
    manifest = _manifest(tmp_path, entries)
    checkpoint = tmp_path / "trusted.pt"
    checkpoint.write_bytes(b"trusted local checkpoint")
    target = tmp_path / "reference-index.json"
    instance = model or FakeEmbedder()
    report = baseline.build_reference_index(
        manifest,
        target,
        checkpoint,
        embedder_factory=lambda _path: instance,
        max_samples=max_samples,
    )
    assert report["build"]["record_count"] == min(
        max_samples,
        sum(
            entry["object_type"] != "unknown" and entry["condition"] != "unknown"
            for entry in entries
        ),
    )
    return target, instance


def test_build_index_uses_only_local_embedder_records_provenance_and_refuses_image_copy(
    tmp_path: Path,
) -> None:
    entries = [
        _entry(
            tmp_path,
            "cabinet-a.jpg",
            object_id="a",
            object_type="РЩ",
            condition="normal",
            color=(255, 0, 0),
        ),
        _entry(
            tmp_path,
            "cabinet-b.jpg",
            object_id="b",
            object_type="ТКШ",
            condition="coating_damage",
            color=(0, 255, 0),
        ),
        _entry(
            tmp_path,
            "unknown.jpg",
            object_id="c",
            object_type="unknown",
            condition="unknown",
        ),
    ]
    target, model = _build(tmp_path, entries)

    index = baseline.load_reference_index(target)
    assert index["schema_version"] == 1
    assert index["kind"] == "mgts-cabinet-reference-index"
    assert index["provenance"]["detector_outputs_used"] is False
    assert (
        index["provenance"]["checkpoint_sha256"]
        == hashlib.sha256(b"trusted local checkpoint").hexdigest()
    )
    assert (
        index["provenance"]["manifest_sha256"]
        == hashlib.sha256((tmp_path / "final-materials.json").read_bytes()).hexdigest()
    )
    assert len(index["records"]) == 2
    assert all(len(record["embedding"]) == 4 for record in index["records"])
    assert all(len(record["embedding"]) > 0 for record in index["records"])
    assert len(model.calls) == 2
    assert all(call["device"] == "cpu" for call in model.calls)
    assert all(call["save"] is False for call in model.calls)
    assert not any(
        path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
        for path in tmp_path.iterdir()
    )


def test_build_requires_existing_checkpoint_before_model_factory(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path, [])
    constructed: list[str] = []
    with pytest.raises(baseline.InferenceError, match="checkpoint is missing"):
        baseline.build_reference_index(
            manifest,
            tmp_path / "new.json",
            tmp_path / "missing.pt",
            embedder_factory=lambda path: constructed.append(path),
        )
    assert constructed == []
    assert not (tmp_path / "new.json").exists()


def test_build_rejects_manifest_path_escape_and_hash_mismatch(tmp_path: Path) -> None:
    manifest = _manifest(
        tmp_path,
        [
            {
                "image_path": "../outside.jpg",
                "object_type": "РЩ",
                "condition": "normal",
                "object_id": "x",
                "sha256": "0" * 64,
            }
        ],
    )
    checkpoint = tmp_path / "trusted.pt"
    checkpoint.write_bytes(b"checkpoint")
    with pytest.raises(baseline.InferenceError, match="manifest-relative"):
        baseline.build_reference_index(
            manifest,
            tmp_path / "index.json",
            checkpoint,
            embedder_factory=lambda _path: FakeEmbedder(),
        )

    item = _entry(
        tmp_path, "actual.jpg", object_id="x", object_type="РЩ", condition="normal"
    )
    item["sha256"] = "0" * 64
    manifest = _manifest(tmp_path, [item])
    with pytest.raises(baseline.InferenceError, match="SHA-256 does not match"):
        baseline.build_reference_index(
            manifest,
            tmp_path / "index.json",
            checkpoint,
            embedder_factory=lambda _path: FakeEmbedder(),
        )


def test_build_caps_reference_images_and_never_overwrites_index(tmp_path: Path) -> None:
    entries = [
        _entry(
            tmp_path, f"{i}.jpg", object_id=str(i), object_type="РЩ", condition="normal"
        )
        for i in range(3)
    ]
    target, model = _build(tmp_path, entries, max_samples=2)
    index = baseline.load_reference_index(target)
    assert len(index["records"]) == 2
    assert index["build"]["truncated"] is True
    assert len(model.calls) == 2

    with pytest.raises(baseline.InferenceError, match="refusing overwrite"):
        baseline.build_reference_index(
            _manifest(tmp_path, entries),
            target,
            tmp_path / "trusted.pt",
            embedder_factory=lambda _path: FakeEmbedder(),
        )


def test_embedding_is_validated_and_retrieval_is_conservative(tmp_path: Path) -> None:
    entries = [
        _entry(
            tmp_path,
            "a.jpg",
            object_id="a",
            object_type="РЩ",
            condition="normal",
            color=(255, 0, 0),
        ),
        _entry(
            tmp_path,
            "b.jpg",
            object_id="b",
            object_type="ТКШ",
            condition="coating_damage",
            color=(0, 255, 0),
        ),
    ]
    target, _ = _build(tmp_path, entries)
    index = baseline.load_reference_index(target)
    query = [1.0, 0.0, 0.0, 1 / 255]
    result = baseline.retrieve(index, query, top_k=2)
    assert result["needs_review"] is True
    assert result["similarity_is_probability"] is False
    assert result["tentative"]["condition"] == "normal"
    assert result["matches"][0]["sha256"] == entries[0]["sha256"]

    assert (
        baseline.retrieve(index, query, exclude_sha256=entries[0]["sha256"])["matches"][
            0
        ]["sha256"]
        == entries[1]["sha256"]
    )
    assert (
        baseline.retrieve(index, query, exclude_object_id="a")["matches"][0]["sha256"]
        == entries[1]["sha256"]
    )
    with pytest.raises(baseline.InferenceError, match="finite non-zero"):
        baseline.retrieve(index, [0, 0, 0, 0])
    with pytest.raises(baseline.InferenceError, match="dimension"):
        baseline.retrieve(index, [1, 2])
    with pytest.raises(baseline.InferenceError, match="finite non-zero"):
        baseline.retrieve(index, [1, float("nan"), 0, 1])


def test_leave_object_group_out_evaluation_excludes_same_id_and_exact_duplicates(
    tmp_path: Path,
) -> None:
    entries = [
        _entry(
            tmp_path,
            "a.jpg",
            object_id="shared",
            object_type="РЩ",
            condition="normal",
            color=(255, 0, 0),
        ),
        _entry(
            tmp_path,
            "a-copy.jpg",
            object_id="other",
            object_type="РЩ",
            condition="normal",
            color=(255, 0, 0),
        ),
        _entry(
            tmp_path,
            "same-object.jpg",
            object_id="shared",
            object_type="ТКШ",
            condition="coating_damage",
            color=(0, 0, 255),
        ),
        _entry(
            tmp_path,
            "reference.jpg",
            object_id="reference",
            object_type="РЩ",
            condition="normal",
            color=(0, 255, 0),
        ),
        _entry(
            tmp_path,
            "unknown.jpg",
            object_id="unknown",
            object_type="unknown",
            condition="unknown",
        ),
    ]
    # Make a-copy an exact duplicate of a to exercise content-connected groups.
    (tmp_path / "photos" / "a-copy.jpg").write_bytes(
        (tmp_path / "photos" / "a.jpg").read_bytes()
    )
    entries[1]["sha256"] = entries[0]["sha256"]
    index_path, _ = _build(tmp_path, entries)
    index = baseline.load_reference_index(index_path)

    first_group = [
        record
        for record in index["records"]
        if record["object_id"] in {"shared", "other"}
    ]
    assert len({record["group_id"] for record in first_group}) == 1
    report = baseline.evaluate_leave_group_out(index)
    assert report["group_isolation"] == "object_id_or_exact_sha256"
    assert report["groups"] == 2
    assert report["targets"]["condition"] == 4
    assert report["targets"]["object_type"] == 4
    assert report["metrics"]["condition"]["macro_f1"] is not None
    assert report["metrics"]["condition"]["confusion_matrix"]
    assert all(
        row["excluded_group_id"] not in row["matched_group_ids"]
        for row in report["folds"]
    )


def test_leave_group_out_has_explicit_empty_metrics_when_no_independent_reference(
    tmp_path: Path,
) -> None:
    entries = [
        _entry(
            tmp_path, "a.jpg", object_id="only", object_type="РЩ", condition="normal"
        )
    ]
    index_path, _ = _build(tmp_path, entries)
    report = baseline.evaluate_leave_group_out(index_path)
    assert report["metrics"]["condition"]["accuracy"] == 0
    assert report["metrics"]["condition"]["macro_f1"] == 0
    assert report["folds"][0]["match_count"] == 0


def test_load_index_rejects_corrupt_embedding_and_embed_photo_validates_model_output(
    tmp_path: Path,
) -> None:
    entries = [
        _entry(tmp_path, "a.jpg", object_id="a", object_type="РЩ", condition="normal")
    ]
    target, _ = _build(tmp_path, entries)
    broken = json.loads(target.read_text(encoding="utf-8"))
    broken["records"][0]["embedding"] = [0, 0, 0, 0]
    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text(json.dumps(broken), encoding="utf-8")
    with pytest.raises(baseline.InferenceError, match="finite non-zero"):
        baseline.load_reference_index(corrupt)

    photo = tmp_path / "photos" / "a.jpg"
    with pytest.raises(baseline.InferenceError, match="finite non-zero"):
        baseline.embed_photo(FakeEmbedderBad([0, 0]), "a.jpg", photo.read_bytes())


class FakeEmbedderBad:
    task = "detect"

    def __init__(self, values: list[float]) -> None:
        self.values = values

    def embed(self, **_kwargs: object) -> list[list[float]]:
        return [self.values]


def test_manifest_schema_and_image_size_limits_are_checked(tmp_path: Path) -> None:
    checkpoint = tmp_path / "trusted.pt"
    checkpoint.write_bytes(b"checkpoint")
    manifest = tmp_path / "bad.json"
    manifest.write_text(
        json.dumps({"schema_version": 9, "samples": []}), encoding="utf-8"
    )
    with pytest.raises(baseline.InferenceError, match="schema_version.*1"):
        baseline.build_reference_index(
            manifest,
            tmp_path / "out.json",
            checkpoint,
            embedder_factory=lambda _path: FakeEmbedder(),
        )

    huge = tmp_path / "huge.jpg"
    huge.write_bytes(b"x" * (baseline.MAX_IMAGE_BYTES + 1))
    with pytest.raises(baseline.InferenceError, match="10 MB limit"):
        baseline.embed_photo(FakeEmbedder(), huge.name, huge.read_bytes())


def test_model_loading_checks_checkpoint_type_failure_and_task(tmp_path: Path) -> None:
    with pytest.raises(baseline.InferenceError, match="checkpoint is missing"):
        baseline.load_embedder(tmp_path / "model.bin", lambda _path: FakeEmbedder())
    checkpoint = tmp_path / "model.pt"
    checkpoint.write_bytes(b"checkpoint")
    with pytest.raises(baseline.InferenceError, match="Could not load"):
        baseline.load_embedder(
            checkpoint,
            lambda _path: (_ for _ in ()).throw(RuntimeError("bad checkpoint")),
        )
    bad_model = FakeEmbedder()
    bad_model.task = "classify"
    with pytest.raises(baseline.InferenceError, match="detection checkpoint"):
        baseline.load_embedder(checkpoint, lambda _path: bad_model)


def test_embed_photo_rejects_wrong_task_embed_errors_and_bad_cardinality() -> None:
    photo = io.BytesIO()
    Image.new("RGB", (2, 2)).save(photo, format="PNG")
    model = FakeEmbedder()
    model.task = "classify"
    with pytest.raises(baseline.InferenceError, match="detection checkpoint"):
        baseline.embed_photo(model, "image.png", photo.getvalue())

    class FailingEmbedder(FakeEmbedder):
        def embed(self, **_kwargs: object) -> list[list[float]]:
            raise RuntimeError("inference")

    with pytest.raises(baseline.InferenceError, match="failed to extract"):
        baseline.embed_photo(FailingEmbedder(), "image.png", photo.getvalue())

    class TwoEmbeddings(FakeEmbedder):
        def embed(self, **_kwargs: object) -> list[list[float]]:
            return [[1.0], [1.0]]

    with pytest.raises(baseline.InferenceError, match="unexpected number"):
        baseline.embed_photo(TwoEmbeddings(), "image.png", photo.getvalue())


@pytest.mark.parametrize(
    ("entry_update", "message"),
    [
        ({"image_path": "photos\\bad.jpg"}, "invalid image_path"),
        ({"object_type": "pole"}, "unsupported label"),
        ({"condition": "unknown-condition"}, "unsupported label"),
        ({"object_id": " "}, "invalid object_id"),
        ({"sha256": "nope"}, "invalid sha256"),
    ],
)
def test_manifest_rejects_invalid_sample_fields(
    tmp_path: Path, entry_update: dict[str, str], message: str
) -> None:
    item = _entry(
        tmp_path, "photo.jpg", object_id="id", object_type="РЩ", condition="normal"
    )
    item.update(entry_update)
    manifest = _manifest(tmp_path, [item])
    checkpoint = tmp_path / "trusted.pt"
    checkpoint.write_bytes(b"checkpoint")
    with pytest.raises(baseline.InferenceError, match=message):
        baseline.build_reference_index(
            manifest,
            tmp_path / "index.json",
            checkpoint,
            embedder_factory=lambda _path: FakeEmbedder(),
        )


def test_manifest_rejects_symlink_escape_and_non_image_file(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside.jpg"
    outside.write_bytes(b"outside")
    (tmp_path / "photos").mkdir()
    (tmp_path / "photos" / "link.jpg").symlink_to(outside)
    manifest = _manifest(
        tmp_path,
        [
            {
                "image_path": "photos/link.jpg",
                "object_type": "РЩ",
                "condition": "normal",
                "object_id": "id",
                "sha256": hashlib.sha256(b"outside").hexdigest(),
            }
        ],
    )
    checkpoint = tmp_path / "trusted.pt"
    checkpoint.write_bytes(b"checkpoint")
    with pytest.raises(baseline.InferenceError, match="outside the manifest"):
        baseline.build_reference_index(
            manifest,
            tmp_path / "index.json",
            checkpoint,
            embedder_factory=lambda _path: FakeEmbedder(),
        )

    plain = tmp_path / "photos" / "readme.txt"
    plain.write_text("not an image")
    manifest = _manifest(
        tmp_path,
        [
            {
                "image_path": "photos/readme.txt",
                "object_type": "РЩ",
                "condition": "normal",
                "object_id": "id",
                "sha256": hashlib.sha256(plain.read_bytes()).hexdigest(),
            }
        ],
    )
    with pytest.raises(baseline.InferenceError, match="JPEG, PNG, or WebP"):
        baseline.build_reference_index(
            manifest,
            tmp_path / "index.json",
            checkpoint,
            embedder_factory=lambda _path: FakeEmbedder(),
        )


def test_retrieval_rejects_bad_index_topk_and_dimension_and_can_return_no_match(
    tmp_path: Path,
) -> None:
    entries = [
        _entry(tmp_path, "a.jpg", object_id="a", object_type="РЩ", condition="normal")
    ]
    target, _ = _build(tmp_path, entries)
    index = baseline.load_reference_index(target)
    with pytest.raises(baseline.InferenceError, match="positive integer"):
        baseline.retrieve(index, [1, 0, 0, 1], top_k=0)
    with pytest.raises(baseline.InferenceError, match="Unsupported"):
        baseline.retrieve({}, [1, 0, 0, 1])
    with pytest.raises(baseline.InferenceError, match="dimension"):
        baseline.retrieve(index, [1, 2])
    result = baseline.retrieve(index, [1, 0, 0, 1], exclude_object_id="a")
    assert result["matches"] == []
    assert result["tentative"] == {"object_type": None, "condition": None}


def test_leave_group_out_and_metrics_are_empty_for_empty_valid_index(
    tmp_path: Path,
) -> None:
    manifest = _manifest(tmp_path, [])
    checkpoint = tmp_path / "trusted.pt"
    checkpoint.write_bytes(b"checkpoint")
    target = tmp_path / "empty-index.json"
    baseline.build_reference_index(
        manifest, target, checkpoint, embedder_factory=lambda _path: FakeEmbedder()
    )
    report = baseline.evaluate_leave_group_out(target)
    assert report["reference_count"] == report["groups"] == 0
    assert report["metrics"]["condition"]["labels"] == []
    assert report["metrics"]["condition"]["accuracy"] == 0


def test_classification_metrics_count_unretrieved_predictions_as_false_negatives() -> (
    None
):
    result = baseline._classification_metrics(["normal", "normal"], ["normal", None])
    assert result["accuracy"] == 0.5
    assert result["macro_f1"] == pytest.approx(2 / 3)
    assert result["no_independent_reference"] == 1
    assert result["confusion_matrix"]["normal"]["unretrieved"] == 1


def test_index_reader_rejects_invalid_schema_dimensions_and_metadata(
    tmp_path: Path,
) -> None:
    base = {
        "schema_version": 1,
        "kind": baseline.INDEX_KIND,
        "records": [],
    }
    path = tmp_path / "index.json"
    path.write_text(json.dumps({**base, "kind": "wrong"}), encoding="utf-8")
    with pytest.raises(baseline.InferenceError, match="schema"):
        baseline.load_reference_index(path)

    record = {
        "embedding": [1.0, 0.0],
        "object_type": "РЩ",
        "condition": "normal",
        "object_id": "a",
        "sha256": "0" * 64,
        "group_id": "group",
        "image_path": "a.jpg",
    }
    path.write_text(
        json.dumps({**base, "records": [record, {**record, "embedding": [1.0]}]}),
        encoding="utf-8",
    )
    with pytest.raises(
        baseline.InferenceError, match="inconsistent embedding dimensions"
    ):
        baseline.load_reference_index(path)

    path.write_text(
        json.dumps({**base, "records": [{**record, "object_type": "unknown"}]}),
        encoding="utf-8",
    )
    with pytest.raises(baseline.InferenceError, match="invalid reference metadata"):
        baseline.load_reference_index(path)


def test_main_evaluate_prints_json_and_errors_are_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    manifest = _manifest(tmp_path, [])
    checkpoint = tmp_path / "trusted.pt"
    checkpoint.write_bytes(b"checkpoint")
    target = tmp_path / "index.json"
    baseline.build_reference_index(
        manifest, target, checkpoint, embedder_factory=lambda _path: FakeEmbedder()
    )
    assert baseline.main(["evaluate", str(target)]) == 0
    assert json.loads(capsys.readouterr().out)["reference_count"] == 0
    assert baseline.main(["evaluate", str(tmp_path / "missing.json")]) == 2
    assert "Could not read cabinet reference index" in capsys.readouterr().err


def test_cli_parser_exposes_build_evaluate_and_query() -> None:
    parser = baseline.build_parser()
    assert parser.parse_args(["evaluate", "index.json"]).command == "evaluate"
    assert (
        parser.parse_args(["build", "manifest.json", "index.json", "model.pt"]).command
        == "build"
    )
    assert (
        parser.parse_args(
            ["query", "index.json", "photo.jpg", "--checkpoint", "model.pt"]
        ).command
        == "query"
    )
