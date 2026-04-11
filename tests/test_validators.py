"""Tests for input validation module."""

import pytest

from proxmox_mcp.utils.validators import (
    CommandExecParams,
    ContainerCreateParams,
    LIMITS,
    VMCreateParams,
    SnapshotParams,
    validate_command,
    validate_cpu_cores,
    validate_disk_gb,
    validate_memory_mb,
    validate_name,
    validate_resource_id,
)


class TestValidateCommand:
    """Test command validation and sanitization."""

    def test_valid_command(self):
        """Test valid command passes validation."""
        cmd = validate_command("systemctl status nginx")
        assert cmd == "systemctl status nginx"

    def test_empty_command(self):
        """Test empty command raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_command("")

    def test_whitespace_command(self):
        """Test whitespace-only command raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_command("   ")

    def test_command_too_long(self):
        """Test command exceeding max length raises ValueError."""
        long_cmd = "echo " + "a" * 5000
        with pytest.raises(ValueError, match="exceeds maximum length"):
            validate_command(long_cmd)

    def test_command_with_dollar_paren(self):
        """Test command with $() is blocked."""
        with pytest.raises(ValueError, match="dangerous pattern"):
            validate_command("echo $(whoami)")

    def test_command_with_backtick(self):
        """Test command with backticks is blocked."""
        with pytest.raises(ValueError, match="dangerous pattern"):
            validate_command("echo `whoami`")

    def test_command_with_semicolon(self):
        """Test command with semicolon is blocked."""
        with pytest.raises(ValueError, match="dangerous pattern"):
            validate_command("ls; rm -rf /")

    def test_command_with_pipe(self):
        """Test command with pipe is blocked."""
        with pytest.raises(ValueError, match="dangerous pattern"):
            validate_command("cat /etc/passwd | grep root")

    def test_command_with_redirect(self):
        """Test command with redirect is blocked."""
        with pytest.raises(ValueError, match="dangerous pattern"):
            validate_command("echo test > /etc/critical")

    def test_command_strips_whitespace(self):
        """Test command is stripped of leading/trailing whitespace."""
        cmd = validate_command("  systemctl status nginx  ")
        assert cmd == "systemctl status nginx"


class TestValidateResourceId:
    """Test resource ID validation."""

    def test_valid_id(self):
        """Test valid resource ID."""
        assert validate_resource_id(100) == 100
        assert validate_resource_id(1000) == 1000

    def test_id_too_low(self):
        """Test ID below minimum raises ValueError."""
        with pytest.raises(ValueError, match="between 100 and"):
            validate_resource_id(99)

    def test_id_too_high(self):
        """Test ID above maximum raises ValueError."""
        with pytest.raises(ValueError, match="between 100 and"):
            validate_resource_id(1000000000)

    def test_non_integer_id(self):
        """Test non-integer ID raises ValueError."""
        with pytest.raises(ValueError, match="must be an integer"):
            validate_resource_id("100")


class TestValidateName:
    """Test resource name validation."""

    def test_valid_resource_name(self):
        """Test valid resource name."""
        assert validate_name("my-resource", "resource_name") == "my-resource"

    def test_valid_vm_name(self):
        """Test valid VM name."""
        assert validate_name("web-server", "vm_name") == "web-server"

    def test_valid_node_name(self):
        """Test valid node name."""
        assert validate_name("pve1", "node_name") == "pve1"

    def test_empty_name(self):
        """Test empty name raises ValueError."""
        with pytest.raises(ValueError, match="cannot be empty"):
            validate_name("")

    def test_name_too_long(self):
        """Test name exceeding max length raises ValueError."""
        long_name = "a" * 100
        with pytest.raises(ValueError, match="exceeds maximum length"):
            validate_name(long_name)

    def test_invalid_name_pattern(self):
        """Test name with invalid characters raises ValueError."""
        with pytest.raises(ValueError, match="doesn't match pattern"):
            validate_name("invalid name!", "resource_name")

    def test_name_strips_whitespace(self):
        """Test name is stripped of whitespace."""
        assert validate_name("  my-resource  ", "resource_name") == "my-resource"

    def test_single_char_name(self):
        """Test single character name is valid."""
        assert validate_name("a", "vm_name") == "a"


class TestValidateCores:
    """Test CPU core validation."""

    def test_valid_cores(self):
        """Test valid core counts."""
        assert validate_cpu_cores(1) == 1
        assert validate_cpu_cores(4) == 4
        assert validate_cpu_cores(128) == 128

    def test_cores_too_low(self):
        """Test core count below minimum."""
        with pytest.raises(ValueError, match="between 1 and"):
            validate_cpu_cores(0)

    def test_cores_too_high(self):
        """Test core count above maximum."""
        with pytest.raises(ValueError, match="between 1 and"):
            validate_cpu_cores(129)


