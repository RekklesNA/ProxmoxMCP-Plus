"""
Input validation and sanitization utilities for ProxmoxMCP-Plus.

Provides comprehensive input validation with:
- Parameter type checking
- Value range validation
- String pattern matching
- Command injection prevention
- Resource limit enforcement
- Pydantic model validators
"""

from __future__ import annotations

import re

from pydantic import BaseModel, field_validator


# Validation patterns
VALIDATORS = {
    # Resource names (alphanumeric, hyphens, underscores)
    "resource_name": re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}$'),
    
    # VM/LXC names (DNS-compatible)
    "vm_name": re.compile(r'^[a-z][a-z0-9-]{0,61}[a-z0-9]$|^[a-z]$'),
    
    # Node names
    "node_name": re.compile(r'^[a-z][a-z0-9-]{0,61}[a-z0-9]$|^[a-z]$'),
    
    # Storage names
    "storage_name": re.compile(r'^[a-z][a-z0-9_-]{0,62}$'),
    
    # Snapshot names
    "snapshot_name": re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,254}$'),
    
    # ISO file names
    "iso_name": re.compile(r'^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,251}\.(iso|img)$'),
    
    # File paths (prevent directory traversal)
    "safe_path": re.compile(r'^[a-zA-Z0-9/_.-]+$'),
    
    # IP addresses (IPv4)
    "ipv4": re.compile(r'^(\d{1,3}\.){3}\d{1,3}$'),
    
    # Email addresses
    "email": re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'),
}

# Resource limits
LIMITS = {
    "vm_id_min": 100,
    "vm_id_max": 999999999,
    "container_id_min": 100,
    "container_id_max": 999999999,
    "cpu_cores_min": 1,
    "cpu_cores_max": 128,
    "memory_mb_min": 64,
    "memory_mb_max": 16777216,  # 16TB
    "disk_gb_min": 1,
    "disk_gb_max": 1048576,  # 1PB
    "name_length_min": 1,
    "name_length_max": 63,
    "command_length_max": 4096,
    "description_length_max": 1024,
}


def validate_command(command: str, max_length: int = LIMITS["command_length_max"]) -> str:
    """
    Validate and sanitize a shell command.

    Checks:
    - Length limits
    - Prevents command injection patterns
    - Blocks dangerous characters

    Args:
        command: Command string to validate
        max_length: Maximum allowed command length

    Returns:
        Validated command string

    Raises:
        ValueError: If command is invalid or dangerous
    """
    if not command or not command.strip():
        raise ValueError("Command cannot be empty")

    if len(command) > max_length:
        raise ValueError(f"Command exceeds maximum length of {max_length} characters")

    # Block dangerous patterns
    dangerous_patterns = [
        r'\$\(',           # Command substitution
        r'`',              # Backtick execution
        r'\|',             # Pipe (context-dependent)
        r'&&',             # Command chaining
        r'\|\|',           # Conditional execution
        r';',              # Command separator
        r'>',              # Output redirection
        r'<',              # Input redirection
    ]

    for pattern in dangerous_patterns:
        if re.search(pattern, command):
            raise ValueError(f"Command contains potentially dangerous pattern: {pattern}")

    return command.strip()


def validate_resource_id(resource_id: int, min_id: int = 100, max_id: int = 999999999) -> int:
    """
    Validate a VM/container resource ID.

    Args:
        resource_id: ID to validate
        min_id: Minimum allowed ID
        max_id: Maximum allowed ID

    Returns:
        Validated resource ID

    Raises:
        ValueError: If ID is out of range
    """
    if not isinstance(resource_id, int):
        raise ValueError(f"Resource ID must be an integer, got {type(resource_id)}")

    if resource_id < min_id or resource_id > max_id:
        raise ValueError(f"Resource ID must be between {min_id} and {max_id}, got {resource_id}")

    return resource_id


def validate_name(name: str, name_type: str = "resource_name") -> str:
    """
    Validate a resource name against pattern.

    Args:
        name: Name to validate
        name_type: Type of name (resource_name, vm_name, node_name, etc.)

    Returns:
        Validated name

    Raises:
        ValueError: If name doesn't match pattern
    """
    if not name or not name.strip():
        raise ValueError("Name cannot be empty")

    # Strip whitespace before validation
    name = name.strip()

    if len(name) > LIMITS["name_length_max"]:
        raise ValueError(f"Name exceeds maximum length of {LIMITS['name_length_max']} characters")

    pattern = VALIDATORS.get(name_type)
    if pattern and not pattern.match(name):
        raise ValueError(
            f"Name '{name}' doesn't match pattern for {name_type}. "
            f"Expected pattern: {pattern.pattern}"
        )

    return name


