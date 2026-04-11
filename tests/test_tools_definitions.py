"""Tests for tools/definitions module."""

import pytest
from proxmox_mcp.tools import definitions


class TestNodeDefinitions:
    """Test node tool descriptions."""

    def test_get_nodes_desc(self):
        """Test GET_NODES_DESC is defined."""
        assert hasattr(definitions, 'GET_NODES_DESC')
        assert isinstance(definitions.GET_NODES_DESC, str)
        assert len(definitions.GET_NODES_DESC) > 0

    def test_get_node_status_desc(self):
        """Test GET_NODE_STATUS_DESC is defined."""
        assert hasattr(definitions, 'GET_NODE_STATUS_DESC')
        assert isinstance(definitions.GET_NODE_STATUS_DESC, str)


class TestVMDefinitions:
    """Test VM tool descriptions."""

    def test_get_vms_desc(self):
        """Test GET_VMS_DESC is defined."""
        assert hasattr(definitions, 'GET_VMS_DESC')
        assert isinstance(definitions.GET_VMS_DESC, str)

    def test_create_vm_desc(self):
        """Test CREATE_VM_DESC is defined."""
        assert hasattr(definitions, 'CREATE_VM_DESC')
        assert isinstance(definitions.CREATE_VM_DESC, str)
        assert "cpus" in definitions.CREATE_VM_DESC

    def test_execute_vm_command_desc(self):
        """Test EXECUTE_VM_COMMAND_DESC is defined."""
        assert hasattr(definitions, 'EXECUTE_VM_COMMAND_DESC')
        assert isinstance(definitions.EXECUTE_VM_COMMAND_DESC, str)

    def test_start_vm_desc(self):
        """Test START_VM_DESC is defined."""
        assert hasattr(definitions, 'START_VM_DESC')
        assert isinstance(definitions.START_VM_DESC, str)

    def test_stop_vm_desc(self):
        """Test STOP_VM_DESC is defined."""
        assert hasattr(definitions, 'STOP_VM_DESC')
        assert isinstance(definitions.STOP_VM_DESC, str)

    def test_shutdown_vm_desc(self):
        """Test SHUTDOWN_VM_DESC is defined."""
        assert hasattr(definitions, 'SHUTDOWN_VM_DESC')
        assert isinstance(definitions.SHUTDOWN_VM_DESC, str)

    def test_reset_vm_desc(self):
        """Test RESET_VM_DESC is defined."""
        assert hasattr(definitions, 'RESET_VM_DESC')
        assert isinstance(definitions.RESET_VM_DESC, str)

    def test_delete_vm_desc(self):
        """Test DELETE_VM_DESC is defined."""
        assert hasattr(definitions, 'DELETE_VM_DESC')
        assert isinstance(definitions.DELETE_VM_DESC, str)
        assert "WARNING" in definitions.DELETE_VM_DESC


class TestContainerDefinitions:
    """Test container tool descriptions."""

    def test_get_containers_desc(self):
        """Test GET_CONTAINERS_DESC is defined."""
        assert hasattr(definitions, 'GET_CONTAINERS_DESC')
        assert isinstance(definitions.GET_CONTAINERS_DESC, str)

    def test_start_container_desc(self):
        """Test START_CONTAINER_DESC is defined."""
        assert hasattr(definitions, 'START_CONTAINER_DESC')
        assert isinstance(definitions.START_CONTAINER_DESC, str)

    def test_stop_container_desc(self):
        """Test STOP_CONTAINER_DESC is defined."""
        assert hasattr(definitions, 'STOP_CONTAINER_DESC')
        assert isinstance(definitions.STOP_CONTAINER_DESC, str)

    def test_restart_container_desc(self):
        """Test RESTART_CONTAINER_DESC is defined."""
        assert hasattr(definitions, 'RESTART_CONTAINER_DESC')
        assert isinstance(definitions.RESTART_CONTAINER_DESC, str)

    def test_update_container_resources_desc(self):
        """Test UPDATE_CONTAINER_RESOURCES_DESC is defined."""
        assert hasattr(definitions, 'UPDATE_CONTAINER_RESOURCES_DESC')
        assert isinstance(definitions.UPDATE_CONTAINER_RESOURCES_DESC, str)

    def test_create_container_desc(self):
        """Test CREATE_CONTAINER_DESC is defined."""
        assert hasattr(definitions, 'CREATE_CONTAINER_DESC')
        assert isinstance(definitions.CREATE_CONTAINER_DESC, str)

    def test_delete_container_desc(self):
        """Test DELETE_CONTAINER_DESC is defined."""
        assert hasattr(definitions, 'DELETE_CONTAINER_DESC')
        assert isinstance(definitions.DELETE_CONTAINER_DESC, str)

    def test_execute_container_command_desc(self):
        """Test EXECUTE_CONTAINER_COMMAND_DESC is defined."""
        assert hasattr(definitions, 'EXECUTE_CONTAINER_COMMAND_DESC')
        assert isinstance(definitions.EXECUTE_CONTAINER_COMMAND_DESC, str)


