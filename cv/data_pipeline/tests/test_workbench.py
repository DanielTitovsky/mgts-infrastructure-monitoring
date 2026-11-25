from __future__ import annotations

import ast
from argparse import Namespace
from pathlib import Path

import pytest

from mgts_data_pipeline import workbench
from mgts_data_pipeline.errors import PipelineError


def test_unsubmitted_form_is_a_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_run(_args: Namespace) -> dict[str, object]:
        pytest.fail("the CLI must not run before explicit form submission")

    monkeypatch.setattr(workbench.cli, "run", unexpected_run)

    assert workbench.run_submission(None) is None


def test_submission_maps_selected_values_to_existing_cli(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    archive_root = tmp_path / "archives"
    hub_root = tmp_path / "hub"
    output = tmp_path / "normalized"
    observed: list[Namespace] = []

    def run(args: Namespace) -> dict[str, object]:
        observed.append(args)
        return {"status": "ok"}

    monkeypatch.setattr(workbench.cli, "run", run)
    result = workbench.run_submission(
        {
            "action": "normalize",
            "sources": ["pd_defect", "broken_poles_v2"],
            "archive_root": str(archive_root),
            "hub_root": str(hub_root),
            "output_path": str(output),
            "validation_path": "",
            "strict_invalid": True,
            "quarantine_invalid": True,
        }
    )

    assert result == {"status": "ok"}
    assert observed == [
        Namespace(
            command="normalize",
            source=["pd_defect", "broken_poles_v2"],
            archive_root=archive_root,
            hub_root=hub_root,
            output=output,
            quarantine_invalid=True,
            strict_invalid=True,
        )
    ]


def test_default_selection_is_one_known_working_source(tmp_path: Path) -> None:
    args = workbench.build_cli_args(
        "inspect",
        sources=["broken_poles_v2"],
        archive_root=tmp_path / "archives",
        hub_root=tmp_path / "hub",
    )

    assert args.source == ["broken_poles_v2"]
    assert args.strict_invalid is False


def test_inspect_and_fetch_preserve_action_specific_options(tmp_path: Path) -> None:
    inspect = workbench.build_cli_args(
        "inspect", sources=["broken_poles_v2"], strict_invalid=True, archive_root=tmp_path, hub_root=tmp_path
    )
    fetch = workbench.build_cli_args(
        "fetch", sources=["broken_poles_v2"], archive_root=tmp_path, hub_root=tmp_path
    )

    assert inspect.command == "inspect"
    assert inspect.strict_invalid is True
    assert fetch.command == "fetch"
    assert not hasattr(fetch, "strict_invalid")


def test_validate_requires_a_path_and_does_not_require_source_selection() -> None:
    with pytest.raises(PipelineError, match="normalized dataset path"):
        workbench.build_cli_args("validate", validation_path="")

    args = workbench.build_cli_args("validate", validation_path="~/normalized", sources=[])
    assert args == Namespace(command="validate", path=Path("~/normalized"))


@pytest.mark.parametrize(
    ("action", "values", "message"),
    [
        ("remove", {"sources": ["broken_poles_v2"]}, "unsupported action"),
        ("fetch", {"sources": []}, "select at least one source"),
        ("inspect", {"sources": ["all"]}, "select sources individually"),
        ("normalize", {"sources": ["broken_poles_v2"], "output_path": ""}, "new output path"),
        ("fetch", {"sources": ["not-a-dataset"]}, "unknown source"),
    ],
)
def test_invalid_submission_fails_before_cli(
    monkeypatch: pytest.MonkeyPatch,
    action: str,
    values: dict[str, object],
    message: str,
) -> None:
    def unexpected_run(_args: Namespace) -> dict[str, object]:
        pytest.fail("invalid form values must be rejected before invoking the CLI")

    monkeypatch.setattr(workbench.cli, "run", unexpected_run)
    with pytest.raises(PipelineError, match=message):
        workbench.run_submission({"action": action, **values})


def test_validate_submission_calls_cli_only_after_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[Namespace] = []
    monkeypatch.setattr(workbench.cli, "run", lambda args: observed.append(args) or {"valid": True})

    assert workbench.run_submission(None) is None
    assert observed == []
    result = workbench.run_submission({"action": "validate", "validation_path": "/tmp/sample"})

    assert result == {"valid": True}
    assert observed == [Namespace(command="validate", path=Path("/tmp/sample"))]


def test_notebook_runs_operations_only_from_a_submitted_form() -> None:
    notebook = Path(__file__).parents[1] / "notebooks" / "dataset_workbench.py"
    source = notebook.read_text(encoding="utf-8")
    tree = ast.parse(source)

    assert "mo.ui.form(" in source
    assert "submit_button_label=\"Выполнить выбранное действие\"" in source
    assert "if submitted_form.value is None:" in source
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "run_submission"
    ]
    assert len(calls) == 1
    assert isinstance(calls[0].args[0], ast.Attribute)
    assert calls[0].args[0].attr == "value"


def test_launcher_passes_auth_password_through_stdin_not_argv() -> None:
    launcher = Path(__file__).parents[1] / "workbench.sh"
    source = launcher.read_text(encoding="utf-8")
    serve = source.split("serve() {", maxsplit=1)[1].split("\n}\n\nstart()", maxsplit=1)[0]

    assert 'unset MARIMO_WORKBENCH_PASSWORD' in serve
    assert "--token-password-file -" in serve
    assert '<<<"$password"' in serve
    assert "/dev/fd/3" not in serve
    assert "--token-password " not in serve
    assert "access_token=)[^&[:space:]]+/\\1[REDACTED]" in serve
    assert "flock --nonblock --exclusive --close --conflict-exit-code 75" in source
    assert "start_locked) start_locked ;;" in source