def validate_cpu_cores(cores: int) -> int:
    """Validate CPU core count."""
    if cores < LIMITS["cpu_cores_min"] or cores > LIMITS["cpu_cores_max"]:
        raise ValueError(
            f"CPU cores must be between {LIMITS['cpu_cores_min']} and "
            f"{LIMITS['cpu_cores_max']}, got {cores}"
        )
    return cores


def validate_memory_mb(memory_mb: int) -> int:
    """Validate memory in MB."""
    if memory_mb < LIMITS["memory_mb_min"] or memory_mb > LIMITS["memory_mb_max"]:
        raise ValueError(
            f"Memory must be between {LIMITS['memory_mb_min']}MB and "
            f"{LIMITS['memory_mb_max']}MB, got {memory_mb}MB"
        )
    return memory_mb


def validate_disk_gb(disk_gb: int) -> int:
    """Validate disk size in GB."""
    if disk_gb < LIMITS["disk_gb_min"] or disk_gb > LIMITS["disk_gb_max"]:
        raise ValueError(
            f"Disk size must be between {LIMITS['disk_gb_min']}GB and "
            f"{LIMITS['disk_gb_max']}GB, got {disk_gb}GB"
        )
    return disk_gb


class VMCreateParams(BaseModel):
    """Validated parameters for VM creation."""

    node: str
    name: str
    vm_id: int
    cores: int = 2
    memory_mb: int = 2048
    storage: str = "local-lvm"

    @field_validator("node")
    @classmethod
    def validate_node_name(cls, v: str) -> str:
        return validate_name(v, "node_name")

    @field_validator("name")
    @classmethod
    def validate_vm_name(cls, v: str) -> str:
        return validate_name(v, "vm_name")

    @field_validator("vm_id")
    @classmethod
    def validate_vm_id(cls, v: int) -> int:
        return validate_resource_id(v, LIMITS["vm_id_min"], LIMITS["vm_id_max"])

    @field_validator("cores")
    @classmethod
    def validate_cores(cls, v: int) -> int:
        return validate_cpu_cores(v)

    @field_validator("memory_mb")
    @classmethod
    def validate_memory(cls, v: int) -> int:
        return validate_memory_mb(v)


class ContainerCreateParams(BaseModel):
    """Validated parameters for container creation."""

    node: str
    hostname: str
    container_id: int
    cores: int = 1
    memory_mb: int = 512
    storage: str = "local"
    template: str

    @field_validator("node")
    @classmethod
    def validate_node_name(cls, v: str) -> str:
        return validate_name(v, "node_name")

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, v: str) -> str:
        return validate_name(v, "vm_name")

    @field_validator("container_id")
    @classmethod
    def validate_container_id(cls, v: int) -> int:
        return validate_resource_id(v, LIMITS["container_id_min"], LIMITS["container_id_max"])

    @field_validator("cores")
    @classmethod
    def validate_cores(cls, v: int) -> int:
        return validate_cpu_cores(v)

    @field_validator("memory_mb")
    @classmethod
    def validate_memory(cls, v: int) -> int:
        return validate_memory_mb(v)


class CommandExecParams(BaseModel):
    """Validated parameters for command execution."""

    command: str
    timeout: int = 30

    @field_validator("command")
    @classmethod
    def validate_command(cls, v: str) -> str:
        return validate_command(v)

    @field_validator("timeout")
    @classmethod
    def validate_timeout(cls, v: int) -> int:
        if v < 1 or v > 300:
            raise ValueError("Timeout must be between 1 and 300 seconds")
        return v


class SnapshotParams(BaseModel):
    """Validated parameters for snapshot operations."""

    snapshot_name: str
    description: str = ""

    @field_validator("snapshot_name")
    @classmethod
    def validate_snapshot_name(cls, v: str) -> str:
        return validate_name(v, "snapshot_name")

    @field_validator("description")
    @classmethod
    def validate_description(cls, v: str) -> str:
        if len(v) > LIMITS["description_length_max"]:
            raise ValueError(
                f"Description exceeds maximum length of {LIMITS['description_length_max']}"
            )
        return v