class TestStorageAndClusterDefinitions:
    """Test storage and cluster tool descriptions."""

    def test_get_storage_desc(self):
        """Test GET_STORAGE_DESC is defined."""
        assert hasattr(definitions, 'GET_STORAGE_DESC')
        assert isinstance(definitions.GET_STORAGE_DESC, str)

    def test_get_cluster_status_desc(self):
        """Test GET_CLUSTER_STATUS_DESC is defined."""
        assert hasattr(definitions, 'GET_CLUSTER_STATUS_DESC')
        assert isinstance(definitions.GET_CLUSTER_STATUS_DESC, str)


class TestSnapshotDefinitions:
    """Test snapshot tool descriptions."""

    def test_list_snapshots_desc(self):
        """Test LIST_SNAPSHOTS_DESC is defined."""
        assert hasattr(definitions, 'LIST_SNAPSHOTS_DESC')
        assert isinstance(definitions.LIST_SNAPSHOTS_DESC, str)

    def test_create_snapshot_desc(self):
        """Test CREATE_SNAPSHOT_DESC is defined."""
        assert hasattr(definitions, 'CREATE_SNAPSHOT_DESC')
        assert isinstance(definitions.CREATE_SNAPSHOT_DESC, str)

    def test_delete_snapshot_desc(self):
        """Test DELETE_SNAPSHOT_DESC is defined."""
        assert hasattr(definitions, 'DELETE_SNAPSHOT_DESC')
        assert isinstance(definitions.DELETE_SNAPSHOT_DESC, str)

    def test_rollback_snapshot_desc(self):
        """Test ROLLBACK_SNAPSHOT_DESC is defined."""
        assert hasattr(definitions, 'ROLLBACK_SNAPSHOT_DESC')
        assert isinstance(definitions.ROLLBACK_SNAPSHOT_DESC, str)


class TestISOAndBackupDefinitions:
    """Test ISO and backup tool descriptions."""

    def test_list_isos_desc(self):
        """Test LIST_ISOS_DESC is defined."""
        assert hasattr(definitions, 'LIST_ISOS_DESC')
        assert isinstance(definitions.LIST_ISOS_DESC, str)

    def test_list_templates_desc(self):
        """Test LIST_TEMPLATES_DESC is defined."""
        assert hasattr(definitions, 'LIST_TEMPLATES_DESC')
        assert isinstance(definitions.LIST_TEMPLATES_DESC, str)

    def test_download_iso_desc(self):
        """Test DOWNLOAD_ISO_DESC is defined."""
        assert hasattr(definitions, 'DOWNLOAD_ISO_DESC')
        assert isinstance(definitions.DOWNLOAD_ISO_DESC, str)

    def test_delete_iso_desc(self):
        """Test DELETE_ISO_DESC is defined."""
        assert hasattr(definitions, 'DELETE_ISO_DESC')
        assert isinstance(definitions.DELETE_ISO_DESC, str)

    def test_list_backups_desc(self):
        """Test LIST_BACKUPS_DESC is defined."""
        assert hasattr(definitions, 'LIST_BACKUPS_DESC')
        assert isinstance(definitions.LIST_BACKUPS_DESC, str)

    def test_create_backup_desc(self):
        """Test CREATE_BACKUP_DESC is defined."""
        assert hasattr(definitions, 'CREATE_BACKUP_DESC')
        assert isinstance(definitions.CREATE_BACKUP_DESC, str)

    def test_restore_backup_desc(self):
        """Test RESTORE_BACKUP_DESC is defined."""
        assert hasattr(definitions, 'RESTORE_BACKUP_DESC')
        assert isinstance(definitions.RESTORE_BACKUP_DESC, str)

    def test_delete_backup_desc(self):
        """Test DELETE_BACKUP_DESC is defined."""
        assert hasattr(definitions, 'DELETE_BACKUP_DESC')
        assert isinstance(definitions.DELETE_BACKUP_DESC, str)


class TestContainerConfigDefinitions:
    """Test container config tool descriptions."""

    def test_get_container_config_desc(self):
        """Test GET_CONTAINER_CONFIG_DESC is defined."""
        assert hasattr(definitions, 'GET_CONTAINER_CONFIG_DESC')
        assert isinstance(definitions.GET_CONTAINER_CONFIG_DESC, str)

    def test_get_container_ip_desc(self):
        """Test GET_CONTAINER_IP_DESC is defined."""
        assert hasattr(definitions, 'GET_CONTAINER_IP_DESC')
        assert isinstance(definitions.GET_CONTAINER_IP_DESC, str)

    def test_update_container_ssh_keys_desc(self):
        """Test UPDATE_CONTAINER_SSH_KEYS_DESC is defined."""
        assert hasattr(definitions, 'UPDATE_CONTAINER_SSH_KEYS_DESC')
        assert isinstance(definitions.UPDATE_CONTAINER_SSH_KEYS_DESC, str)