class TestValidateMemory:
    """Test memory validation."""

    def test_valid_memory(self):
        """Test valid memory sizes."""
        assert validate_memory_mb(64) == 64
        assert validate_memory_mb(2048) == 2048

    def test_memory_too_low(self):
        """Test memory below minimum."""
        with pytest.raises(ValueError, match="between 64MB and"):
            validate_memory_mb(32)

    def test_memory_too_high(self):
        """Test memory above maximum."""
        with pytest.raises(ValueError, match="between 64MB and"):
            validate_memory_mb(16777217)


class TestValidateDisk:
    """Test disk size validation."""

    def test_valid_disk(self):
        """Test valid disk sizes."""
        assert validate_disk_gb(1) == 1
        assert validate_disk_gb(100) == 100

    def test_disk_too_low(self):
        """Test disk size below minimum."""
        with pytest.raises(ValueError, match="between 1GB and"):
            validate_disk_gb(0)

    def test_disk_too_high(self):
        """Test disk size above maximum."""
        with pytest.raises(ValueError, match="between 1GB and"):
            validate_disk_gb(1048577)


class TestVMCreateParams:
    """Test VM creation parameters validation."""

    def test_valid_params(self):
        """Test valid VM creation parameters."""
        params = VMCreateParams(
            node="pve1",
            name="web-server",
            vm_id=100,
            cores=2,
            memory_mb=2048,
            storage="local-lvm"
        )
        assert params.node == "pve1"
        assert params.name == "web-server"
        assert params.vm_id == 100
        assert params.cores == 2
        assert params.memory_mb == 2048

    def test_invalid_node(self):
        """Test invalid node name."""
        with pytest.raises(ValueError):
            VMCreateParams(
                node="INVALID NODE!",
                name="web-server",
                vm_id=100
            )

    def test_invalid_vm_name(self):
        """Test invalid VM name."""
        with pytest.raises(ValueError):
            VMCreateParams(
                node="pve1",
                name="INVALID_VM_NAME",
                vm_id=100
            )

    def test_invalid_vm_id(self):
        """Test invalid VM ID."""
        with pytest.raises(ValueError):
            VMCreateParams(
                node="pve1",
                name="web-server",
                vm_id=99
            )

    def test_invalid_cores(self):
        """Test invalid core count."""
        with pytest.raises(ValueError):
            VMCreateParams(
                node="pve1",
                name="web-server",
                vm_id=100,
                cores=0
            )

    def test_invalid_memory(self):
        """Test invalid memory size."""
        with pytest.raises(ValueError):
            VMCreateParams(
                node="pve1",
                name="web-server",
                vm_id=100,
                memory_mb=32
            )

    def test_default_values(self):
        """Test default parameter values."""
        params = VMCreateParams(
            node="pve1",
            name="web-server",
            vm_id=100
        )
        assert params.cores == 2
        assert params.memory_mb == 2048
        assert params.storage == "local-lvm"


class TestContainerCreateParams:
    """Test container creation parameters validation."""

    def test_valid_params(self):
        """Test valid container creation parameters."""
        params = ContainerCreateParams(
            node="pve1",
            hostname="web-container",
            container_id=200,
            cores=1,
            memory_mb=512,
            storage="local",
            template="ubuntu-22.04"
        )
        assert params.hostname == "web-container"
        assert params.container_id == 200

    def test_invalid_container_id(self):
        """Test invalid container ID."""
        with pytest.raises(ValueError):
            ContainerCreateParams(
                node="pve1",
                hostname="web-container",
                container_id=99,
                template="ubuntu-22.04"
            )


class TestCommandExecParams:
    """Test command execution parameters validation."""

    def test_valid_command(self):
        """Test valid command parameters."""
        params = CommandExecParams(command="systemctl status")
        assert params.command == "systemctl status"
        assert params.timeout == 30  # default

    def test_command_with_timeout(self):
        """Test command with custom timeout."""
        params = CommandExecParams(command="systemctl status", timeout=60)
        assert params.timeout == 60

    def test_invalid_timeout_too_low(self):
        """Test invalid timeout (too low)."""
        with pytest.raises(ValueError, match="between 1 and 300"):
            CommandExecParams(command="test", timeout=0)

    def test_invalid_timeout_too_high(self):
        """Test invalid timeout (too high)."""
        with pytest.raises(ValueError, match="between 1 and 300"):
            CommandExecParams(command="test", timeout=301)


class TestSnapshotParams:
    """Test snapshot parameters validation."""

    def test_valid_params(self):
        """Test valid snapshot parameters."""
        params = SnapshotParams(snapshot_name="backup-2026")
        assert params.snapshot_name == "backup-2026"
        assert params.description == ""

    def test_snapshot_with_description(self):
        """Test snapshot with description."""
        params = SnapshotParams(
            snapshot_name="backup-2026",
            description="Pre-upgrade backup"
        )
        assert params.description == "Pre-upgrade backup"

    def test_invalid_snapshot_name(self):
        """Test invalid snapshot name."""
        with pytest.raises(ValueError):
            SnapshotParams(snapshot_name="")

    def test_description_too_long(self):
        """Test description exceeding max length."""
        long_desc = "a" * 2000
        with pytest.raises(ValueError, match="exceeds maximum length"):
            SnapshotParams(
                snapshot_name="backup",
                description=long_desc
            )
