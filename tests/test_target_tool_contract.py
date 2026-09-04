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
    missing = []
    for node in tools:
        params = node.args.args + node.args.kwonlyargs
        names = {arg.arg for arg in params}
        if "target" not in names:
            missing.append(node.name)
            continue
        if "target" in [arg.arg for arg in node.args.args]:
            index = [arg.arg for arg in node.args.args].index("target")
            optional = index >= len(node.args.args) - len(node.args.defaults)
        else:
            index = [arg.arg for arg in node.args.kwonlyargs].index("target")
            optional = node.args.kw_defaults[index] is not None
        if not optional:
            missing.append(node.name)
    assert missing == []
