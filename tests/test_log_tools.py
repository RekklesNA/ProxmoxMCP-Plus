"""Unit tests for LogTools.

Follows the same pattern as test_tool_user_paths.py:
- Build a Mock() proxmox API object
- Instantiate LogTools directly
- Assert return type, content, and which API endpoint was called
- Assert optional params are omitted when not provided (not forwarded as None)
"""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from proxmox_mcp.tools.logs import LogTools


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tools(proxmox: Mock | None = None) -> LogTools:
    """Return a LogTools instance backed by a Mock Proxmox API."""
    return LogTools(proxmox or Mock())


def _node_api(proxmox: Mock) -> Mock:
    """Return the mock for the node-scoped API (proxmox.nodes(...))."""
    return proxmox.nodes.return_value


# ---------------------------------------------------------------------------
# get_node_syslog
# ---------------------------------------------------------------------------

class TestGetNodeSyslog:
    def test_returns_content_list(self):
        proxmox = Mock()
        _node_api(proxmox).syslog.get.return_value = [
            {"n": 1, "t": "Jun  1 10:00:01 pve pvedaemon: task started"},
        ]
        result = _make_tools(proxmox).get_node_syslog("pve")

        assert len(result) == 1
        assert result[0].type == "text"

    def test_output_contains_log_line(self):
        proxmox = Mock()
        _node_api(proxmox).syslog.get.return_value = [
            {"n": 1, "t": "pvedaemon: task started"},
            {"n": 2, "t": "pveproxy: connection from 10.0.0.1"},
        ]
        result = _make_tools(proxmox).get_node_syslog("pve")

        assert "pvedaemon: task started" in result[0].text
        assert "pveproxy: connection from 10.0.0.1" in result[0].text

    def test_header_contains_node_name(self):
        proxmox = Mock()
        _node_api(proxmox).syslog.get.return_value = [{"n": 1, "t": "line"}]
        result = _make_tools(proxmox).get_node_syslog("pve1")

        assert "pve1" in result[0].text

    def test_default_limit_forwarded(self):
        proxmox = Mock()
        _node_api(proxmox).syslog.get.return_value = []
        _make_tools(proxmox).get_node_syslog("pve")

        proxmox.nodes.assert_called_once_with("pve")
        call_kwargs = _node_api(proxmox).syslog.get.call_args.kwargs
        assert call_kwargs["limit"] == 100

    def test_custom_limit_forwarded(self):
        proxmox = Mock()
        _node_api(proxmox).syslog.get.return_value = []
        _make_tools(proxmox).get_node_syslog("pve", limit=25)

        call_kwargs = _node_api(proxmox).syslog.get.call_args.kwargs
        assert call_kwargs["limit"] == 25

    def test_none_optional_params_not_forwarded(self):
        """start, since, until, service must not appear in the API call when None."""
        proxmox = Mock()
        _node_api(proxmox).syslog.get.return_value = []
        _make_tools(proxmox).get_node_syslog("pve")

        call_kwargs = _node_api(proxmox).syslog.get.call_args.kwargs
        assert "start" not in call_kwargs
        assert "since" not in call_kwargs
        assert "until" not in call_kwargs
        assert "service" not in call_kwargs

    def test_optional_params_forwarded_when_supplied(self):
        proxmox = Mock()
        _node_api(proxmox).syslog.get.return_value = []
        _make_tools(proxmox).get_node_syslog(
            "pve", start=10, since="2024-01-01", until="2024-01-31", service="pvedaemon"
        )

        call_kwargs = _node_api(proxmox).syslog.get.call_args.kwargs
        assert call_kwargs["start"] == 10
        assert call_kwargs["since"] == "2024-01-01"
        assert call_kwargs["until"] == "2024-01-31"
        assert call_kwargs["service"] == "pvedaemon"

    def test_empty_response_returns_message(self):
        proxmox = Mock()
        _node_api(proxmox).syslog.get.return_value = []
        result = _make_tools(proxmox).get_node_syslog("pve")

        assert "No syslog entries" in result[0].text
        assert "pve" in result[0].text

    def test_string_entries_rendered_directly(self):
        """Syslog entries that are plain strings (not dicts) should render fine."""
        proxmox = Mock()
        _node_api(proxmox).syslog.get.return_value = ["raw log line"]
        result = _make_tools(proxmox).get_node_syslog("pve")

        assert "raw log line" in result[0].text

    def test_api_error_propagates(self):
        proxmox = Mock()
        _node_api(proxmox).syslog.get.side_effect = RuntimeError("connection refused")

        with pytest.raises(RuntimeError, match="connection refused"):
            _make_tools(proxmox).get_node_syslog("pve")


