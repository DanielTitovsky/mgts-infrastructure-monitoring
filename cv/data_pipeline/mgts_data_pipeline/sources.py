from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Iterator

import pyarrow as pa
import pyarrow.parquet as pq

from .adapters import (
    iter_ohl_samples,
    iter_parquet_samples,
    iter_roboflow_samples,
    iter_yolo_directory_samples,
    roboflow_family_splits,
)
from .errors import PipelineError
from .models import Sample
from .registry import (
    HF_SOURCES,
    HUB_REPOSITORY,
    HUB_REVISION,
    SOURCE_SPECS,
    SourceSpec,
)
from .safeio import ensure_regular_file, hash_file


EXPECTED_LOCAL_SHA256 = {
    "ohl_uk": "1de42934b8e446b4229a38af501a76ca0e5ac574c81281e7362abdf5efbe639d",
    "utility_pole_y8w7k_v3": "1f621fac775109c6dfa51b9142baf0027a9f3b390ce59295adfb3e1b81950a4f",
    "broken_poles_v2": "50ff7ed26bf154ea4bf8bd82c7309046ab5772bf9968372b0180195c81e8727d",
}
EXPECTED_LOCAL_MANIFEST_SHA256 = {
    "ohl_uk": "355c3f61bfb2523a5dcf2c8fe852bdffd83e018611cf5662ea6dd77ad7f27a16",
    "utility_pole_y8w7k_v3": "a09cd617a946a782feaaac8c649b2bfa70d8e510981f67da6160f17bfecde41d",
    "broken_poles_v2": "04057357f1a3755431ff588918b4719d09149ebebb30d63a7da2de2b8f7c8abe",
}
EXPECTED_LOCAL_HUB_OIDS = {
    "ohl_uk": (
        "1de42934b8e446b4229a38af501a76ca0e5ac574c81281e7362abdf5efbe639d",
        "6fb68c3abf540f3ce8c4ac9d185405df05d382d2",
    ),
    "utility_pole_y8w7k_v3": (
        "1f621fac775109c6dfa51b9142baf0027a9f3b390ce59295adfb3e1b81950a4f",
        "2ba969c7971d7a29892c70877811ec039463cb58",
    ),
    "broken_poles_v2": (
        "50ff7ed26bf154ea4bf8bd82c7309046ab5772bf9968372b0180195c81e8727d",
        "79458b7db7bae89f20e6b5d3b70666a86150476d",
    ),
}
EXPECTED_UPSTREAM_REVISIONS = {
    "pd_defect": "b9c64b2f9615ef5ade71fceade7d9d31b0dc9416",
    "streetlevel_poles": "0352f0b2b067439ca3467994cb9938a42310a09e",
    "powerline_faults": "79a307bc40b0ccb9cc6bebd99d549e1b6b651be0",
}
LOCAL_RELATIVE_PATHS = {
    "ohl_uk": Path("OHL-UK.zip"),
    "utility_pole_y8w7k_v3": Path("roboflow/export-1.zip"),
    "broken_poles_v2": Path("roboflow/export-2.zip"),
}
SOURCE_MANIFEST_PATHS = {
    "ohl_uk": Path("manifest.json"),
    "utility_pole_y8w7k_v3": Path("roboflow/utility-pole-y8w7k.json"),
    "broken_poles_v2": Path("roboflow/broken-poles-1-efa9c.json"),
}
HUB_MANIFEST_NAME = ".mgts-fetch-manifest.json"


def local_archive_path(source_id: str, archive_root: Path) -> Path:
    try:
        return archive_root / LOCAL_RELATIVE_PATHS[source_id]
    except KeyError as exc:
        raise PipelineError(f"source does not use a local archive: {source_id}") from exc


