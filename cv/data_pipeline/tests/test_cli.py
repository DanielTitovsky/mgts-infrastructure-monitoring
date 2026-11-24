from __future__ import annotations

import json
import runpy
import sys
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from mgts_data_pipeline import cli
from mgts_data_pipeline.errors import PipelineError
from mgts_data_pipeline.models import Annotation, Sample
from mgts_data_pipeline.registry import SOURCE_IDS, source_ids


def jpeg_bytes() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (20, 16), color=(12, 34, 56)).save(stream, format="JPEG")
    return stream.getvalue()


def test_registry_source_selection_is_deterministic() -> None:
    assert source_ids(["all"]) == list(SOURCE_IDS)
    assert source_ids([]) == list(SOURCE_IDS)
    assert source_ids(["streetlevel_poles", "ohl_uk", "streetlevel_poles"]) == ["streetlevel_poles", "ohl_uk"]
    with pytest.raises(ValueError, match="cannot be combined"):
        source_ids(["all", "ohl_uk"])
    with pytest.raises(ValueError, match="unknown source"):
        source_ids(["not-a-source"])


def test_cli_inspect_outputs_json_and_uses_selected_source(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(
        cli,
        "inspect_source",
        lambda source_id, *_, **__: {"source_id": source_id, "image_count": 3},
    )
    result = cli.main(["inspect", "--source", "ohl_uk"])
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert list(payload["sources"]) == ["ohl_uk"]
    assert payload["sources"]["ohl_uk"]["image_count"] == 3


def test_cli_fetch_passes_source_roots_and_selected_sources(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    recorded: dict[str, object] = {}

    def fetch(selected: list[str], archive_root: Path, hub_root: Path) -> dict[str, object]:
        recorded.update(selected=selected, archive_root=archive_root, hub_root=hub_root)
        return {"status": "verified"}

    monkeypatch.setattr(cli, "fetch_sources", fetch)
    assert cli.main(
        ["fetch", "--source", "ohl_uk", "--archive-root", str(tmp_path), "--hub-root", str(tmp_path / "hub")]
    ) == 0
    assert recorded["selected"] == ["ohl_uk"]
    assert json.loads(capsys.readouterr().out) == {"status": "verified"}


def test_cli_normalize_and_validate_multi_source_root(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    sample = Sample(
        "train/example.jpg",
        "train",
        jpeg_bytes(),
        20,
        16,
        [Annotation(0, 0.5, 0.5, 0.5, 0.5)],
    )
    seen_flags: list[tuple[bool, bool]] = []

    def source_inputs(
        _source_id: str,
        _archive_root: Path,
        _hub_root: Path,
        *,
        quarantine_invalid: bool,
        strict_invalid: bool,
    ) -> tuple[list[str], list[Sample], dict[str, object], list[dict[str, object]]]:
        seen_flags.append((quarantine_invalid, strict_invalid))
        return ["Pole"], [sample], {"revision": "fixture"}, []

    monkeypatch.setattr(cli, "source_inputs", source_inputs)
    output = tmp_path / "result"
    assert cli.main(["normalize", "--source", "ohl_uk", "--output", str(output), "--quarantine-invalid"]) == 0
    normalized = json.loads(capsys.readouterr().out)
    assert normalized["datasets"]["ohl_uk"]["evaluation_ready"] is False
    assert seen_flags == [(True, False)]

    assert cli.main(["validate", str(output)]) == 0
    validation = json.loads(capsys.readouterr().out)
    assert validation["valid"] is True
    assert validation["datasets"]["ohl_uk"]["image_count"] == 1


def test_cli_strict_invalid_flag_is_passed_to_inspect_and_normalize(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    sample = Sample("train/example.jpg", "train", jpeg_bytes(), 20, 16, [])
    observed: list[tuple[str, bool]] = []

    def inspect_source(source_id: str, *_args: object, strict_invalid: bool) -> dict[str, object]:
        observed.append((source_id, strict_invalid))
        return {"source_id": source_id, "availability": "available_and_inspected"}

    def source_inputs(
        source_id: str,
        _archive_root: Path,
        _hub_root: Path,
        *,
        quarantine_invalid: bool,
        strict_invalid: bool,
    ) -> tuple[list[str], list[Sample], dict[str, object], list[dict[str, object]]]:
        observed.append((source_id, strict_invalid))
        assert quarantine_invalid is False
        return ["Pole"], [sample], {"revision": "fixture"}, []

    monkeypatch.setattr(cli, "inspect_source", inspect_source)
    monkeypatch.setattr(cli, "source_inputs", source_inputs)
    assert cli.main(["inspect", "--source", "ohl_uk", "--strict-invalid"]) == 0
    capsys.readouterr()
    assert cli.main(
        ["normalize", "--source", "ohl_uk", "--output", str(tmp_path / "strict"), "--strict-invalid"]
    ) == 0
    capsys.readouterr()

    assert observed == [("ohl_uk", True), ("ohl_uk", True)]


def test_cli_refuses_existing_output_and_returns_failure_for_invalid_validation(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    occupied = tmp_path / "occupied"
    occupied.mkdir()
    assert cli.main(["normalize", "--source", "ohl_uk", "--output", str(occupied)]) == 2
    assert "refusing overwrite" in capsys.readouterr().err

    bad = tmp_path / "bad"
    bad.mkdir()
    assert cli.main(["validate", str(bad)]) == 1
    assert json.loads(capsys.readouterr().out)["valid"] is False


def test_cli_rejects_unsafe_multi_source_catalog_path(tmp_path: Path) -> None:
    output = tmp_path / "root"
    output.mkdir()
    (output / "NORMALIZATION.json").write_text(json.dumps({"datasets": {"ohl_uk": {"path": "../elsewhere"}}}))
    result = cli._validate_path(output)
    assert result["valid"] is False
    assert any("unsafe catalog path" in error for error in result["errors"])


def test_module_entrypoint_runs_argparse(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["mgts-datasets", "--help"])
    with pytest.raises(SystemExit) as exit_code:
        runpy.run_module("mgts_data_pipeline.__main__", run_name="__main__")
    assert exit_code.value.code == 0
    assert "inspect" in capsys.readouterr().out
