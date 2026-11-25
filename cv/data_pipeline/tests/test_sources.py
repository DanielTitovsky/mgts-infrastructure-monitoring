from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from PIL import Image
from io import BytesIO

from mgts_data_pipeline.errors import PipelineError
from mgts_data_pipeline.registry import HUB_REPOSITORY, HUB_REVISION, SOURCE_SPECS
from mgts_data_pipeline import sources
from mgts_data_pipeline.safeio import hash_file


UPSTREAM = sources.EXPECTED_UPSTREAM_REVISIONS
HUB_PREFIX = {
    "pd_defect": "pd-defect",
    "streetlevel_poles": "streetlevel-poles",
    "powerline_faults": "powerline-faults",
}


def jpeg_bytes() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (32, 24), color=(4, 15, 70)).save(stream, "JPEG")
    return stream.getvalue()


def git_blob_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    digest.update(f"blob {path.stat().st_size}\0".encode())
    digest.update(path.read_bytes())
    return digest.hexdigest()


def make_hub_cache(root: Path, source_id: str, files: dict[str, bytes]) -> dict[str, object]:
    prefix = HUB_PREFIX[source_id]
    inventory = []
    for relative, content in sorted(files.items()):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        inventory.append(
            {
                "path": relative,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "hub_oid": git_blob_sha1(path),
            }
        )
    fetch_manifest = {
        "schema_version": 1,
        "repository": HUB_REPOSITORY,
        "revision": HUB_REVISION,
        "sources": {source_id: {"files": inventory, "status": "verified_hub_revision"}},
    }
    (root / sources.HUB_MANIFEST_NAME).write_text(json.dumps(fetch_manifest), encoding="utf-8")
    return fetch_manifest


def source_manifest_bytes(source_id: str) -> bytes:
    if source_id == "pd_defect":
        manifest = {"source": "EPDCL/pd-defect", "revision": UPSTREAM[source_id], "license": "CC-BY-4.0"}
    elif source_id == "streetlevel_poles":
        manifest = {"source": "hotosm/streetlevel-poles", "revision": UPSTREAM[source_id], "note": "localization"}
    else:
        manifest = {"source": "docmhvr/powerline-components-and-faults", "revision": UPSTREAM[source_id], "note": "fault labels"}
    return json.dumps(manifest).encode()


def local_collection_payloads() -> tuple[dict[str, bytes], dict[str, str], dict[str, str]]:
    archive_bytes = {
        "ohl_uk": b"fixture OHL archive",
        "utility_pole_y8w7k_v3": b"fixture utility archive",
        "broken_poles_v2": b"fixture broken-poles archive",
    }
    archive_sha256 = {source_id: hashlib.sha256(data).hexdigest() for source_id, data in archive_bytes.items()}
    manifests = {
        "ohl_uk": {
            "dataset": "OHL-UK",
            "license": "CC-BY-4.0",
            "sha256": archive_sha256["ohl_uk"],
        },
        "utility_pole_y8w7k_v3": {
            "project": "utility-pole-y8w7k",
            "version": 3,
            "names": ["Compromised-Pole", "Stable"],
            "sha256": archive_sha256["utility_pole_y8w7k_v3"],
        },
        "broken_poles_v2": {
            "project": "broken-poles-1-efa9c",
            "version": 2,
            "names": ["broken", "normal"],
            "sha256": archive_sha256["broken_poles_v2"],
        },
    }
    collection_paths = {
        "ohl_uk": ("OHL-UK.zip", "manifest.json"),
        "utility_pole_y8w7k_v3": (
            "roboflow/utility-pole-y8w7k/v3/dataset.zip",
            "roboflow/utility-pole-y8w7k/v3/SOURCE.json",
        ),
        "broken_poles_v2": (
            "roboflow/broken-poles-1-efa9c/v2/dataset.zip",
            "roboflow/broken-poles-1-efa9c/v2/SOURCE.json",
        ),
    }
    payloads: dict[str, bytes] = {}
    manifest_sha256: dict[str, str] = {}
    for source_id, paths in collection_paths.items():
        manifest_bytes = json.dumps(manifests[source_id], sort_keys=True).encode()
        payloads[paths[0]] = archive_bytes[source_id]
        payloads[paths[1]] = manifest_bytes
        manifest_sha256[source_id] = hashlib.sha256(manifest_bytes).hexdigest()
    return payloads, archive_sha256, manifest_sha256


