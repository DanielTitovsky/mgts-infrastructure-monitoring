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
