from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from mgts_data_pipeline import minio_materials


def _fixture() -> tuple[bytes, bytes, str]:
    from io import BytesIO

    from PIL import Image

    image = BytesIO()
    Image.new("RGB", (8, 6), color=(10, 20, 30)).save(image, format="PNG")
    image_bytes = image.getvalue()
    manifest = json.dumps(
        {
            "schema_version": 1,
            "samples": [
                {
                    "image_path": "organizer/photos/cabinet.png",
                    "object_type": "РЩ",
                    "condition": "normal",
                    "source_folder": "organizer/photos",
                    "object_id": "cabinet",
                    "status": "original spreadsheet labels",
                    "description": "Fixture row",
                    "sha256": hashlib.sha256(image_bytes).hexdigest(),
                    "width": 8,
                    "height": 6,
                    "split": "unassigned",
                    "bbox_annotations": None,
                }
            ],
            "warnings": [],
            "counts": {"samples": 1},
        },
        ensure_ascii=False,
    ).encode()
    return manifest, image_bytes, hashlib.sha256(image_bytes).hexdigest()


class FakeS3:
    def __init__(self, objects: dict[str, bytes], *, content_lengths: dict[str, int] | None = None) -> None:
        self.objects = objects
        self.content_lengths = content_lengths or {}
        self.calls: list[tuple[str, str]] = []

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self.calls.append((Bucket, Key))
        if Key not in self.objects:
            raise KeyError(Key)
        data = self.objects[Key]
        return {"Body": _Body(data), "ContentLength": self.content_lengths.get(Key, len(data))}


class _Body:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self, size: int = -1) -> bytes:
        return self.data if size < 0 else self.data[:size]

    def close(self) -> None:
        pass


def _set_env(monkeypatch: pytest.MonkeyPatch, cache: Path) -> None:
    monkeypatch.setenv("MGTS_DATASET_S3_ENDPOINT", "http://minio.test:9000")
    monkeypatch.setenv("MGTS_DATASET_S3_BUCKET", "mgts-hackathon")
    monkeypatch.setenv("MGTS_DATASET_S3_PREFIX", "final-2026")
    monkeypatch.setenv("MGTS_DATASET_S3_ACCESS_KEY", "read-only-user")
    monkeypatch.setenv("MGTS_DATASET_S3_SECRET_KEY", "not-a-real-secret")
    monkeypatch.setenv("MGTS_DATASET_S3_CACHE_DIR", str(cache))


def test_prepare_fetches_manifest_and_materializes_pinned_photo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest, image, _ = _fixture()
    client = FakeS3({
        "final-2026/final-materials.json": manifest,
        "final-2026/organizer/photos/cabinet.png": image,
    })
    _set_env(monkeypatch, tmp_path / "cache")
    monkeypatch.setattr(minio_materials, "_create_s3_client", lambda _config: client)

    result = Path(minio_materials.prepare_minio_materials_from_env())

    assert result.is_file()
    assert result.read_bytes() == manifest
    assert (result.parent / "organizer/photos/cabinet.png").read_bytes() == image
    assert client.calls == [
        ("mgts-hackathon", "final-2026/final-materials.json"),
        ("mgts-hackathon", "final-2026/organizer/photos/cabinet.png"),
    ]


def test_prepare_refetches_manifest_but_reuses_content_verified_photo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest, image, _ = _fixture()
    client = FakeS3({
        "final-2026/final-materials.json": manifest,
        "final-2026/organizer/photos/cabinet.png": image,
    })
    _set_env(monkeypatch, tmp_path / "cache")
    monkeypatch.setattr(minio_materials, "_create_s3_client", lambda _config: client)

    first = minio_materials.prepare_minio_materials_from_env()
    second = minio_materials.prepare_minio_materials_from_env()

    assert second == first
    assert client.calls.count(("mgts-hackathon", "final-2026/final-materials.json")) == 2
    assert client.calls.count(("mgts-hackathon", "final-2026/organizer/photos/cabinet.png")) == 1

    Path(first).parent.joinpath("organizer/photos/cabinet.png").write_bytes(b"corrupt")
    minio_materials.prepare_minio_materials_from_env()
    assert client.calls.count(("mgts-hackathon", "final-2026/organizer/photos/cabinet.png")) == 2
    assert Path(first).parent.joinpath("organizer/photos/cabinet.png").read_bytes() == image


