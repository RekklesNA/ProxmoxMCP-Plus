"""Smoke test OpenRouter against this repository's MCP tool surface."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def build_payload(model: str, tools: list[str]) -> dict[str, Any]:
    preview = ", ".join(tools[:16])
    prompt = (
        "You are validating an MCP server for Proxmox VE.\n"
        f"Available tools ({len(tools)} total): {preview}\n"
        "Based only on those tool names, answer in 3 short bullets:\n"
        "1. The 3 riskiest operations.\n"
        "2. The 2 most useful day-2 ops workflows.\n"
        "3. One sentence on why metrics and approval gates matter here."
    )
    return {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": 0.2,
    }


async def list_tool_names(config_path: str) -> list[str]:
    from proxmox_mcp.server import ProxmoxMCPServer

    server = ProxmoxMCPServer(config_path)
    tools = await server.mcp.list_tools()
    return sorted(tool.name for tool in tools)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a real OpenRouter LLM smoke test")
    parser.add_argument(
        "--model",
        default=os.getenv("OPENROUTER_MODEL", "qwen/qwen3.6-plus"),
        help="OpenRouter model identifier",
    )
    parser.add_argument(
        "--config",
        default=os.getenv("PROXMOX_MCP_CONFIG", str(ROOT / "proxmox-config" / "config.json")),
        help="Path to Proxmox MCP config used only for local tool discovery",
    )
    parser.add_argument(
        "--api-key-env",
        default="OPENROUTER_API_KEY",
        help="Environment variable containing the OpenRouter API key",
    )
    args = parser.parse_args()

    api_key = os.getenv(args.api_key_env)
    if not api_key:
        raise RuntimeError(f"Missing OpenRouter API key in env var: {args.api_key_env}")

    tool_names = asyncio.run(list_tool_names(args.config))
    payload = build_payload(args.model, tool_names)
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/RekklesNA/ProxmoxMCP-Plus",
            "X-Title": "ProxmoxMCP-Plus Smoke Test",
        },
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    data = response.json()
    choices = data.get("choices", [])
    if not choices:
        raise RuntimeError(f"OpenRouter returned no choices: {json.dumps(data, indent=2)}")

    message = choices[0].get("message", {}).get("content", "")
    if not message:
        raise RuntimeError(f"OpenRouter returned an empty message: {json.dumps(data, indent=2)}")

    print("[openrouter-smoke] model:", data.get("model", args.model))
    print("[openrouter-smoke] tools:", len(tool_names))
    print("[openrouter-smoke] response:")
    print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