# ---------------------------------------------------------------------------
# get_task_log
# ---------------------------------------------------------------------------

class TestGetTaskLog:
    _upid = "UPID:pve:00001234:qmstart:100:root@pam:"
    _sample_log = [
        {"n": 1, "t": "starting task"},
        {"n": 2, "t": "task finished successfully"},
    ]

    def test_returns_content_list(self):
        proxmox = Mock()
        proxmox.nodes.return_value.tasks.return_value.log.get.return_value = self._sample_log
        result = _make_tools(proxmox).get_task_log("pve", self._upid)

        assert len(result) == 1
        assert result[0].type == "text"

    def test_output_contains_log_lines(self):
        proxmox = Mock()
        proxmox.nodes.return_value.tasks.return_value.log.get.return_value = self._sample_log
        result = _make_tools(proxmox).get_task_log("pve", self._upid)

        assert "starting task" in result[0].text
        assert "task finished successfully" in result[0].text

    def test_header_contains_upid(self):
        proxmox = Mock()
        proxmox.nodes.return_value.tasks.return_value.log.get.return_value = self._sample_log
        result = _make_tools(proxmox).get_task_log("pve", self._upid)

        assert self._upid in result[0].text

    def test_default_limit_forwarded(self):
        proxmox = Mock()
        proxmox.nodes.return_value.tasks.return_value.log.get.return_value = []
        _make_tools(proxmox).get_task_log("pve", self._upid)

        call_kwargs = proxmox.nodes.return_value.tasks.return_value.log.get.call_args.kwargs
        assert call_kwargs["limit"] == 50

    def test_start_param_not_forwarded_when_none(self):
        proxmox = Mock()
        proxmox.nodes.return_value.tasks.return_value.log.get.return_value = []
        _make_tools(proxmox).get_task_log("pve", self._upid)

        call_kwargs = proxmox.nodes.return_value.tasks.return_value.log.get.call_args.kwargs
        assert "start" not in call_kwargs

    def test_start_and_limit_forwarded_when_supplied(self):
        proxmox = Mock()
        proxmox.nodes.return_value.tasks.return_value.log.get.return_value = []
        _make_tools(proxmox).get_task_log("pve", self._upid, start=100, limit=25)

        call_kwargs = proxmox.nodes.return_value.tasks.return_value.log.get.call_args.kwargs
        assert call_kwargs["start"] == 100
        assert call_kwargs["limit"] == 25

    def test_correct_node_and_upid_passed(self):
        proxmox = Mock()
        proxmox.nodes.return_value.tasks.return_value.log.get.return_value = []
        _make_tools(proxmox).get_task_log("pve", self._upid)

        proxmox.nodes.assert_called_once_with("pve")
        proxmox.nodes.return_value.tasks.assert_called_once_with(self._upid)

    def test_empty_response_returns_message(self):
        proxmox = Mock()
        proxmox.nodes.return_value.tasks.return_value.log.get.return_value = []
        result = _make_tools(proxmox).get_task_log("pve", self._upid)

        assert "No log entries" in result[0].text
        assert self._upid in result[0].text

    def test_string_log_entries_rendered_directly(self):
        proxmox = Mock()
        proxmox.nodes.return_value.tasks.return_value.log.get.return_value = ["plain text line"]
        result = _make_tools(proxmox).get_task_log("pve", self._upid)

        assert "plain text line" in result[0].text

    def test_api_error_propagates(self):
        proxmox = Mock()
        proxmox.nodes.return_value.tasks.return_value.log.get.side_effect = RuntimeError(
            "task not found"
        )

        with pytest.raises(ValueError, match="task not found"):
            _make_tools(proxmox).get_task_log("pve", self._upid)