def test_prepare_fails_closed_for_missing_config_without_local_fallback(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("MGTS_DATASET_S3_ENDPOINT", raising=False)
    monkeypatch.setenv("MGTS_FINAL_MANIFEST", str(tmp_path / "local-manifest.json"))
    monkeypatch.setattr(minio_materials, "_create_s3_client", lambda _config: pytest.fail("must not connect"))

    with pytest.raises(minio_materials.MinioMaterialsError, match="MGTS_DATASET_S3_ENDPOINT"):
        minio_materials.prepare_minio_materials_from_env()


@pytest.mark.parametrize(
    ("variable", "value", "message"),
    [
        ("MGTS_DATASET_S3_ENDPOINT", "ftp://minio.test", "ENDPOINT"),
        ("MGTS_DATASET_S3_ENDPOINT", "http://user:password@minio.test", "ENDPOINT"),
        ("MGTS_DATASET_S3_BUCKET", "bad_bucket", "BUCKET"),
        ("MGTS_DATASET_S3_PREFIX", "../outside", "PREFIX"),
        ("MGTS_DATASET_S3_ACCESS_KEY", "", "ACCESS_KEY"),
    ],
)
def test_prepare_rejects_invalid_s3_configuration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    variable: str,
    value: str,
    message: str,
) -> None:
    _set_env(monkeypatch, tmp_path / "cache")
    monkeypatch.setenv(variable, value)
    monkeypatch.setattr(minio_materials, "_create_s3_client", lambda _config: pytest.fail("must not connect"))

    with pytest.raises(minio_materials.MinioMaterialsError, match=message):
        minio_materials.prepare_minio_materials_from_env()


def test_prepare_rejects_bad_upstream_hash_and_wrong_transfer_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest, image, _ = _fixture()
    photo_key = "final-2026/organizer/photos/cabinet.png"
    _set_env(monkeypatch, tmp_path / "cache")
    client = FakeS3(
        {"final-2026/final-materials.json": manifest, photo_key: image},
        content_lengths={photo_key: len(image) + 1},
    )
    monkeypatch.setattr(minio_materials, "_create_s3_client", lambda _config: client)

    with pytest.raises(minio_materials.MinioMaterialsError, match="size"):
        minio_materials.prepare_minio_materials_from_env()

    client.content_lengths.clear()
    valid_manifest = json.loads(manifest)
    valid_manifest["samples"][0]["sha256"] = "0" * 64
    client.objects["final-2026/final-materials.json"] = json.dumps(valid_manifest).encode()
    with pytest.raises(minio_materials.MinioMaterialsError, match="SHA-256"):
        minio_materials.prepare_minio_materials_from_env()


def test_prepare_checks_manifest_size_when_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    manifest, image, _ = _fixture()
    photo_key = "final-2026/organizer/photos/cabinet.png"
    document = json.loads(manifest)
    document["samples"][0]["size_bytes"] = len(image) + 1
    manifest_with_size = json.dumps(document).encode()
    client = FakeS3({"final-2026/final-materials.json": manifest_with_size, photo_key: image})
    _set_env(monkeypatch, tmp_path / "cache")
    monkeypatch.setattr(minio_materials, "_create_s3_client", lambda _config: client)

    with pytest.raises(minio_materials.MinioMaterialsError, match="manifest"):
        minio_materials.prepare_minio_materials_from_env()


def test_prepare_rejects_unsafe_manifest_key_before_photo_download(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest, _, _ = _fixture()
    unsafe = json.loads(manifest)
    unsafe["samples"][0]["image_path"] = "../outside.png"
    client = FakeS3({"final-2026/final-materials.json": json.dumps(unsafe).encode()})
    _set_env(monkeypatch, tmp_path / "cache")
    monkeypatch.setattr(minio_materials, "_create_s3_client", lambda _config: client)

    with pytest.raises(minio_materials.MinioMaterialsError, match="manifest"):
        minio_materials.prepare_minio_materials_from_env()

    assert len(client.calls) == 1


def test_prepare_fails_when_upstream_photo_is_missing_even_if_local_manifest_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    manifest, _, _ = _fixture()
    local_manifest = tmp_path / "ordinary-local-manifest.json"
    local_manifest.write_bytes(manifest)
    client = FakeS3({"final-2026/final-materials.json": manifest})
    _set_env(monkeypatch, tmp_path / "cache")
    monkeypatch.setenv("MGTS_FINAL_MANIFEST", str(local_manifest))
    monkeypatch.setattr(minio_materials, "_create_s3_client", lambda _config: client)

    with pytest.raises(minio_materials.MinioMaterialsError, match="unable to fetch MinIO object"):
        minio_materials.prepare_minio_materials_from_env()

    manifest_digest = hashlib.sha256(manifest).hexdigest()
    assert not (tmp_path / "cache" / manifest_digest / "final-materials.json").exists()


def test_cli_print_path_outputs_only_the_verified_manifest_path(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        minio_materials,
        "_prepare",
        lambda **_: (Path("/cache/verified/final-materials.json"), 62),
    )

    minio_materials.main(["--print-path"])

    assert capsys.readouterr().out == "/cache/verified/final-materials.json\n"
