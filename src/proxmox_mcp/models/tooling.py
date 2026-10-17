"""Standardized tool result envelope."""

from __future__ import annotations

from typing import Any
import json

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    success: bool
    code: str = Field(description="Stable machine-readable result code")
    message: str
    data: Any | None = None


def result_succeeded(result: Any) -> bool:
    """Read structured outcomes while preserving legacy text tool responses."""
    if isinstance(result, ToolResult):
        return result.success
    if isinstance(result, dict):
        return result.get("success", result.get("ok", True)) is not False
    if isinstance(result, list):
        for item in result:
            if hasattr(item, "text"):
                try:
                    payload = json.loads(item.text)
                except (ValueError, TypeError):
                    continue
                if not result_succeeded(payload):
                    return False
            elif not result_succeeded(item):
                return False
    return True


def result_status(result: Any) -> str:
    """Classify only structured results; retain legacy text compatibility."""
    if isinstance(result, ToolResult):
        result = result.model_dump()
    if isinstance(result, dict):
        code = str(result.get("code", ""))
        if code.startswith(("CMD_POLICY_", "OP_POLICY_")) and not result_succeeded(result):
            return "denied"
        if code == "INCOMPLETE_INVENTORY" or result.get("status") == "partial":
            return "partial"
        if not result_succeeded(result):
            return "error"
        return "submitted" if result.get("status") == "submitted" else "success"
    if isinstance(result, list):
        statuses = []
        for item in result:
            if hasattr(item, "text"):
                try:
                    item = json.loads(item.text)
                except (ValueError, TypeError):
                    continue
            statuses.append(result_status(item))
        for status in ("denied", "partial"):
            if status in statuses:
                return status
        if "error" in statuses:
            return "partial" if "success" in statuses or "submitted" in statuses else "error"
        if "submitted" in statuses:
            return "submitted"
    return "success"
