"""Redaction helpers for values that may contain credentials."""

from __future__ import annotations

import re
from typing import Any

_RE_USERINFO = re.compile(r"(?P<scheme>\w+://)(?P<userinfo>[^/@\s]+)@")
_RE_AUTH = re.compile(
    r"(?i)(authorization|x-api-key|api-key)\s*[=:]\s*(?:(?:Bearer|Basic)\s+\S+|PVEAPIToken=\S+)"
)
_RE_SECRET_KV = re.compile(
    r"(?i)([\"']?(?:token|password|secret|api[_-]?key|authorization|approval_token)"
    r"[\"']?\s*[:=]\s*)([\"']?)([^\"'&,}\s]+)\2"
)
_SECRET_KEYS = {
    "password", "token", "token_value", "api_key", "secret", "authorization", "approval_token",
}


def sanitize_string(value: object, max_length: int | None = None) -> str:
    """Return text with URL credentials, auth headers, and secret fields redacted."""
    text = str(value).replace("\r", "").replace("\n", "")
    text = _RE_USERINFO.sub(lambda m: f"{m.group('scheme')}[REDACTED]@", text)
    text = _RE_AUTH.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    text = _RE_SECRET_KV.sub(lambda m: f"{m.group(1)}[REDACTED]", text)
    return text[:max_length] if max_length is not None else text


def is_secret_key(key: str) -> bool:
    """Return whether a mapping key identifies a credential."""
    normalized = key.lower().replace("-", "_")
    return any(secret in normalized for secret in _SECRET_KEYS)


def sanitize_value(value: Any) -> Any:
    """Recursively redact credential-bearing mapping keys and string values."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if is_secret_key(str(key)) else sanitize_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_value(item) for item in value)
    if isinstance(value, str):
        return sanitize_string(value)
    return value