# ---------------------------------------------------------------------------
# get_cluster_log
# ---------------------------------------------------------------------------

class TestGetClusterLog:
    _sample_entries = [
        {
            "time": 1700000000,
            "node": "pve",
            "user": "root@pam",
            "pri": 6,
            "tag": "pvedaemon",
            "msg": "starting task UPID:pve:...",
        },
        {
            "time": 1700000060,
            "node": "pve2",
            "user": "user@pve",
            "pri": 5,
            "tag": "pveproxy",
            "msg": "login successful",
        },
    ]

    def test_returns_content_list(self):
        proxmox = Mock()
        proxmox.cluster.log.get.return_value = self._sample_entries
        result = _make_tools(proxmox).get_cluster_log()

        assert len(result) == 1
        assert result[0].type == "text"

    def test_output_contains_entry_fields(self):
        proxmox = Mock()
        proxmox.cluster.log.get.return_value = self._sample_entries
        result = _make_tools(proxmox).get_cluster_log()

        assert "pvedaemon" in result[0].text
        assert "starting task UPID:pve:..." in result[0].text
        assert "pve2" in result[0].text
        assert "login successful" in result[0].text

    def test_default_max_forwarded_as_max(self):
        """API param is 'max'; the tool arg is max_entries."""
        proxmox = Mock()
        proxmox.cluster.log.get.return_value = []
        _make_tools(proxmox).get_cluster_log()

        call_kwargs = proxmox.cluster.log.get.call_args.kwargs
        assert call_kwargs["max"] == 50
        assert "max_entries" not in call_kwargs

    def test_custom_max_forwarded(self):
        proxmox = Mock()
        proxmox.cluster.log.get.return_value = []
        _make_tools(proxmox).get_cluster_log(max_entries=200)

        call_kwargs = proxmox.cluster.log.get.call_args.kwargs
        assert call_kwargs["max"] == 200

    def test_empty_response_returns_message(self):
        proxmox = Mock()
        proxmox.cluster.log.get.return_value = []
        result = _make_tools(proxmox).get_cluster_log()

        assert "No cluster log entries" in result[0].text

    def test_api_error_propagates(self):
        proxmox = Mock()
        proxmox.cluster.log.get.side_effect = RuntimeError("connection refused")

        with pytest.raises(RuntimeError, match="connection refused"):
            _make_tools(proxmox).get_cluster_log()


# ---------------------------------------------------------------------------
# get_node_firewall_log
# ---------------------------------------------------------------------------

class TestGetNodeFirewallLog:
    def test_returns_content_list(self):
        proxmox = Mock()
        _node_api(proxmox).firewall.log.get.return_value = [
            {"n": 1, "t": "0 6 tap100i0-IN 01/Jan/2024 ACCEPT: ..."},
        ]
        result = _make_tools(proxmox).get_node_firewall_log("pve")

        assert len(result) == 1
        assert result[0].type == "text"
        assert "ACCEPT" in result[0].text

    def test_default_limit_forwarded(self):
        proxmox = Mock()
        _node_api(proxmox).firewall.log.get.return_value = []
        _make_tools(proxmox).get_node_firewall_log("pve")

        proxmox.nodes.assert_called_once_with("pve")
        call_kwargs = _node_api(proxmox).firewall.log.get.call_args.kwargs
        assert call_kwargs["limit"] == 100

    def test_none_optional_params_not_forwarded(self):
        proxmox = Mock()
        _node_api(proxmox).firewall.log.get.return_value = []
        _make_tools(proxmox).get_node_firewall_log("pve")

        call_kwargs = _node_api(proxmox).firewall.log.get.call_args.kwargs
        assert "start" not in call_kwargs
        assert "since" not in call_kwargs
        assert "until" not in call_kwargs

    def test_optional_params_forwarded_when_supplied(self):
        proxmox = Mock()
        _node_api(proxmox).firewall.log.get.return_value = []
        _make_tools(proxmox).get_node_firewall_log(
            "pve", limit=25, start=10, since=1700000000, until=1700003600
        )

        call_kwargs = _node_api(proxmox).firewall.log.get.call_args.kwargs
        assert call_kwargs["limit"] == 25
        assert call_kwargs["start"] == 10
        assert call_kwargs["since"] == 1700000000
        assert call_kwargs["until"] == 1700003600

    def test_empty_response_returns_message(self):
        proxmox = Mock()
        _node_api(proxmox).firewall.log.get.return_value = []
        result = _make_tools(proxmox).get_node_firewall_log("pve")

        assert "No firewall log entries" in result[0].text

    def test_api_error_propagates(self):
        proxmox = Mock()
        _node_api(proxmox).firewall.log.get.side_effect = RuntimeError("connection refused")

        with pytest.raises(RuntimeError, match="connection refused"):
            _make_tools(proxmox).get_node_firewall_log("pve")


