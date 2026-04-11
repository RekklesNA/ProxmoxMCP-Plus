"""Standardized tool result envelope."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    success: bool
    code: str = Field(description="Stable machine-readable result code")
    message: str
    data: Any | None = None
