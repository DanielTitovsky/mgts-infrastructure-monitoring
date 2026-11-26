"""Render Marimo's trusted user config from explicit operator settings."""

from __future__ import annotations

import ipaddress
import os
import re
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import tomlkit

AI_BASE_URL_ENV = "MGTS_MARIMO_AI_BASE_URL"
AI_API_KEY_ENV = "MGTS_MARIMO_AI_API_KEY"
AI_MODEL_IDS_ENV = "MGTS_MARIMO_AI_MODELS"
PROVIDER_ID = "mgts"
ALLOWED_MODEL_IDS = ("gpt-6.2-sol", "gpt-6.2-astra")
REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max")
DEFAULT_REASONING_EFFORT = "high"
MAX_CONFIGURED_MODELS = len(ALLOWED_MODEL_IDS)
MAX_MODEL_ID_LENGTH = 128
_MODEL_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]*\Z")
_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "marimo.toml"


def build_marimo_ai_config(env: Mapping[str, str]) -> dict[str, Any]:
    """Build safe native Marimo AI config; empty/partial settings stay off."""
    config = tomlkit.parse(_TEMPLATE_PATH.read_text(encoding="utf-8")).unwrap()
    ai = config["ai"]

    base_url = env.get(AI_BASE_URL_ENV, "").strip()
    api_key = env.get(AI_API_KEY_ENV, "").strip()
    raw_model_ids = env.get(AI_MODEL_IDS_ENV, "").strip()
    if not (base_url and api_key and raw_model_ids):
        return config

    normalized_url = _validate_base_url(base_url)
    model_ids = _parse_model_ids(raw_model_ids)
    qualified_models = [
        f"{PROVIDER_ID}/{model_id}({effort})"
        for model_id in model_ids
        for effort in REASONING_EFFORTS
    ]
    default_model = f"{PROVIDER_ID}/{model_ids[0]}({DEFAULT_REASONING_EFFORT})"

    ai["enabled"] = True
    ai["custom_providers"] = {
        PROVIDER_ID: {
            "base_url": normalized_url,
            "api_key": f"env:{AI_API_KEY_ENV}",
        }
    }
    ai["models"] = {
        "displayed_models": qualified_models,
        "custom_models": qualified_models,
        "chat_model": default_model,
        "edit_model": default_model,
        "autocomplete_model": default_model,
    }
    return config


def write_marimo_ai_config(path: Path, env: Mapping[str, str]) -> bool:
    """Write the resolved user config without ever storing an API key."""
    try:
        config = build_marimo_ai_config(env)
    except ValueError:
        config = tomlkit.parse(_TEMPLATE_PATH.read_text(encoding="utf-8")).unwrap()
        print("Invalid MGTS Marimo AI configuration; native AI remains disabled.")

    _write_private_config(path, tomlkit.dumps(config))
    enabled = bool(config["ai"]["enabled"])
    if enabled:
        print("Native Marimo AI enabled for the explicitly configured MGTS models.")
    else:
        print(
            "Native Marimo AI remains disabled until all operator settings are supplied."
        )
    return enabled


def _validate_base_url(value: str) -> str:
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
        _ = parts.port
    except ValueError as error:
        raise ValueError("invalid base URL") from error

    if (
        not hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or not parts.path.rstrip("/").endswith("/v1")
    ):
        raise ValueError("invalid base URL")

    if parts.scheme == "https":
        return value.rstrip("/")

    if parts.scheme == "http":
        try:
            is_loopback = ipaddress.ip_address(hostname).is_loopback
        except ValueError:
            is_loopback = hostname.lower() == "localhost"
        if is_loopback:
            return value.rstrip("/")

    raise ValueError("base URL must use HTTPS; HTTP is allowed only for loopback tests")


def _parse_model_ids(value: str) -> list[str]:
    model_ids = [model_id.strip() for model_id in value.split(",")]
    if (
        not model_ids
        or len(model_ids) > MAX_CONFIGURED_MODELS
        or len(set(model_ids)) != len(model_ids)
        or set(model_ids) != set(ALLOWED_MODEL_IDS)
        or any(
            not model_id
            or len(model_id) > MAX_MODEL_ID_LENGTH
            or not _MODEL_ID_RE.fullmatch(model_id)
            or model_id.startswith(f"{PROVIDER_ID}/")
            for model_id in model_ids
        )
    ):
        raise ValueError("invalid model allowlist")
    return model_ids


def _write_private_config(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise OSError("refusing to replace a symlinked Marimo config")

    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".marimo-config-",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            os.chmod(temporary_path, 0o600)
            temporary_file.write(content)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def main() -> None:
    write_marimo_ai_config(Path.home() / ".marimo.toml", os.environ)


if __name__ == "__main__":
    main()