def _local_asset_entries(source_id: str, archive_root: Path) -> list[dict[str, object]]:
    archive_path = local_archive_path(source_id, archive_root)
    manifest_path = archive_root / SOURCE_MANIFEST_PATHS[source_id]
    collection_paths = SOURCE_SPECS[source_id].collection_paths
    if len(collection_paths) != 2:
        raise PipelineError(f"incomplete pinned collection assets for {source_id}")
    return [
        {
            "path": archive_path,
            "collection_path": collection_paths[0],
            "sha256": EXPECTED_LOCAL_SHA256[source_id],
            "hub_oid": EXPECTED_LOCAL_HUB_OIDS[source_id][0],
            "kind": "archive",
        },
        {
            "path": manifest_path,
            "collection_path": collection_paths[1],
            "sha256": EXPECTED_LOCAL_MANIFEST_SHA256[source_id],
            "hub_oid": EXPECTED_LOCAL_HUB_OIDS[source_id][1],
            "kind": "source manifest",
        },
    ]


def _verify_local_file(path: Path, expected_sha256: str, description: str) -> str:
    ensure_regular_file(path)
    digest = hash_file(path)
    if digest != expected_sha256:
        raise PipelineError(f"source checksum mismatch for {description}: {path.name}")
    return digest


def _validate_local_source_manifest(source_id: str, manifest_path: Path) -> tuple[list[str], int | None]:
    source_manifest = _load_json(manifest_path, "source manifest")
    if source_id == "ohl_uk":
        if source_manifest.get("dataset") != "OHL-UK" or source_manifest.get("license") != "CC-BY-4.0":
            raise PipelineError("OHL source manifest does not match the pinned source")
        class_names = ["Pole", "Sign"]
        revision = None
    elif source_id == "utility_pole_y8w7k_v3":
        if source_manifest.get("project") != "utility-pole-y8w7k" or source_manifest.get("version") != 3:
            raise PipelineError("utility-pole source manifest does not match the pinned source")
        class_names = source_manifest.get("names")
        revision = 3
    elif source_id == "broken_poles_v2":
        if source_manifest.get("project") != "broken-poles-1-efa9c" or source_manifest.get("version") != 2:
            raise PipelineError("broken-poles source manifest does not match the pinned source")
        class_names = source_manifest.get("names")
        revision = 2
    else:
        raise PipelineError(f"source does not use a local manifest: {source_id}")
    if source_manifest.get("sha256") != EXPECTED_LOCAL_SHA256[source_id]:
        raise PipelineError(f"source manifest archive checksum mismatch for {source_id}")
    expected_classes = list(SOURCE_SPECS[source_id].classes)
    if class_names != expected_classes:
        raise PipelineError(f"source class mapping differs from pinned registry for {source_id}")
    return expected_classes, revision


def hub_source_root(source_id: str, hub_root: Path) -> Path:
    if source_id == "pd_defect":
        return hub_root / "pd-defect" / "pole_lean_assessment" / "object_detection"
    if source_id in {"streetlevel_poles", "powerline_faults"}:
        prefix = "streetlevel-poles" if source_id == "streetlevel_poles" else "powerline-faults"
        return hub_root / prefix
    raise PipelineError(f"source does not use the Hugging Face cache: {source_id}")


