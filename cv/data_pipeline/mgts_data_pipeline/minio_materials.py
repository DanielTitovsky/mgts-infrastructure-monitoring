"""Read the final materials manifest and pinned photos from MinIO into a cache."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any, Sequence
from urllib.parse import urlparse

from . import research
from .final_materials import _sheet_rows


DEFAULT_BUCKET = "mgts-hackathon"
DEFAULT_PREFIX = "final-2026"
DEFAULT_CACHE_DIR = Path("/data/archive/cache/mgts-final-minio")
MANIFEST_NAME = "final-materials.json"


class MinioMaterialsError(RuntimeError):
    """MinIO configuration, manifest, or material integrity failure."""


@dataclass(frozen=True)
class _Config:
    endpoint: str
    bucket: str
    prefix: str
    access_key: str = field(repr=False)
    secret_key: str = field(repr=False)
    cache_dir: Path


def _configuration_from_env() -> _Config:
    endpoint = os.environ.get("MGTS_DATASET_S3_ENDPOINT", "").strip()
    parsed_endpoint = urlparse(endpoint)
    if (
        not endpoint
        or parsed_endpoint.scheme not in {"http", "https"}
        or not parsed_endpoint.hostname
        or parsed_endpoint.username is not None
        or parsed_endpoint.password is not None
    ):
        raise MinioMaterialsError("MGTS_DATASET_S3_ENDPOINT must be an http(s) MinIO endpoint without embedded credentials")

    bucket = os.environ.get("MGTS_DATASET_S3_BUCKET", DEFAULT_BUCKET).strip()
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", bucket):
        raise MinioMaterialsError("MGTS_DATASET_S3_BUCKET is invalid")

    prefix = os.environ.get("MGTS_DATASET_S3_PREFIX", DEFAULT_PREFIX).strip()
    prefix_path = PurePosixPath(prefix)
    if (
        not prefix
        or prefix_path.is_absolute()
        or "\\" in prefix
        or any(part in {"", ".", ".."} for part in prefix.split("/"))
    ):
        raise MinioMaterialsError("MGTS_DATASET_S3_PREFIX must be a safe relative object prefix")

    access_key = os.environ.get("MGTS_DATASET_S3_ACCESS_KEY", "")
    secret_key = os.environ.get("MGTS_DATASET_S3_SECRET_KEY", "")
    if not access_key or not secret_key:
        raise MinioMaterialsError("MGTS_DATASET_S3_ACCESS_KEY and MGTS_DATASET_S3_SECRET_KEY are required")

    cache_dir = Path(os.environ.get("MGTS_DATASET_S3_CACHE_DIR", str(DEFAULT_CACHE_DIR))).expanduser()
    return _Config(endpoint, bucket, prefix, access_key, secret_key, cache_dir)


def _create_s3_client(config: _Config) -> Any:
    try:
        import boto3
        from botocore.config import Config as BotoConfig

        return boto3.client(
            "s3",
            endpoint_url=config.endpoint,
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
            region_name="us-east-1",
            config=BotoConfig(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
    except Exception:
        raise MinioMaterialsError("unable to initialize the configured MinIO client") from None


def _read_object(client: Any, config: _Config, key: str, *, max_bytes: int) -> bytes:
    try:
        response = client.get_object(Bucket=config.bucket, Key=key)
    except Exception:
        raise MinioMaterialsError(f"unable to fetch MinIO object {key!r}") from None

    body = response.get("Body")
    expected_size = response.get("ContentLength")
    if (
        body is None
        or isinstance(expected_size, bool)
        or not isinstance(expected_size, int)
        or expected_size < 0
        or expected_size > max_bytes
    ):
        if body is not None and hasattr(body, "close"):
            body.close()
        raise MinioMaterialsError(f"MinIO object {key!r} has an invalid or oversized ContentLength")

    try:
        contents = body.read(max_bytes + 1)
    except Exception:
        raise MinioMaterialsError(f"unable to read MinIO object {key!r}") from None
    finally:
        if hasattr(body, "close"):
            body.close()
    if len(contents) != expected_size:
        raise MinioMaterialsError(f"MinIO object {key!r} size does not match ContentLength")
    return contents


def _atomic_write(target: Path, contents: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_symlink():
        raise MinioMaterialsError(f"unsafe symlink in MinIO cache: {target.name}")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _verified_cached_file(path: Path, expected_sha256: str, expected_size: int | None) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        size = path.stat().st_size
        if size > research.MAX_IMAGE_BYTES or (expected_size is not None and size != expected_size):
            return False
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
        return digest.hexdigest() == expected_sha256
    except OSError:
        return False


def _safe_material_path(root: Path, image_path: str) -> Path:
    relative = PurePosixPath(image_path)
    if (
        not image_path
        or "\\" in image_path
        or relative.is_absolute()
        or any(part in {"", ".", ".."} for part in image_path.split("/"))
        or relative.suffix.lower() not in research.IMAGE_SUFFIXES
    ):
        raise MinioMaterialsError("manifest contains an unsafe image_path")

    target = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise MinioMaterialsError("manifest image_path traverses a cache symlink")
    try:
        target.resolve(strict=False).relative_to(root.resolve())
    except ValueError:
        raise MinioMaterialsError("manifest image_path escapes the local MinIO cache") from None
    return target


def _load_verified_manifest(contents: bytes, cache_dir: Path) -> dict[str, Any]:
    fd, temporary_name = tempfile.mkstemp(prefix=".manifest-validation-", suffix=".json", dir=cache_dir)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(contents)
        try:
            manifest = research.load_material_manifest(temporary)
        except research.ResearchError as error:
            raise MinioMaterialsError(f"MinIO materials manifest is invalid: {error}") from None
        for sample in manifest["samples"]:
            digest = sample.get("sha256")
            if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                raise MinioMaterialsError("MinIO materials manifest must pin a SHA-256 for every image")
            for field_name in ("size_bytes",):
                size = sample.get(field_name)
                if size is not None and (isinstance(size, bool) or not isinstance(size, int) or size < 0):
                    raise MinioMaterialsError(f"MinIO materials manifest has an invalid {field_name}")
        return manifest
    finally:
        temporary.unlink(missing_ok=True)


def _prepare_reports_and_labels(client, config, version_dir, manifest, manifest_digest):
    # These keys are operator-owned. Never let an S3 document choose arbitrary local paths.
    result_names = {"cabinet-boxes.json", "cabinet-final-index-v1.json", "cabinet-mlp-head-v1.json",
                    "cabinet-oof-predictions-v1.json", "comparison.json"}
    def get(suffix, limit):
        return _read_object(client, config, f"{config.prefix}/{suffix}", max_bytes=limit)
    labels = json.loads(get("labels/SOURCES.json", 512_000))
    truth = {(s["source_archive"], s["source_folder"], s["object_id"]):(s["status"], s["description"])
             for s in manifest["samples"] if s["condition"] != "unknown"}
    actual = {}
    if len(labels) != 6:
        raise MinioMaterialsError("Unexpected organizer workbook count")
    for item in labels:
        key = item["key"]
        if not key.startswith(config.prefix + "/labels/") or not key.endswith(".xlsx"):
            raise MinioMaterialsError("Unexpected workbook object key")
        raw = _read_object(client, config, key, max_bytes=1_000_000)
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise MinioMaterialsError("Organizer workbook SHA mismatch")
        for stem, status, description in _sheet_rows(raw):
            if stem and stem != "Имя файла":
                k = (PurePosixPath(item["source_url"]).name, str(PurePosixPath(item["zip_member"]).parent), stem)
                if k in actual:
                    raise MinioMaterialsError("Duplicate organizer label")
                actual[k] = (status, description)
    if actual != truth:
        raise MinioMaterialsError("Organizer XLSX labels do not match the selected manifest")
    sources = json.loads(get("predictions/v1/SOURCES.json", 128_000))
    if sources.get("manifest_sha256") != manifest_digest or set(sources["results"]) != result_names:
        raise MinioMaterialsError("Model outputs are not bound to the selected manifest")
    for name in sorted(result_names):
        raw = get("predictions/v1/" + name, 8_000_000)
        meta = sources["results"][name]
        if len(raw) != meta["bytes"] or hashlib.sha256(raw).hexdigest() != meta["sha256"]:
            raise MinioMaterialsError("Model output integrity failure: "+name)
        _atomic_write(version_dir/name, raw)


def _prepare(*, verify_reports=False) -> tuple[Path, int]:
    config = _configuration_from_env()
    try:
        if config.cache_dir.is_symlink():
            raise MinioMaterialsError("MinIO cache directory cannot be a symlink")
        config.cache_dir.mkdir(parents=True, exist_ok=True)
    except MinioMaterialsError:
        raise
    except OSError:
        raise MinioMaterialsError("unable to create the configured MinIO cache directory") from None

    client = _create_s3_client(config)
    manifest_key = f"{config.prefix}/{MANIFEST_NAME}"
    manifest_bytes = _read_object(client, config, manifest_key, max_bytes=research.MAX_MANIFEST_BYTES)
    try:
        manifest_digest = hashlib.sha256(manifest_bytes).hexdigest()
        version_dir = config.cache_dir / manifest_digest
        if version_dir.is_symlink():
            raise MinioMaterialsError("unsafe symlink in MinIO cache version directory")
        version_dir.mkdir(parents=True, exist_ok=True)
        manifest = _load_verified_manifest(manifest_bytes, version_dir)

        for sample in manifest["samples"]:
            image_path = str(sample["image_path"])
            expected_sha256 = str(sample["sha256"]).lower()
            expected_size_value = sample.get("size_bytes")
            expected_size = expected_size_value if isinstance(expected_size_value, int) else None
            target = _safe_material_path(version_dir, image_path)
            if _verified_cached_file(target, expected_sha256, expected_size):
                continue

            object_key = f"{config.prefix}/{image_path}"
            image_bytes = _read_object(client, config, object_key, max_bytes=research.MAX_IMAGE_BYTES)
            if expected_size is not None and len(image_bytes) != expected_size:
                raise MinioMaterialsError(f"MinIO object {object_key!r} size does not match the manifest")
            if hashlib.sha256(image_bytes).hexdigest() != expected_sha256:
                raise MinioMaterialsError(f"MinIO object {object_key!r} SHA-256 does not match the manifest")
            _atomic_write(target, image_bytes)

        if verify_reports:
            _prepare_reports_and_labels(client, config, version_dir, manifest, manifest_digest)
        manifest_path = version_dir / MANIFEST_NAME
        if manifest_path.is_symlink():
            raise MinioMaterialsError("manifest cache path cannot be a symlink")
        if not manifest_path.is_file() or manifest_path.read_bytes() != manifest_bytes:
            _atomic_write(manifest_path, manifest_bytes)
        return manifest_path, manifest["sample_count"]
    except MinioMaterialsError:
        raise
    except OSError:
        raise MinioMaterialsError("unable to prepare the verified MinIO materials cache") from None


def prepare_minio_materials_from_env() -> str:
    """Fetch the manifest and eagerly verify/cache every photo; never fall back locally."""
    manifest_path, _ = _prepare()
    return str(manifest_path)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--print-path", action="store_true", help="print only the verified manifest path")
    parser.add_argument("--verify-labels-and-models", action="store_true")
    args = parser.parse_args(argv)

    manifest_path, verified_count = _prepare(verify_reports=args.verify_labels_and_models)
    if args.print_path:
        print(manifest_path)
    else:
        print(json.dumps({"verified_materials": verified_count, "manifest": str(manifest_path)}))


if __name__ == "__main__":
    main()
