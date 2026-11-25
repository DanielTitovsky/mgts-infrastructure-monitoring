from __future__ import annotations

import importlib
from pathlib import Path

import pytest
import yaml

from mgts_data_pipeline import cli, workbench


REPOSITORY_ROOT = Path(__file__).parents[3]


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
        "HF_TOKEN": "${HF_TOKEN:-}",
        "MARIMO_PASSWORD_FILE": "/run/secrets/marimo_password",
        "MARIMO_PORT": "8790",
        "MGTS_DATA_ARCHIVE_ROOT": "/data/archive",
        "MGTS_DATA_HUB_ROOT": "/data/hub",
        "MGTS_DATA_OUTPUT_ROOT": "/data/output",
        "MGTS_MODEL_PATH": "/models/best.pt",
    }
    assert service["secrets"] == [{"source": "marimo_password", "target": "marimo_password"}]
    assert {mount["target"] for mount in service["volumes"]} == {
        "/data/archive",
        "/data/hub",
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


def test_container_image_uses_the_locked_ui_dependencies_and_safe_entrypoint() -> None:
    pipeline_root = REPOSITORY_ROOT / "cv" / "data_pipeline"
    dockerfile = (pipeline_root / "Dockerfile").read_text(encoding="utf-8")
    entrypoint = (pipeline_root / "container-entrypoint.sh").read_text(encoding="utf-8")
    ignore = (pipeline_root / ".dockerignore").read_text(encoding="utf-8")

    assert "uv sync --locked --no-dev --extra ui --extra inference --no-install-project" in dockerfile
    assert "uv sync --locked --no-dev --extra ui --extra inference" in dockerfile
    assert "USER 10001:10001" in dockerfile
    assert "--host 0.0.0.0" in entrypoint
    assert '--token-password-file "$MARIMO_PASSWORD_FILE"' in entrypoint
    assert "access_token=)[^&[:space:]]+" in entrypoint
    assert "fetch" not in entrypoint and "normalize" not in entrypoint
    assert "--token-password " not in entrypoint
    assert ".venv" in ignore


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