def _load_json(path: Path, description: str) -> dict[str, object]:
    ensure_regular_file(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise PipelineError(f"invalid {description}: {path.name}") from exc
    if not isinstance(value, dict):
        raise PipelineError(f"invalid {description}: expected a JSON object")
    return value


def local_source_metadata(source_id: str, archive_root: Path) -> dict[str, object]:
    source_path = local_archive_path(source_id, archive_root)
    actual_sha256 = _verify_local_file(
        source_path, EXPECTED_LOCAL_SHA256[source_id], f"archive for {source_id}"
    )
    manifest_path = archive_root / SOURCE_MANIFEST_PATHS[source_id]
    _verify_local_file(
        manifest_path,
        EXPECTED_LOCAL_MANIFEST_SHA256[source_id],
        f"source manifest for {source_id}",
    )
    expected_sha256 = EXPECTED_LOCAL_SHA256[source_id]
    class_names, revision = _validate_local_source_manifest(source_id, manifest_path)
    return {
        "source_id": source_id,
        "license": SOURCE_SPECS[source_id].license,
        "source_manifest": manifest_path.name,
        "archive_size_bytes": source_path.stat().st_size,
        "archive_sha256": actual_sha256,
        "pinned_sha256": expected_sha256,
        "source_version": revision,
        "class_names": class_names,
        "collection_repository": HUB_REPOSITORY,
        "collection_revision": HUB_REVISION,
        "collection_file": SOURCE_SPECS[source_id].collection_paths[0],
        "limitations": list(SOURCE_SPECS[source_id].limitations),
    }


def _git_blob_sha1(path: Path) -> str:
    size = path.stat().st_size
    digest = hashlib.sha1()
    digest.update(f"blob {size}\0".encode("ascii"))
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_local_asset(asset: dict[str, object]) -> None:
    path = Path(str(asset["path"]))
    digest = _verify_local_file(
        path, str(asset["sha256"]), f"existing {asset['kind']}"
    )
    actual_hub_oid = digest if asset["kind"] == "archive" else _git_blob_sha1(path)
    if actual_hub_oid != asset["hub_oid"]:
        raise PipelineError(f"source object ID mismatch for {path.name}")


def _powerline_class_names(path: Path) -> list[str]:
    try:
        schema = pq.read_schema(path)
        metadata = schema.metadata or {}
        encoded_features = metadata[b"huggingface"]
        features = json.loads(encoded_features.decode("utf-8"))["info"]["features"]
        label_feature = features["labels"]["feature"]
        names = label_feature["names"]
        is_class_label = label_feature.get("_type") == "ClassLabel"
    except (OSError, pa.ArrowException, KeyError, TypeError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PipelineError(f"Powerline Parquet ClassLabel mapping is missing or malformed: {path.name}") from exc
    expected = list(SOURCE_SPECS["powerline_faults"].classes)
    if (
        not is_class_label
        or not isinstance(names, list)
        or any(not isinstance(name, str) or not name.strip() for name in names)
        or len(set(names)) != len(names)
        or names != expected
    ):
        raise PipelineError(f"Powerline Parquet ClassLabel mapping differs from pinned registry: {path.name}")
    return names


def hf_source_metadata(source_id: str, hub_root: Path) -> tuple[dict[str, object], list[Path]]:
    if source_id not in HF_SOURCES:
        raise PipelineError(f"source does not use the Hugging Face cache: {source_id}")
    fetch_manifest_path = hub_root / HUB_MANIFEST_NAME
    fetch_manifest = _load_json(fetch_manifest_path, "fetch manifest")
    if fetch_manifest.get("repository") != HUB_REPOSITORY or fetch_manifest.get("revision") != HUB_REVISION:
        raise PipelineError("source cache is not pinned to the expected Hugging Face collection revision")
    source_entries = fetch_manifest.get("sources", {}).get(source_id) if isinstance(fetch_manifest.get("sources"), dict) else None
    if not isinstance(source_entries, dict) or not isinstance(source_entries.get("files"), list):
        raise PipelineError(f"{source_id} is not present in the pinned fetch manifest; run fetch first")
    inventory: list[dict[str, object]] = []
    paths: list[Path] = []
    for item in source_entries["files"]:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise PipelineError(f"malformed file inventory for {source_id}")
        relative = PurePosixPath(item["path"])
        if relative.is_absolute() or ".." in relative.parts or not relative.parts or relative.parts[0] != source_id.replace("_", "-"):
            if source_id == "pd_defect" and relative.parts[:1] == ("pd-defect",):
                pass
            elif source_id == "streetlevel_poles" and relative.parts[:1] == ("streetlevel-poles",):
                pass
            elif source_id == "powerline_faults" and relative.parts[:1] == ("powerline-faults",):
                pass
            else:
                raise PipelineError(f"unsafe or unrelated cached source path for {source_id}")
        path = hub_root.joinpath(*relative.parts)
        ensure_regular_file(path)
        if path.stat().st_size != item.get("size_bytes"):
            raise PipelineError(f"cached source file size changed: {relative.as_posix()}")
        digest = hash_file(path)
        if digest != item.get("sha256"):
            raise PipelineError(f"cached source file checksum changed: {relative.as_posix()}")
        paths.append(path)
        inventory.append(
            {
                "path": relative.as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": digest,
                "hub_oid": item.get("hub_oid"),
            }
        )
    if not inventory:
        raise PipelineError(f"no pinned source files found for {source_id}; run fetch first")
    prefix = {
        "pd_defect": "pd-defect",
        "streetlevel_poles": "streetlevel-poles",
        "powerline_faults": "powerline-faults",
    }[source_id]
    actual_paths = sorted(
        path.relative_to(hub_root).as_posix()
        for path in (hub_root / prefix).rglob("*")
        if path.is_file()
    )
    expected_paths = sorted(item["path"] for item in inventory)
    if actual_paths != expected_paths:
        raise PipelineError(f"cached file inventory changed for {source_id}; rerun fetch at the pinned revision")
    manifest_path = hub_root / prefix / "SOURCE.json"
    upstream_manifest = _load_json(manifest_path, "upstream source manifest")
    if upstream_manifest.get("revision") != EXPECTED_UPSTREAM_REVISIONS[source_id]:
        raise PipelineError(f"upstream revision mismatch for {source_id}")
    if source_id == "pd_defect":
        if upstream_manifest.get("source") != "EPDCL/pd-defect":
            raise PipelineError("PD-Defect source manifest does not match pinned origin")
    elif source_id == "streetlevel_poles":
        if upstream_manifest.get("source") != "hotosm/streetlevel-poles":
            raise PipelineError("Streetlevel source manifest does not match pinned origin")
    elif upstream_manifest.get("source") != "docmhvr/powerline-components-and-faults":
        raise PipelineError("Powerline Faults source manifest does not match pinned origin")
    metadata: dict[str, object] = {
        "source_id": source_id,
        "license": upstream_manifest.get("license", SOURCE_SPECS[source_id].license),
        "upstream_source": upstream_manifest.get("source"),
        "upstream_revision": upstream_manifest.get("revision"),
        "collection_repository": HUB_REPOSITORY,
        "collection_revision": HUB_REVISION,
        "fetch_source_record_sha256": hashlib.sha256(
            json.dumps(
                {
                    "repository": HUB_REPOSITORY,
                    "revision": HUB_REVISION,
                    "source_id": source_id,
                    "source": source_entries,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        "source_files": inventory,
        "source_file_count": len(inventory),
        "source_total_bytes": sum(int(item["size_bytes"]) for item in inventory),
        "limitations": list(SOURCE_SPECS[source_id].limitations),
    }
    return metadata, paths


def source_inputs(
    source_id: str,
    archive_root: Path,
    hub_root: Path,
    *,
    quarantine_invalid: bool = False,
    strict_invalid: bool = False,
) -> tuple[list[str], Iterator[Sample], dict[str, object], list[dict[str, object]]]:
    spec = SOURCE_SPECS[source_id]
    rejects: list[dict[str, object]] = []
    if source_id in {"ohl_uk", "utility_pole_y8w7k_v3", "broken_poles_v2"}:
        source_path = local_archive_path(source_id, archive_root)
        metadata = local_source_metadata(source_id, archive_root)
        if source_id == "ohl_uk":
            samples = iter_ohl_samples(
                source_path, rejected_records=rejects, strict_invalid=strict_invalid
            )
        else:
            family_splits = roboflow_family_splits(source_path)
            samples = iter_roboflow_samples(
                source_path,
                spec.classes,
                family_splits,
                rejected_records=rejects,
                strict_invalid=strict_invalid,
            )
        return list(spec.classes), samples, metadata, rejects
    metadata, files = hf_source_metadata(source_id, hub_root)
    source_root = hub_source_root(source_id, hub_root)
    classes = list(spec.classes)
    if source_id == "pd_defect":
        samples = iter_yolo_directory_samples(
            source_root,
            spec.classes,
            rejected_records=rejects,
            strict_invalid=strict_invalid,
        )
    else:
        format_name = "streetlevel" if source_id == "streetlevel_poles" else "powerline"
        parquet_paths = sorted(path for path in files if path.suffix.lower() == ".parquet")
        if not parquet_paths:
            raise PipelineError(f"no Parquet files in pinned source: {source_id}")
        if source_id == "powerline_faults":
            classes = _powerline_class_names(parquet_paths[0])
            for path in parquet_paths[1:]:
                _powerline_class_names(path)

        def parquet_samples() -> Iterator[Sample]:
            for path in parquet_paths:
                if source_id == "streetlevel_poles":
                    relative = path.relative_to(source_root / "data")
                    split_token = relative.parts[0]
                else:
                    split_token = path.name.split("-", 1)[0]
                samples_for_file, file_rejects = iter_parquet_samples(
                    path,
                    format_name,
                    split_token,
                    classes,
                    quarantine_invalid=quarantine_invalid,
                    strict_invalid=strict_invalid,
                )
                yield from samples_for_file
                rejects.extend(file_rejects)

        samples = parquet_samples()
    return classes, samples, metadata, rejects


def _local_source_fetch_result(source_id: str, archive_root: Path) -> dict[str, object]:
    files: list[dict[str, object]] = []
    for asset in _local_asset_entries(source_id, archive_root):
        path = Path(str(asset["path"]))
        files.append(
            {
                "path": path.relative_to(archive_root).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": asset["sha256"],
                "hub_oid": asset["hub_oid"],
                "collection_file": asset["collection_path"],
            }
        )
    return {"files": files, "status": "verified_local_original"}


def _inspect_local_assets(
    source_id: str, archive_root: Path
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    assets = _local_asset_entries(source_id, archive_root)
    missing: list[dict[str, object]] = []
    for asset in assets:
        path = Path(str(asset["path"]))
        if path.exists() or path.is_symlink():
            _verify_local_asset(asset)
            asset["present"] = True
        else:
            asset["present"] = False
            missing.append(asset)
    manifest = next(asset for asset in assets if asset["kind"] == "source manifest")
    if manifest["present"]:
        _validate_local_source_manifest(source_id, Path(str(manifest["path"])))
    return assets, missing


def _verify_local_hub_entry(asset: dict[str, object], info: object) -> None:
    actual_hub_oid = getattr(info, "lfs", None)
    actual_hub_oid = actual_hub_oid.sha256 if actual_hub_oid else getattr(info, "blob_id", None)
    if actual_hub_oid != asset["hub_oid"]:
        raise PipelineError(f"pinned collection object differs for {asset['collection_path']}")


def _fetch_missing_local_assets(
    missing_by_source: dict[str, list[dict[str, object]]],
    archive_root: Path,
    *,
    token: str,
    remote_siblings: dict[str, object],
    snapshot_download: Callable[..., object],
) -> None:
    for assets in missing_by_source.values():
        for asset in assets:
            collection_path = str(asset["collection_path"])
            info = remote_siblings.get(collection_path)
            if info is None:
                raise PipelineError(f"pinned collection is missing local source asset: {collection_path}")
            _verify_local_hub_entry(asset, info)
    archive_root.mkdir(parents=True, exist_ok=True)
    patterns = sorted(
        {str(asset["collection_path"]) for assets in missing_by_source.values() for asset in assets}
    )
    with tempfile.TemporaryDirectory(prefix=".mgts-datasets-fetch-", dir=archive_root) as temporary_root:
        snapshot_download(
            repo_id=HUB_REPOSITORY,
            repo_type="dataset",
            revision=HUB_REVISION,
            token=token,
            local_dir=temporary_root,
            allow_patterns=patterns,
        )
        staged_by_source: dict[str, dict[str, Path]] = {}
        for source_id, assets in missing_by_source.items():
            staged: dict[str, Path] = {}
            for asset in assets:
                collection_path = str(asset["collection_path"])
                stage_path = Path(temporary_root).joinpath(*PurePosixPath(collection_path).parts)
                _verify_local_file(stage_path, str(asset["sha256"]), f"downloaded {asset['kind']} for {source_id}")
                info = remote_siblings[collection_path]
                expected_size = getattr(info, "size", None)
                if expected_size is not None and stage_path.stat().st_size != expected_size:
                    raise PipelineError(f"downloaded file size differs from pinned collection: {collection_path}")
                if getattr(info, "lfs", None):
                    if info.lfs.sha256 != hash_file(stage_path):
                        raise PipelineError(f"downloaded file checksum differs from pinned collection: {collection_path}")
                elif _git_blob_sha1(stage_path) != info.blob_id:
                    raise PipelineError(f"downloaded file object ID differs from pinned collection: {collection_path}")
                staged[str(asset["kind"])] = stage_path
            manifest_asset = next(
                asset
                for asset in _local_asset_entries(source_id, archive_root)
                if asset["kind"] == "source manifest"
            )
            manifest_path = staged.get("source manifest", Path(str(manifest_asset["path"])))
            _validate_local_source_manifest(source_id, manifest_path)
            staged_by_source[source_id] = staged
        for source_id, assets in missing_by_source.items():
            for asset in assets:
                target = Path(str(asset["path"]))
                if target.exists() or target.is_symlink():
                    raise PipelineError(f"source asset appeared during fetch; refusing overwrite: {target.name}")
                target.parent.mkdir(parents=True, exist_ok=True)
                staged_path = staged_by_source[source_id][str(asset["kind"])]
                try:
                    os.link(staged_path, target)
                except FileExistsError as exc:
                    raise PipelineError(f"source asset appeared during fetch; refusing overwrite: {target.name}") from exc
                staged_path.unlink()


def fetch_sources(source_ids: Iterable[str], archive_root: Path, hub_root: Path) -> dict[str, object]:
    selected = list(source_ids)
    local_results: dict[str, object] = {}
    local_sources = [source_id for source_id in selected if source_id not in HF_SOURCES]
    missing_local: dict[str, list[dict[str, object]]] = {}
    for source_id in local_sources:
        _, missing = _inspect_local_assets(source_id, archive_root)
        if missing:
            missing_local[source_id] = missing
        else:
            local_results[source_id] = _local_source_fetch_result(source_id, archive_root)
    remote_sources = [source_id for source_id in selected if source_id in HF_SOURCES]
    if remote_sources or missing_local:
        token = os.environ.get("HF_TOKEN")
        if not token:
            raise PipelineError("HF_TOKEN is required to fetch missing files from the private dataset collection")
        try:
            from huggingface_hub import HfApi, snapshot_download

            api = HfApi(token=token)
            remote_info = api.dataset_info(HUB_REPOSITORY, revision=HUB_REVISION, files_metadata=True)
            if remote_info.sha != HUB_REVISION:
                raise PipelineError("Hugging Face returned a different collection revision")
            remote_siblings = {info.rfilename: info for info in remote_info.siblings}
            if missing_local:
                _fetch_missing_local_assets(
                    missing_local,
                    archive_root,
                    token=token,
                    remote_siblings=remote_siblings,
                    snapshot_download=snapshot_download,
                )
                for source_id in missing_local:
                    local_results[source_id] = _local_source_fetch_result(source_id, archive_root)
            if remote_sources:
                patterns = sorted(
                    {
                        pattern
                        for source_id in remote_sources
                        for pattern in SOURCE_SPECS[source_id].collection_paths
                    }
                )
                hub_root.mkdir(parents=True, exist_ok=True)
                snapshot_download(
                    repo_id=HUB_REPOSITORY,
                    repo_type="dataset",
                    revision=HUB_REVISION,
                    token=token,
                    local_dir=str(hub_root),
                    allow_patterns=patterns,
                )
        except PipelineError:
            raise
        except Exception as exc:
            raise PipelineError(f"Hugging Face fetch failed ({type(exc).__name__}); check HF_TOKEN and network") from exc
        for source_id in remote_sources:
            patterns = SOURCE_SPECS[source_id].collection_paths
            remote_entries = [
                info
                for info in remote_info.siblings
                if any(fnmatch.fnmatchcase(info.rfilename, pattern) for pattern in patterns)
            ]
            if not remote_entries:
                raise PipelineError(f"pinned collection has no files for {source_id}")
            inventory: list[dict[str, object]] = []
            for info in sorted(remote_entries, key=lambda row: row.rfilename):
                path = hub_root / info.rfilename
                ensure_regular_file(path)
                if info.size is not None and path.stat().st_size != info.size:
                    raise PipelineError(f"downloaded file size differs from pinned collection: {info.rfilename}")
                digest = hash_file(path)
                hub_oid = info.lfs.sha256 if info.lfs else info.blob_id
                if info.lfs and info.lfs.sha256 != digest:
                    raise PipelineError(f"downloaded file checksum differs from pinned collection: {info.rfilename}")
                if not info.lfs and _git_blob_sha1(path) != info.blob_id:
                    raise PipelineError(f"downloaded file object ID differs from pinned collection: {info.rfilename}")
                inventory.append(
                    {
                        "path": info.rfilename,
                        "size_bytes": path.stat().st_size,
                        "sha256": digest,
                        "hub_oid": hub_oid,
                    }
                )
            local_results[source_id] = {"files": inventory, "status": "verified_hub_revision"}
    hub_root.mkdir(parents=True, exist_ok=True)
    manifest_path = hub_root / HUB_MANIFEST_NAME
    previous: dict[str, object] = {}
    if manifest_path.exists():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            previous = {}
    stored_sources = previous.get("sources", {}) if previous.get("revision") == HUB_REVISION else {}
    if not isinstance(stored_sources, dict):
        stored_sources = {}
    stored_sources.update(local_results)
    for source_id in selected:
        if source_id not in stored_sources:
            raise PipelineError(f"fetch did not produce source state for {source_id}")
    manifest = {
        "schema_version": 1,
        "repository": HUB_REPOSITORY,
        "revision": HUB_REVISION,
        "sources": stored_sources,
    }
    fd, temporary_name = tempfile.mkstemp(prefix=f".{HUB_MANIFEST_NAME}.", dir=hub_root)
    os.close(fd)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, manifest_path)
    finally:
        temporary.unlink(missing_ok=True)
    return manifest


def inspect_source(
    source_id: str,
    archive_root: Path,
    hub_root: Path,
    *,
    strict_invalid: bool = False,
) -> dict[str, object]:
    spec: SourceSpec = SOURCE_SPECS[source_id]
    if source_id in {"ohl_uk", "utility_pole_y8w7k_v3", "broken_poles_v2"}:
        path = local_archive_path(source_id, archive_root)
        if not path.exists():
            return {
                "source_id": source_id,
                "title": spec.title,
                "availability": "missing_local_original",
                "expected_path": str(path),
                "classes": list(spec.classes),
                "limitations": list(spec.limitations),
            }
    else:
        try:
            metadata, _ = hf_source_metadata(source_id, hub_root)
        except PipelineError as exc:
            return {
                "source_id": source_id,
                "title": spec.title,
                "availability": "fetch_required",
                "expected_path": str(hub_source_root(source_id, hub_root)),
                "classes": list(spec.classes),
                "limitations": list(spec.limitations),
                "detail": str(exc),
            }
    classes, samples, metadata, rejects = source_inputs(
        source_id,
        archive_root,
        hub_root,
        quarantine_invalid=source_id == "powerline_faults" and not strict_invalid,
        strict_invalid=strict_invalid,
    )
    counts: Counter[str] = Counter()
    splits: Counter[str] = Counter()
    annotations: Counter[int] = Counter()
    formats: Counter[str] = Counter()
    for sample in samples:
        counts["images"] += 1
        splits[sample.split] += 1
        counts["annotations"] += len(sample.boxes)
        annotations.update(annotation.class_id for annotation in sample.boxes)
        formats.update(sample.format_counts)
    return {
        "source_id": source_id,
        "title": spec.title,
        "availability": "available_and_inspected",
        "source_metadata": metadata,
        "class_names": classes,
        "image_count": counts["images"],
        "annotation_count": counts["annotations"],
        "annotations_by_class_id": {str(key): value for key, value in sorted(annotations.items())},
        "images_by_split": dict(sorted(splits.items())),
        "annotation_formats": dict(sorted(formats.items())),
        "rejected_record_count": len(rejects),
        "rejected_annotation_count": sum(int(item.get("rejected_annotation_count", 0)) for item in rejects),
        "rejected_records": rejects,
        "limitations": list(spec.limitations),
        "scene_independence_claim": False,
    }
