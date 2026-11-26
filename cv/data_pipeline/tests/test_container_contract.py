from __future__ import annotations

import importlib
import os
import shlex
import subprocess
from pathlib import Path

import pytest
import yaml

from mgts_data_pipeline import cli, workbench


REPOSITORY_ROOT = Path(__file__).parents[3]


def _container_entrypoint_fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, dict[str, str]]:
    pipeline_root = REPOSITORY_ROOT / "cv" / "data_pipeline"
    source = tmp_path / "bundled.py"
    notebook = tmp_path / "persistent" / "cabinet_gallery.md"
    script = (pipeline_root / "container-entrypoint.sh").read_text(encoding="utf-8")
    script = script.replace(
        'NOTEBOOK_SOURCE="/app/notebooks/cabinet_gallery.md"',
        f"NOTEBOOK_SOURCE={shlex.quote(str(source))}",
    ).replace(
        'NOTEBOOK_PATH="/data/notebooks/cabinet_gallery.md"',
        f"NOTEBOOK_PATH={shlex.quote(str(notebook))}",
    )
    test_entrypoint = tmp_path / "container-entrypoint.sh"
    test_entrypoint.write_text(script, encoding="utf-8")
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    marimo_stub = stub_dir / "marimo"
    marimo_stub.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$MARIMO_ARGS_FILE"\n',
        encoding="utf-8",
    )
    marimo_stub.chmod(0o755)
    python_stub = stub_dir / "python"
    python_stub.write_text(
        '#!/bin/sh\nprintf \'%s\\n\' "$@" > "$MARIMO_AI_CONFIG_ARGS_FILE"\n',
        encoding="utf-8",
    )
    python_stub.chmod(0o755)
    secret = tmp_path / "password"
    secret.write_text("not-a-real-password\n", encoding="utf-8")
    args_file = tmp_path / "marimo-args"
    env = {
        **os.environ,
        "PATH": f"{stub_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "MARIMO_PASSWORD_FILE": str(secret),
        "MARIMO_ARGS_FILE": str(args_file),
        "MARIMO_AI_CONFIG_ARGS_FILE": str(tmp_path / "marimo-ai-config-args"),
        "MARIMO_PORT": "8790",
    }
    return test_entrypoint, source, notebook, secret, args_file, env


