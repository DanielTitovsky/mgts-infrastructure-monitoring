from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from . import cli
from .errors import PipelineError
from .registry import source_ids


def _required_path(value: str | Path | None, label: str) -> Path:
    if value is None or not str(value).strip():
        raise PipelineError(f"provide a {label}")
    return Path(value)


def build_cli_args(
    action: str,
    *,
    sources: Sequence[str] | None = None,
    archive_root: str | Path = cli.DEFAULT_ARCHIVE_ROOT,
    hub_root: str | Path = cli.DEFAULT_HUB_ROOT,
    output_path: str | Path | None = None,
    validation_path: str | Path | None = None,
    strict_invalid: bool = False,
    quarantine_invalid: bool = False,
) -> argparse.Namespace:
    """Translate one explicitly submitted workbench form into the CLI API."""
    if action not in {"inspect", "fetch", "normalize", "validate"}:
        raise PipelineError(f"unsupported action: {action}")

    if action == "validate":
        return argparse.Namespace(
            command="validate",
            path=_required_path(validation_path, "normalized dataset path"),
        )

    if isinstance(sources, str):
        selected_sources = [sources]
    else:
        selected_sources = list(sources or [])
    if not selected_sources:
        raise PipelineError("select at least one source")
    if "all" in selected_sources:
        raise PipelineError("select sources individually; the all-source recipe is currently blocked")
    try:
        selected_sources = source_ids(selected_sources)
    except ValueError as exc:
        raise PipelineError(str(exc)) from exc

    shared = {
        "command": action,
        "source": selected_sources,
        "archive_root": _required_path(archive_root, "archive root"),
        "hub_root": _required_path(hub_root, "Hub cache root"),
    }
    if action == "fetch":
        return argparse.Namespace(**shared)
    if not isinstance(strict_invalid, bool) or not isinstance(quarantine_invalid, bool):
        raise PipelineError("invalid annotation flags must be booleans")
    if action == "inspect":
        return argparse.Namespace(**shared, strict_invalid=strict_invalid)
    return argparse.Namespace(
        **shared,
        output=_required_path(output_path, "new output path"),
        quarantine_invalid=quarantine_invalid,
        strict_invalid=strict_invalid,
    )


def run_submission(values: Mapping[str, Any] | None) -> dict[str, object] | None:
    """Run the existing CLI only for a submitted form; None is an inert state."""
    if values is None:
        return None
    args = build_cli_args(
        values.get("action"),
        sources=values.get("sources"),
        archive_root=values.get("archive_root", cli.DEFAULT_ARCHIVE_ROOT),
        hub_root=values.get("hub_root", cli.DEFAULT_HUB_ROOT),
        output_path=values.get("output_path"),
        validation_path=values.get("validation_path"),
        strict_invalid=values.get("strict_invalid", False),
        quarantine_invalid=values.get("quarantine_invalid", False),
    )
    return cli.run(args)