# ---------------------------------------------------------------------------
# get_guest_firewall_log
# ---------------------------------------------------------------------------

class TestGetGuestFirewallLog:
    def test_qemu_path_used_by_default(self):
        proxmox = Mock()
        _node_api(proxmox).qemu.return_value.firewall.log.get.return_value = [
            {"n": 1, "t": "100 6 tap100i0-IN ACCEPT: ..."},
        ]
        result = _make_tools(proxmox).get_guest_firewall_log("pve", 100)

        proxmox.nodes.assert_called_once_with("pve")
        _node_api(proxmox).qemu.assert_called_once_with(100)
        assert "ACCEPT" in result[0].text

    def test_lxc_path_used_when_requested(self):
        proxmox = Mock()
        _node_api(proxmox).lxc.return_value.firewall.log.get.return_value = [
            {"n": 1, "t": "101 6 veth101i0-IN DROP: ..."},
        ]
        result = _make_tools(proxmox).get_guest_firewall_log("pve", 101, vm_type="lxc")

        _node_api(proxmox).lxc.assert_called_once_with(101)
        _node_api(proxmox).qemu.assert_not_called()
        assert "DROP" in result[0].text

    def test_invalid_vm_type_raises(self):
        proxmox = Mock()

        with pytest.raises(ValueError, match="Invalid vm_type"):
            _make_tools(proxmox).get_guest_firewall_log("pve", 100, vm_type="openvz")

    def test_default_limit_forwarded(self):
        proxmox = Mock()
        _node_api(proxmox).qemu.return_value.firewall.log.get.return_value = []
        _make_tools(proxmox).get_guest_firewall_log("pve", 100)

        call_kwargs = _node_api(proxmox).qemu.return_value.firewall.log.get.call_args.kwargs
        assert call_kwargs["limit"] == 100

    def test_none_optional_params_not_forwarded(self):
        proxmox = Mock()
        _node_api(proxmox).qemu.return_value.firewall.log.get.return_value = []
        _make_tools(proxmox).get_guest_firewall_log("pve", 100)

        call_kwargs = _node_api(proxmox).qemu.return_value.firewall.log.get.call_args.kwargs
        assert "start" not in call_kwargs
        assert "since" not in call_kwargs
        assert "until" not in call_kwargs

    def test_optional_params_forwarded_when_supplied(self):
        proxmox = Mock()
        _node_api(proxmox).qemu.return_value.firewall.log.get.return_value = []
        _make_tools(proxmox).get_guest_firewall_log(
            "pve", 100, limit=10, start=5, since=1700000000, until=1700003600
        )

        call_kwargs = _node_api(proxmox).qemu.return_value.firewall.log.get.call_args.kwargs
        assert call_kwargs["limit"] == 10
        assert call_kwargs["start"] == 5
        assert call_kwargs["since"] == 1700000000
        assert call_kwargs["until"] == 1700003600

    def test_empty_response_returns_message(self):
        proxmox = Mock()
        _node_api(proxmox).qemu.return_value.firewall.log.get.return_value = []
        result = _make_tools(proxmox).get_guest_firewall_log("pve", 100)

        assert "No firewall log (qemu 100) entries" in result[0].text

    def test_api_error_propagates(self):
        proxmox = Mock()
        _node_api(proxmox).qemu.return_value.firewall.log.get.side_effect = RuntimeError(
            "permission denied"
        )

        with pytest.raises(ValueError, match="permission denied"):
            _make_tools(proxmox).get_guest_firewall_log("pve", 100)