def local_collection_hub_oids(payloads: dict[str, bytes]) -> dict[str, tuple[str, str]]:
    paths = {
        "ohl_uk": ("OHL-UK.zip", "manifest.json"),
        "utility_pole_y8w7k_v3": (
            "roboflow/utility-pole-y8w7k/v3/dataset.zip",
            "roboflow/utility-pole-y8w7k/v3/SOURCE.json",
        ),
        "broken_poles_v2": (
            "roboflow/broken-poles-1-efa9c/v2/dataset.zip",
            "roboflow/broken-poles-1-efa9c/v2/SOURCE.json",
        ),
    }
    return {
        source_id: (
            hashlib.sha256(payloads[archive]).hexdigest(),
            hashlib.sha1(f"blob {len(payloads[manifest])}\0".encode() + payloads[manifest]).hexdigest(),
        )
        for source_id, (archive, manifest) in paths.items()
    }


def install_local_collection_mocks(
    monkeypatch: pytest.MonkeyPatch,
    payloads: dict[str, bytes],
    archive_sha256: dict[str, str],
    manifest_sha256: dict[str, str],
    snapshot_calls: list[list[str]] | None = None,
) -> None:
    monkeypatch.setattr(sources, "EXPECTED_LOCAL_SHA256", archive_sha256)
    monkeypatch.setattr(sources, "EXPECTED_LOCAL_MANIFEST_SHA256", manifest_sha256, raising=False)
    monkeypatch.setattr(sources, "EXPECTED_LOCAL_HUB_OIDS", local_collection_hub_oids(payloads))
    siblings = []
    for path, content in sorted(payloads.items()):
        siblings.append(
            SimpleNamespace(
                rfilename=path,
                size=len(content),
                blob_id=hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest(),
                lfs=SimpleNamespace(sha256=hashlib.sha256(content).hexdigest()) if path.endswith(".zip") else None,
            )
        )

    class FakeApi:
        def __init__(self, token: str) -> None:
            assert token == "synthetic-token"

        def dataset_info(self, repo_id: str, revision: str, files_metadata: bool) -> SimpleNamespace:
            assert repo_id == HUB_REPOSITORY
            assert revision == HUB_REVISION
            assert files_metadata is True
            return SimpleNamespace(sha=HUB_REVISION, siblings=siblings)

    def fake_snapshot_download(**kwargs: object) -> str:
        assert kwargs["repo_id"] == HUB_REPOSITORY
        assert kwargs["repo_type"] == "dataset"
        assert kwargs["revision"] == HUB_REVISION
        assert kwargs["token"] == "synthetic-token"
        local_root = Path(str(kwargs["local_dir"]))
        patterns = [str(path) for path in kwargs["allow_patterns"]]  # type: ignore[union-attr]
        if snapshot_calls is not None:
            snapshot_calls.append(patterns)
        for path in patterns:
            destination = local_root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payloads[path])
        return str(local_root)

    monkeypatch.setenv("HF_TOKEN", "synthetic-token")
    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "HfApi", FakeApi)
    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)


@pytest.mark.parametrize("source_id", sorted(UPSTREAM))
def test_hf_metadata_verifies_revision_inventory_and_file_hashes(tmp_path: Path, source_id: str) -> None:
    prefix = HUB_PREFIX[source_id]
    files = {
        f"{prefix}/SOURCE.json": source_manifest_bytes(source_id),
        f"{prefix}/README.md": b"dataset notes",
        f"{prefix}/data/train-00000.parquet": b"synthetic parquet placeholder",
    }
    make_hub_cache(tmp_path, source_id, files)

    metadata, paths = sources.hf_source_metadata(source_id, tmp_path)

    assert metadata["upstream_revision"] == UPSTREAM[source_id]
    assert metadata["source_file_count"] == 3
    assert len(paths) == 3
    assert metadata["fetch_source_record_sha256"]
    assert len(metadata["fetch_source_record_sha256"]) == 64


