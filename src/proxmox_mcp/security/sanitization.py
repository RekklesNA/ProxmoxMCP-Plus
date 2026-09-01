"""Redaction helpers for values that may contain credentials."""

from __future__ import annotations

import re
from typing import Any

# The scheme is bounded rather than \w+ : an unbounded greedy run followed by "://"
# backtracks quadratically over long word-character sequences (a ReDoS vector, since
# this sanitizer runs on attacker-influenced error text). A bounded, RFC-3986-shaped
# scheme caps the work per starting position, keeping the scan linear overall.
_RE_USERINFO = re.compile(
    r"(?P<scheme>[A-Za-z][A-Za-z0-9+.\-]{0,31}://)(?P<userinfo>[^/@\s]{1,256})@"
)
_RE_AUTH = re.compile(
    r"(?i)(authorization|x-api-key|api-key)\s*[=:]\s*(?:(?:Bearer|Basic)\s+\S+|PVEAPIToken=\S+)"
)
_SECRET_KEY_PATTERN = (
    r"(?:token_value|token|password|secret|api[_-]?key|authorization"
    r"|approval_token|pveauthcookie)"
)
# The quoted branches use a single flat character class ([^"]* / [^']*) rather than
# a nested quantifier such as [^"\\]*(?:\\.[^"\\]*)*. Nested quantifiers backtrack
# quadratically when the closing quote is missing, which is a ReDoS vector on
# attacker-influenced error text; a flat class is one linear scan that fails fast.
# A backslash-escaped quote therefore ends the match early, which is safe: the
# secret is still replaced, only the trailing fragment survives.
_RE_SECRET_KV = re.compile(
    r"(?i)([\"']?" + _SECRET_KEY_PATTERN + r"[\"']?\s*[:=]\s*)"
    r"(?:"
    r"\"(?P<dq>[^\"]*)\""
    r"|"
    r"'(?P<sq>[^']*)'"
    r"|"
    r"(?P<bare>[^\"'&,}\s]+)"
    r")"
)
_SECRET_KEYS = {
    "password", "token", "token_value", "api_key", "secret", "authorization", "approval_token", "pveauthcookie",
}


def _redact_secret_kv(match: re.Match[str]) -> str:
    """Redact a secret value, preserving the original quoting style."""
    if match.group("dq") is not None:
        return f'{match.group(1)}"[REDACTED]"'
    if match.group("sq") is not None:
        return f"{match.group(1)}'[REDACTED]'"
    return f"{match.group(1)}[REDACTED]"


def sanitize_string(value: object, max_length: int | None = None) -> str:
    """Return text with URL credentials, auth headers, and secret fields redacted."""
    text = str(value).replace("\r", "").replace("\n", "")
    text = _RE_USERINFO.sub(lambda m: f"{m.group('scheme')}[REDACTED]@", text)
    text = _RE_AUTH.sub(lambda m: f"{m.group(1)}=[REDACTED]", text)
    text = _RE_SECRET_KV.sub(_redact_secret_kv, text)
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
