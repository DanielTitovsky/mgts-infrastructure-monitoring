from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path, PurePosixPath

from .errors import PipelineError
from .normalize import normalize_records, validate_dataset
from .registry import HUB_REPOSITORY, HUB_REVISION, SOURCE_IDS, SOURCE_SPECS, source_ids
from .sources import fetch_sources, inspect_source, source_inputs


DEFAULT_ARCHIVE_ROOT = Path(
    os.environ.get("MGTS_DATA_ARCHIVE_ROOT") or "/tmp/mgts-dataset-transfer"
)
DEFAULT_HUB_ROOT = Path(
    os.environ.get("MGTS_DATA_HUB_ROOT") or Path.home() / ".cache" / "mgts-infrastructure-datasets"
)


def _source_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--source",
        nargs="+",
        choices=("all", *SOURCE_IDS),
        default=["all"],
        help="source ID(s), or all (default: all)",
    )
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_ARCHIVE_ROOT)
    parser.add_argument("--hub-root", type=Path, default=DEFAULT_HUB_ROOT)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mgts-datasets",
        description="Inspect, fetch, normalize, and validate pinned MGTS research datasets.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    inspect = commands.add_parser("inspect", help="inspect source availability and numeric annotations")
    _source_arg(inspect)
    inspect.add_argument(
        "--strict-invalid",
        action="store_true",
        help="abort inspection on an invalid source annotation instead of reporting and rejecting its sample",
    )

    fetch = commands.add_parser("fetch", help="fetch pinned private Hugging Face source files read-only")
    _source_arg(fetch)

    normalize = commands.add_parser("normalize", help="create separate normalized YOLO datasets")
    _source_arg(normalize)
    normalize.add_argument("--output", required=True, type=Path, help="new output root (must not already exist)")
    normalize.add_argument(
        "--quarantine-invalid",
        action="store_true",
        help="explicitly allow Powerline Faults records with invalid XYXY annotations to be rejected and reported",
    )
    normalize.add_argument(
        "--strict-invalid",
        action="store_true",
        help="abort on any invalid source annotation instead of reporting and rejecting its sample",
    )

    validate = commands.add_parser("validate", help="validate a normalized dataset or multi-source output root")
    validate.add_argument("path", type=Path)
    return parser


def _dump(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False))


def _normalize(args: argparse.Namespace, selected: list[str]) -> dict[str, object]:
    output: Path = args.output.expanduser()
    if output.exists() or output.is_symlink():
        raise PipelineError(f"output already exists; refusing overwrite: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    datasets: dict[str, dict[str, object]] = {}
    try:
        for source_id in selected:
            classes, samples, metadata, rejects = source_inputs(
                source_id,
                args.archive_root.expanduser(),
                args.hub_root.expanduser(),
                quarantine_invalid=args.quarantine_invalid,
                strict_invalid=args.strict_invalid,
            )
            source_output = temporary_root / source_id
            report = normalize_records(
                source_id,
                classes,
                samples,
                source_output,
                source_metadata=metadata,
                rejected_records=rejects,
            )
            datasets[source_id] = {
                "path": source_id,
                "counts": report["counts"],
                "evaluation_ready": report["evaluation_ready"],
                "evaluation_missing_splits": report["evaluation_missing_splits"],
                "rejected_records": report["rejected_records"],
                "rejected_annotations": report["rejected_annotations"],
            }
        catalog = {
            "schema_version": 1,
            "collection_repository": HUB_REPOSITORY,
            "collection_revision": HUB_REVISION,
            "datasets": datasets,
            "source_vocabularies_are_separate": True,
            "scene_independence_claim": False,
        }
        (temporary_root / "NORMALIZATION.json").write_text(
            json.dumps(catalog, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        if output.exists() or output.is_symlink():
            raise PipelineError(f"output appeared during normalization; refusing overwrite: {output}")
        os.rename(temporary_root, output)
        return {"output": str(output), **catalog}
    except Exception:
        shutil.rmtree(temporary_root, ignore_errors=True)
        raise


def _validate_path(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_dir():
        return {"valid": False, "errors": ["output path is missing or unsafe"]}
    catalog_path = path / "NORMALIZATION.json"
    if not catalog_path.exists():
        return validate_dataset(path)
    try:
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"valid": False, "errors": ["cannot read NORMALIZATION.json"]}
    datasets = catalog.get("datasets") if isinstance(catalog, dict) else None
    if not isinstance(datasets, dict) or not datasets:
        return {"valid": False, "errors": ["NORMALIZATION.json has no dataset entries"]}
    reports: dict[str, object] = {}
    errors: list[str] = []
    for source_id, item in sorted(datasets.items()):
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            errors.append(f"invalid catalog entry for {source_id}")
            continue
        relative = PurePosixPath(item["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.parts != (source_id,):
            errors.append(f"unsafe catalog path for {source_id}")
            continue
        report = validate_dataset(path / source_id)
        reports[source_id] = report
        if not report["valid"]:
            errors.extend(f"{source_id}: {error}" for error in report["errors"])
    return {"valid": not errors, "datasets": reports, "errors": errors}


def run(args: argparse.Namespace) -> dict[str, object]:
    if args.command == "validate":
        return _validate_path(args.path.expanduser())
    try:
        selected = source_ids(args.source)
    except ValueError as exc:
        raise PipelineError(str(exc)) from exc
    archive_root = args.archive_root.expanduser()
    hub_root = args.hub_root.expanduser()
    if args.command == "fetch":
        return fetch_sources(selected, archive_root, hub_root)
    if args.command == "inspect":
        return {
            "collection_repository": HUB_REPOSITORY,
            "collection_revision": HUB_REVISION,
            "sources": {
                source_id: inspect_source(
                    source_id, archive_root, hub_root, strict_invalid=args.strict_invalid
                )
                for source_id in selected
            },
            "source_ids": list(SOURCE_SPECS),
        }
    if args.command == "normalize":
        return _normalize(args, selected)
    raise PipelineError(f"unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = run(args)
    except (PipelineError, OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    _dump(result)
    if args.command == "validate" and not result.get("valid", False):
        return 1
    return 0