def test_hf_metadata_rejects_tampered_file_and_wrong_pinned_revision(tmp_path: Path) -> None:
    prefix = HUB_PREFIX["streetlevel_poles"]
    make_hub_cache(
        tmp_path,
        "streetlevel_poles",
        {f"{prefix}/SOURCE.json": source_manifest_bytes("streetlevel_poles"), f"{prefix}/README.md": b"ok"},
    )
    (tmp_path / prefix / "README.md").write_bytes(b"tampered")
    with pytest.raises(PipelineError, match="changed"):
        sources.hf_source_metadata("streetlevel_poles", tmp_path)

    manifest_path = tmp_path / sources.HUB_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text())
    manifest["revision"] = "0" * 40
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(PipelineError, match="not pinned"):
        sources.hf_source_metadata("streetlevel_poles", tmp_path)


@pytest.mark.parametrize(
    ("source_id", "manifest", "relative_archive"),
    [
        (
            "ohl_uk",
            {"dataset": "OHL-UK", "license": "CC-BY-4.0", "sha256": sources.EXPECTED_LOCAL_SHA256["ohl_uk"]},
            "OHL-UK.zip",
        ),
        (
            "utility_pole_y8w7k_v3",
            {
                "project": "utility-pole-y8w7k",
                "version": 3,
                "names": ["Compromised-Pole", "Stable"],
                "sha256": sources.EXPECTED_LOCAL_SHA256["utility_pole_y8w7k_v3"],
            },
            "roboflow/export-1.zip",
        ),
        (
            "broken_poles_v2",
            {
                "project": "broken-poles-1-efa9c",
                "version": 2,
                "names": ["broken", "normal"],
                "sha256": sources.EXPECTED_LOCAL_SHA256["broken_poles_v2"],
            },
            "roboflow/export-2.zip",
        ),
    ],
)
def test_local_source_metadata_checks_manifest_and_pinned_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_id: str,
    manifest: dict[str, object],
    relative_archive: str,
) -> None:
    archive = tmp_path / relative_archive
    archive.parent.mkdir(parents=True, exist_ok=True)
    archive.write_bytes(b"fixture original archive")
    manifest_path = tmp_path / sources.SOURCE_MANIFEST_PATHS[source_id]
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    expected = sources.EXPECTED_LOCAL_SHA256[source_id]
    monkeypatch.setattr(
        sources,
        "hash_file",
        lambda path: expected if path == archive else hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    )
    monkeypatch.setattr(
        sources,
        "EXPECTED_LOCAL_MANIFEST_SHA256",
        {source_id: hashlib.sha256(manifest_path.read_bytes()).hexdigest()},
    )

    metadata = sources.local_source_metadata(source_id, tmp_path)

    assert metadata["archive_sha256"] == expected
    assert metadata["class_names"] == list(SOURCE_SPECS[source_id].classes)