def test_configured_persistent_roots_are_used_by_cli_and_workbench(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    with monkeypatch.context() as scoped:
        scoped.setenv("MGTS_DATA_ARCHIVE_ROOT", str(tmp_path / "archives"))
        scoped.setenv("MGTS_DATA_HUB_ROOT", str(tmp_path / "hub"))
        scoped.setenv("MGTS_DATA_OUTPUT_ROOT", str(tmp_path / "output"))
        importlib.reload(cli)
        importlib.reload(workbench)

        assert cli.DEFAULT_ARCHIVE_ROOT == tmp_path / "archives"
        assert cli.DEFAULT_HUB_ROOT == tmp_path / "hub"
        assert workbench.DEFAULT_OUTPUT_PATH == tmp_path / "output" / "mgts-normalized-broken-poles-ui"

    importlib.reload(cli)
    importlib.reload(workbench)


def test_compose_runs_only_the_authenticated_workbench_with_loopback_host_port() -> None:
    compose_path = REPOSITORY_ROOT / "compose.ml.yml"
    compose = yaml.safe_load(compose_path.read_text(encoding="utf-8"))

    assert set(compose["services"]) == {"workbench"}
    service = compose["services"]["workbench"]
    assert service["build"] == {"context": "./cv/data_pipeline", "dockerfile": "Dockerfile"}
    assert service["ports"] == ["${MARIMO_PUBLISH_HOST:-127.0.0.1}:${MARIMO_PUBLISH_PORT:-8790}:8790"]
    assert service["expose"] == ["8790"]
    assert service["environment"] == {
        "MGTS_MARIMO_AI_BASE_URL": "${MGTS_MARIMO_AI_BASE_URL:-}",
        "MGTS_MARIMO_AI_API_KEY": "${MGTS_MARIMO_AI_API_KEY:-}",
        "MGTS_MARIMO_AI_MODELS": "${MGTS_MARIMO_AI_MODELS:-}",
        "HF_TOKEN": "${HF_TOKEN:-}",
        "MARIMO_PASSWORD_FILE": "/run/secrets/marimo_password",
        "MARIMO_PORT": "8790",
        "MGTS_DATA_ARCHIVE_ROOT": "/data/archive",
        "MGTS_DATA_HUB_ROOT": "/data/hub",
        "MGTS_DATA_OUTPUT_ROOT": "/data/output",
        "MGTS_FINAL_MANIFEST": "/data/archive/mgts-final/final-materials.json",
        "MGTS_REFERENCE_INDEX": "/data/archive/mgts-final/cabinet-final-index-v1.json",
        "MGTS_MODEL_PATH": "/models/best.pt",
    }
    assert service["secrets"] == [{"source": "marimo_password", "target": "marimo_password"}]
    assert {mount["target"] for mount in service["volumes"]} == {
        "/data/archive",
        "/data/hub",
        "/data/notebooks",
        "/data/output",
        "/models/best.pt",
    }
    model_mount = next(mount for mount in service["volumes"] if mount["target"] == "/models/best.pt")
    assert model_mount["type"] == "bind"
    assert model_mount["source"] == "${MGTS_MODEL_FILE:-./cv/ml/best.pt}"
    assert model_mount["read_only"] is True
    assert model_mount["bind"]["create_host_path"] is False
    assert service["cap_drop"] == ["ALL"]
    assert service["security_opt"] == ["no-new-privileges:true"]
    assert compose["secrets"]["marimo_password"]["file"] == (
        "${MARIMO_PASSWORD_FILE:-.secrets/marimo_password}"
    )
    assert service["user"] == "10001:10001"
    notebook_mount = next(mount for mount in service["volumes"] if mount["target"] == "/data/notebooks")
    assert notebook_mount == {"type": "volume", "source": "notebook_workspace", "target": "/data/notebooks"}
    assert compose["volumes"]["notebook_workspace"]["name"] == (
        "${MGTS_VOLUME_PREFIX:-mgts-dataset-workbench}-notebooks"
    )


def test_container_image_uses_the_locked_ui_dependencies_and_safe_entrypoint() -> None:
    pipeline_root = REPOSITORY_ROOT / "cv" / "data_pipeline"
    dockerfile = (pipeline_root / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (pipeline_root / "container-entrypoint.sh").read_text(encoding="utf-8")
    ignore = (pipeline_root / ".dockerignore").read_text(encoding="utf-8")

    assert "uv sync --locked --no-dev --extra ui --extra inference --no-install-project" in dockerfile
    assert "uv sync --locked --no-dev --extra ui --extra inference" in dockerfile
    assert "COPY marimo.toml ./marimo.toml" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "--host 0.0.0.0" in entrypoint
    assert "marimo edit \"$NOTEBOOK_PATH\"" in entrypoint
    assert '--token-password-file "$MARIMO_PASSWORD_FILE"' in entrypoint
    assert 'NOTEBOOK_PATH="/data/notebooks/cabinet_gallery.md"' in entrypoint
    assert 'NOTEBOOK_SOURCE="/app/notebooks/cabinet_gallery.md"' in entrypoint
    assert "cp --no-clobber" in entrypoint
    assert "access_token=)[^&[:space:]]+" in entrypoint
    assert "python -m mgts_data_pipeline.marimo_ai_config" in entrypoint
    assert entrypoint.index("python -m mgts_data_pipeline.marimo_ai_config") < entrypoint.index("exec marimo edit")
    assert "fetch" not in entrypoint and "normalize" not in entrypoint
    assert "--token-password " not in entrypoint
    assert "/data/notebooks" in dockerfile
    assert ".venv" in ignore


def test_container_entrypoint_authenticates_editor_and_preserves_user_notebook(tmp_path: Path) -> None:
    test_entrypoint, source, notebook, secret, args_file, env = _container_entrypoint_fixture(tmp_path)

    legacy = notebook.parent / "dataset_workbench.py"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("existing collaborator edits", encoding="utf-8")
    source.write_text("starter notebook", encoding="utf-8")
    result = subprocess.run(["bash", str(test_entrypoint)], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert notebook.read_text(encoding="utf-8") == "starter notebook"
    assert legacy.read_text(encoding="utf-8") == "existing collaborator edits"
    assert (args_file.parent / "marimo-ai-config-args").read_text(encoding="utf-8").splitlines() == [
        "-m",
        "mgts_data_pipeline.marimo_ai_config",
    ]
    assert args_file.read_text(encoding="utf-8").splitlines() == [
        "edit",
        str(notebook),
        "--host",
        "0.0.0.0",
        "--port",
        "8790",
        "--token-password-file",
        str(secret),
        "--headless",
        "--trusted",
    ]
    assert "not-a-real-password" not in result.stdout + result.stderr

    notebook.write_text("user's saved edits", encoding="utf-8")
    source.write_text("new image template", encoding="utf-8")
    result = subprocess.run(["bash", str(test_entrypoint)], env=env, capture_output=True, text=True)

    assert result.returncode == 0, result.stderr
    assert notebook.read_text(encoding="utf-8") == "user's saved edits"


def test_container_entrypoint_requires_nonempty_password_before_launch(tmp_path: Path) -> None:
    test_entrypoint, _, notebook, secret, args_file, env = _container_entrypoint_fixture(tmp_path)
    secret.write_text("", encoding="utf-8")

    result = subprocess.run(["bash", str(test_entrypoint)], env=env, capture_output=True, text=True)

    assert result.returncode == 1
    assert "password secret file is missing or empty" in result.stderr
    assert not args_file.exists()
    assert not notebook.exists()


def test_inference_dependency_is_routed_to_the_cpu_wheel_index() -> None:
    pyproject = REPOSITORY_ROOT / "cv" / "data_pipeline" / "pyproject.toml"
    content = pyproject.read_text(encoding="utf-8")
    lock = (pyproject.parent / "uv.lock").read_text(encoding="utf-8")

    assert '"ultralytics==8.4.214"' in content
    assert 'name = "pytorch-cpu"' in content
    assert 'url = "https://download.pytorch.org/whl/cpu"' in content
    assert 'torch = { index = "pytorch-cpu" }' in content
    assert 'torchvision = { index = "pytorch-cpu" }' in content
    assert 'version = "2.15.0+cpu"' in lock
    assert 'version = "0.29.2+cpu"' in lock
    assert "nvidia-cuda-runtime" not in lock
    assert "nvidia-cudnn" not in lock
