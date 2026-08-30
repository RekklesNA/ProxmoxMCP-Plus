import ast
from pathlib import Path


PLUGIN = Path(__file__).parents[1] / "src/proxmox_mcp/services/builtin_tool_plugins.py"


def test_every_operational_tool_accepts_optional_target():
    tree = ast.parse(PLUGIN.read_text())
    tools = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(isinstance(dec, ast.Call) and getattr(dec.func, "attr", "") == "tool" for dec in node.decorator_list):
            continue
        if node.name == "list_targets":
            continue
        tools.append(node)
    assert tools
    missing = [node.name for node in tools if "target" not in {arg.arg for arg in node.args.args}]
    assert missing == []