def test_local_source_metadata_fails_closed_on_changed_checksum(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    archive = tmp_path / "OHL-UK.zip"
    archive.write_bytes(b"changed")
    (tmp_path / "manifest.json").write_text(
        json.dumps(
            {
                "dataset": "OHL-UK",
                "license": "CC-BY-4.0",
                "sha256": sources.EXPECTED_LOCAL_SHA256["ohl_uk"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(sources, "hash_file", lambda _path: "bad")
    with pytest.raises(PipelineError, match="checksum mismatch"):
        sources.local_source_metadata("ohl_uk", tmp_path)


def test_source_inputs_hf_yolo_directory_and_parquet_splits(tmp_path: Path) -> None:
    pd_root = tmp_path / "pd-defect/pole_lean_assessment/object_detection"
    pd_files = {
        "pd-defect/SOURCE.json": source_manifest_bytes("pd_defect"),
        "pd-defect/pole_lean_assessment/object_detection/data.yaml": b"nc: 2\nnames: ['Leaned_Pole', 'Straight_Pole']\n",
        "pd-defect/pole_lean_assessment/object_detection/train/images/1.jpg": jpeg_bytes(),
        "pd-defect/pole_lean_assessment/object_detection/train/labels/1.txt": b"0 0.5 0.5 0.5 0.5\n",
    }
    make_hub_cache(tmp_path, "pd_defect", pd_files)
    classes, samples, metadata, rejects = sources.source_inputs("pd_defect", tmp_path, tmp_path)
    pd_samples = list(samples)
    assert classes == ["Leaned_Pole", "Straight_Pole"]
    assert len(pd_samples) == 1 and pd_samples[0].split == "train"
    assert metadata["upstream_revision"] == UPSTREAM["pd_defect"]
    assert rejects == []

    street_file = tmp_path / "streetlevel-poles/data/train/train-00000.parquet"
    street_file.parent.mkdir(parents=True)
    pq.write_table(
        pa.table(
            {
                "image": [{"bytes": jpeg_bytes(), "path": "pole.jpg"}],
                "width": [32],
                "height": [24],
                "objects": [{"bbox": [[2.0, 2.0, 10.0, 15.0]], "category": [0]}],
            }
        ),
        street_file,
    )
    street_manifest = tmp_path / "streetlevel-poles/SOURCE.json"
    street_manifest.write_bytes(source_manifest_bytes("streetlevel_poles"))
    street_entries = [
        {
            "path": path.relative_to(tmp_path).as_posix(),
            "size_bytes": path.stat().st_size,
            "sha256": hash_file(path),
            "hub_oid": None,
        }
        for path in sorted((tmp_path / "streetlevel-poles").rglob("*"))
        if path.is_file()
    ]
    (tmp_path / sources.HUB_MANIFEST_NAME).write_text(
        json.dumps(
            {
                "repository": HUB_REPOSITORY,
                "revision": HUB_REVISION,
                "sources": {"streetlevel_poles": {"files": street_entries}},
            }
        ),
        encoding="utf-8",
    )
    street_classes, street_samples, _, _ = sources.source_inputs("streetlevel_poles", tmp_path, tmp_path)
    assert street_classes == ["pole", "tower"]
    assert len(list(street_samples)) == 1


def test_fetch_sources_local_only_writes_verified_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payloads, archive_sha256, manifest_sha256 = local_collection_payloads()
    archive_root = tmp_path / "originals"
    monkeypatch.setattr(sources, "EXPECTED_LOCAL_SHA256", archive_sha256)
    monkeypatch.setattr(sources, "EXPECTED_LOCAL_MANIFEST_SHA256", manifest_sha256, raising=False)
    monkeypatch.setattr(sources, "EXPECTED_LOCAL_HUB_OIDS", local_collection_hub_oids(payloads))
    (archive_root / "OHL-UK.zip").parent.mkdir(parents=True)
    (archive_root / "OHL-UK.zip").write_bytes(payloads["OHL-UK.zip"])
    (archive_root / "manifest.json").write_bytes(payloads["manifest.json"])
    monkeypatch.delenv("HF_TOKEN", raising=False)

    result = sources.fetch_sources(["ohl_uk"], archive_root, tmp_path / "cache")

    assert result["sources"]["ohl_uk"]["status"] == "verified_local_original"
    state = json.loads((tmp_path / "cache" / sources.HUB_MANIFEST_NAME).read_text())
    assert state["revision"] == HUB_REVISION
    assert {row["path"] for row in state["sources"]["ohl_uk"]["files"]} == {
        "OHL-UK.zip",
        "manifest.json",
    }


def test_fetch_bootstraps_missing_local_archives_and_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads, archive_sha256, manifest_sha256 = local_collection_payloads()
    install_local_collection_mocks(monkeypatch, payloads, archive_sha256, manifest_sha256)
    archive_root = tmp_path / "custom-originals"
    sources_selected = ["ohl_uk", "utility_pole_y8w7k_v3", "broken_poles_v2"]

    result = sources.fetch_sources(sources_selected, archive_root, tmp_path / "cache")

    assert set(result["sources"]) == set(sources_selected)
    expected_hub_oids = local_collection_hub_oids(payloads)
    for source_id in sources_selected:
        archive_path = archive_root / sources.LOCAL_RELATIVE_PATHS[source_id]
        manifest_path = archive_root / sources.SOURCE_MANIFEST_PATHS[source_id]
        assert archive_path.read_bytes() == payloads[SOURCE_SPECS[source_id].collection_paths[0]]
        assert manifest_path.read_bytes() == payloads[SOURCE_SPECS[source_id].collection_paths[1]]
        assert sources.local_source_metadata(source_id, archive_root)["archive_sha256"] == archive_sha256[source_id]
        assert result["sources"][source_id]["status"] == "verified_local_original"
        inventory = {row["collection_file"]: row for row in result["sources"][source_id]["files"]}
        assert set(inventory) == set(SOURCE_SPECS[source_id].collection_paths)
        assert [inventory[path]["hub_oid"] for path in SOURCE_SPECS[source_id].collection_paths] == list(
            expected_hub_oids[source_id]
        )


def test_fetch_reuses_a_verified_local_archive_and_downloads_only_its_missing_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payloads, archive_sha256, manifest_sha256 = local_collection_payloads()
    snapshot_calls: list[list[str]] = []
    install_local_collection_mocks(monkeypatch, payloads, archive_sha256, manifest_sha256, snapshot_calls)
    archive_root = tmp_path / "partially-cached"
    archive_path = archive_root / sources.LOCAL_RELATIVE_PATHS["ohl_uk"]
    archive_path.parent.mkdir(parents=True)
    archive_path.write_bytes(payloads["OHL-UK.zip"])

    sources.fetch_sources(["ohl_uk"], archive_root, tmp_path / "cache")

    assert archive_path.read_bytes() == payloads["OHL-UK.zip"]
    assert (archive_root / sources.SOURCE_MANIFEST_PATHS["ohl_uk"]).read_bytes() == payloads["manifest.json"]
    assert snapshot_calls == [["manifest.json"]]


@pytest.mark.parametrize("asset_kind", ["archive", "source manifest"])
def test_fetch_rejects_mismatched_existing_asset_without_replacing_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, asset_kind: str
) -> None:
    _, archive_sha256, manifest_sha256 = local_collection_payloads()
    archive_root = tmp_path / "originals"
    relative_path = (
        sources.LOCAL_RELATIVE_PATHS["ohl_uk"]
        if asset_kind == "archive"
        else sources.SOURCE_MANIFEST_PATHS["ohl_uk"]
    )
    path = archive_root / relative_path
    path.parent.mkdir(parents=True)
    path.write_bytes(f"mismatched {asset_kind}".encode())
    monkeypatch.setattr(sources, "EXPECTED_LOCAL_SHA256", archive_sha256)
    monkeypatch.setattr(sources, "EXPECTED_LOCAL_MANIFEST_SHA256", manifest_sha256, raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    with pytest.raises(PipelineError, match="checksum mismatch"):
        sources.fetch_sources(["ohl_uk"], archive_root, tmp_path / "cache")

    assert path.read_bytes() == f"mismatched {asset_kind}".encode()


def test_fetch_requires_hf_token_only_when_local_assets_are_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    archive_root = tmp_path / "new-originals"

    with pytest.raises(PipelineError, match="HF_TOKEN"):
        sources.fetch_sources(["ohl_uk"], archive_root, tmp_path / "cache")

    assert not archive_root.exists()


@pytest.mark.parametrize(
    "class_names",
    [
        ["Broken Cable", "Broken Insulator", "Cable", "Insulators", "Tower", "Vegetation"],
        ["wrong", "class", "names", "must", "not", "pass"],
        None,
    ],
)
def test_powerline_classes_are_read_and_validated_from_parquet_metadata(
    tmp_path: Path, class_names: list[str] | None
) -> None:
    prefix = HUB_PREFIX["powerline_faults"]
    parquet_path = tmp_path / prefix / "data" / "train-00000-of-00001.parquet"
    parquet_path.parent.mkdir(parents=True)
    image_type = pa.struct([pa.field("bytes", pa.binary()), pa.field("path", pa.string())])
    table = pa.table(
        {
            "image": pa.array([{"bytes": jpeg_bytes(), "path": "example.jpg"}], type=image_type),
            "bboxes": pa.array([[]], type=pa.list_(pa.list_(pa.float32()))),
            "labels": pa.array([[]], type=pa.list_(pa.int64())),
        }
    )
    if class_names is not None:
        features = {
            "labels": {
                "feature": {"names": class_names, "_type": "ClassLabel"},
                "_type": "Sequence",
            }
        }
        table = table.replace_schema_metadata(
            {b"huggingface": json.dumps({"info": {"features": features}}).encode()}
        )
    pq.write_table(table, parquet_path)
    make_hub_cache(
        tmp_path,
        "powerline_faults",
        {
            f"{prefix}/SOURCE.json": source_manifest_bytes("powerline_faults"),
            f"{prefix}/README.md": b"dataset readme",
            parquet_path.relative_to(tmp_path).as_posix(): parquet_path.read_bytes(),
        },
    )

    if class_names == ["Broken Cable", "Broken Insulator", "Cable", "Insulators", "Tower", "Vegetation"]:
        classes, _, metadata, _ = sources.source_inputs(
            "powerline_faults", tmp_path, tmp_path, quarantine_invalid=True
        )
        assert classes == class_names
        assert metadata["upstream_revision"] == UPSTREAM["powerline_faults"]
    else:
        with pytest.raises(PipelineError, match="ClassLabel mapping"):
            sources.source_inputs("powerline_faults", tmp_path, tmp_path, quarantine_invalid=True)


def test_fetch_private_hub_uses_pinned_revision_and_records_checksums(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_id = "streetlevel_poles"
    prefix = HUB_PREFIX[source_id]
    content = {
        f"{prefix}/SOURCE.json": source_manifest_bytes(source_id),
        f"{prefix}/README.md": b"dataset readme",
        f"{prefix}/data/train/train-00000.parquet": b"fixture parquet",
    }
    metadata = []
    for path, data in sorted(content.items()):
        digest = hashlib.sha256(data).hexdigest()
        metadata.append(
            SimpleNamespace(
                rfilename=path,
                size=len(data),
                blob_id=hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest(),
                lfs=None,
            )
        )

    class FakeApi:
        def __init__(self, token: str) -> None:
            assert token == "synthetic-token"

        def dataset_info(self, repo_id: str, revision: str, files_metadata: bool) -> SimpleNamespace:
            assert repo_id == HUB_REPOSITORY
            assert revision == HUB_REVISION
            assert files_metadata is True
            return SimpleNamespace(sha=HUB_REVISION, siblings=metadata)

    def fake_snapshot_download(**kwargs: object) -> str:
        assert kwargs["revision"] == HUB_REVISION
        assert kwargs["repo_id"] == HUB_REPOSITORY
        local_root = Path(str(kwargs["local_dir"]))
        for path, data in content.items():
            destination = local_root / path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        return str(local_root)

    monkeypatch.setenv("HF_TOKEN", "synthetic-token")
    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "HfApi", FakeApi)
    monkeypatch.setattr(huggingface_hub, "snapshot_download", fake_snapshot_download)
    result = sources.fetch_sources([source_id], tmp_path, tmp_path / "cache")

    assert result["revision"] == HUB_REVISION
    assert result["sources"][source_id]["status"] == "verified_hub_revision"
    assert len(result["sources"][source_id]["files"]) == 3
    verified, paths = sources.hf_source_metadata(source_id, tmp_path / "cache")
    assert verified["source_file_count"] == 3
    assert len(paths) == 3


def test_fetch_hub_requires_token_and_sanitizes_network_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    with pytest.raises(PipelineError, match="HF_TOKEN"):
        sources.fetch_sources(["pd_defect"], tmp_path, tmp_path / "cache")

    class BrokenApi:
        def __init__(self, token: str) -> None:
            pass

        def dataset_info(self, **_kwargs: object) -> None:
            raise RuntimeError("secret-token-must-not-appear")

    monkeypatch.setenv("HF_TOKEN", "synthetic-token")
    import huggingface_hub

    monkeypatch.setattr(huggingface_hub, "HfApi", BrokenApi)
    with pytest.raises(PipelineError) as error:
        sources.fetch_sources(["pd_defect"], tmp_path, tmp_path / "cache")
    assert "secret-token-must-not-appear" not in str(error.value)


def test_inspect_source_reports_missing_and_counts_available_samples(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = sources.inspect_source("ohl_uk", tmp_path, tmp_path)
    assert missing["availability"] == "missing_local_original"

    archive = tmp_path / "OHL-UK.zip"
    archive.write_bytes(b"fixture")
    sample = SimpleNamespace(
        split="train",
        boxes=[SimpleNamespace(class_id=0), SimpleNamespace(class_id=1)],
        format_counts={"coco_xywh": 2},
    )
    monkeypatch.setattr(
        sources,
        "source_inputs",
        lambda *_args, **_kwargs: (["Pole", "Sign"], iter([sample]), {"sha256": "x"}, []),
    )
    report = sources.inspect_source("ohl_uk", tmp_path, tmp_path)
    assert report["availability"] == "available_and_inspected"
    assert report["image_count"] == 1
    assert report["annotation_count"] == 2
    assert report["images_by_split"] == {"train": 1}
