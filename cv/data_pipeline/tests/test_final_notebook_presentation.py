"""Acceptance: the editable default notebook is readable without exposing raw code/data."""
import ast
from pathlib import Path


def test_screen_uses_native_markdown_and_structured_outputs():
    path = Path(__file__).parents[1] / "notebooks" / "ml_research.py"
    source = path.read_text()
    funcs = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)]
    markdown = [node.value.args[0].value for f in funcs for node in f.body
                if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                and ast.unparse(node.value.func) == "mo.md" and node.value.args
                and isinstance(node.value.args[0], ast.Constant)]
    assert "mo.json(" not in source
    assert any("шкаф" in val.lower() for val in markdown)
    assert any("разметк" in val.lower() for val in markdown)
    assert all("hide_code=True" in ast.unparse(f.decorator_list[0]) for f in funcs)


def test_team_assistant_uses_optional_independent_settings_without_personal_keys():
    import yaml
    compose = yaml.safe_load((Path(__file__).parents[3] / "compose.ml.yml").read_text())
    env = compose["services"]["workbench"]["environment"]
    for key in ("MGTS_MARIMO_AI_BASE_URL", "MGTS_MARIMO_AI_API_KEY", "MGTS_MARIMO_AI_MODELS"):
        assert env[key] == "${" + key + ":-}"
