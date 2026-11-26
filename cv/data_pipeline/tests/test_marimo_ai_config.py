from __future__ import annotations

import asyncio
import json
import stat
import threading
import tomllib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from mgts_data_pipeline.marimo_ai_config import (
    AI_API_KEY_ENV,
    AI_BASE_URL_ENV,
    AI_MODEL_IDS_ENV,
    build_marimo_ai_config,
    write_marimo_ai_config,
)


def _operator_env(base_url: str, api_key: str, model_ids: str) -> dict[str, str]:
    return {
        AI_BASE_URL_ENV: base_url,
        AI_API_KEY_ENV: api_key,
        AI_MODEL_IDS_ENV: model_ids,
    }


def test_native_ai_is_off_without_an_explicit_complete_operator_config() -> None:
    config = build_marimo_ai_config({})
    ai = config["ai"]

    assert ai["enabled"] is False
    assert ai["allow_provider_config"] is False
    assert ai["inline_tooltip"] is False
    assert ai["models"]["displayed_models"] == []
    assert "custom_providers" not in ai
    assert config["runtime"] == {
        "auto_instantiate": True,
        "on_cell_change": "autorun",
    }

    partial = build_marimo_ai_config({AI_BASE_URL_ENV: "https://proxy.invalid/v1"})
    assert partial["ai"]["enabled"] is False
    assert "custom_providers" not in partial["ai"]


def test_operator_models_are_qualified_and_key_is_only_an_env_reference() -> None:
    secret = "test-key-that-must-never-be-written"
    config = build_marimo_ai_config(
        _operator_env("https://proxy.example/v1", secret, "fast-model,accurate-model")
    )
    ai = config["ai"]
    models = ["mgts/fast-model", "mgts/accurate-model"]

    assert ai["enabled"] is True
    assert ai["allow_provider_config"] is False
    assert ai["inline_tooltip"] is False
    assert ai["models"]["displayed_models"] == models
    assert ai["models"]["custom_models"] == models
    assert ai["models"]["chat_model"] == models[0]
    assert ai["models"]["edit_model"] == models[0]
    assert ai["models"]["autocomplete_model"] == models[0]
    assert config["runtime"] == {
        "auto_instantiate": True,
        "on_cell_change": "autorun",
    }
    assert ai["custom_providers"]["mgts"] == {
        "base_url": "https://proxy.example/v1",
        "api_key": f"env:{AI_API_KEY_ENV}",
    }
    assert secret not in repr(config)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://proxy.example/v1",
        "https://user:password@proxy.example/v1",
        "https://proxy.example/v1?token=secret",
        "https://proxy.example/chat/completions",
    ],
)
def test_unsafe_or_non_openai_api_base_urls_are_rejected(base_url: str) -> None:
    with pytest.raises(ValueError):
        build_marimo_ai_config(_operator_env(base_url, "key", "model"))


def test_invalid_runtime_config_fails_closed_and_writes_private_config(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / ".marimo.toml"
    secret = "must-not-appear-in-file-or-output"

    enabled = write_marimo_ai_config(
        config_path,
        _operator_env("http://proxy.example/v1", secret, "model"),
    )

    content = config_path.read_text(encoding="utf-8")
    assert enabled is False
    assert "enabled = false" in content
    assert secret not in content
    assert secret not in capsys.readouterr().out
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_valid_config_file_is_redacted_by_marimo_before_ui_serialization(
    tmp_path: Path,
) -> None:
    from marimo._config.secrets import redact_secrets

    config_path = tmp_path / ".marimo.toml"
    secret = "runtime-only-test-key"
    enabled = write_marimo_ai_config(
        config_path,
        _operator_env("https://proxy.example/v1", secret, "chat-model"),
    )

    config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    redacted = redact_secrets(config)
    assert enabled is True
    assert (
        config["ai"]["custom_providers"]["mgts"]["api_key"] == f"env:{AI_API_KEY_ENV}"
    )
    assert redacted["ai"]["custom_providers"]["mgts"]["api_key"] == "********"
    assert secret not in config_path.read_text(encoding="utf-8")


def test_native_marimo_adapter_uses_the_selected_model_against_local_mock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_model = "second-local-model"
    api_key = "local-test-only-key"
    state: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["path"] = self.path
            state["model"] = payload["model"]
            state["authorization"] = self.headers.get("Authorization")
            body = json.dumps(
                {
                    "id": "chatcmpl-local-test",
                    "object": "chat.completion",
                    "created": 0,
                    "model": payload["model"],
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "LOCAL_OK"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                }
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = build_marimo_ai_config(
            _operator_env(
                f"http://127.0.0.1:{server.server_port}/v1",
                api_key,
                f"first-local-model,{selected_model}",
            )
        )
        ai = config["ai"]
        selected_id = f"mgts/{selected_model}"

        from marimo._server.ai.config import AnyProviderConfig
        from marimo._server.ai.providers import get_completion_provider
        from pydantic_ai import Agent

        provider_config = AnyProviderConfig.for_model(
            selected_id,
            ai,
            secret_resolver=lambda name: api_key if name == AI_API_KEY_ENV else None,
        )
        provider = get_completion_provider(provider_config, selected_id)
        agent = Agent(provider.create_model())
        result = asyncio.run(agent.run("Reply with exactly LOCAL_OK."))

        assert result.output == "LOCAL_OK"
        assert state == {
            "path": "/v1/chat/completions",
            "model": selected_model,
            "authorization": f"Bearer {api_key}",
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
