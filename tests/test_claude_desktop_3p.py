"""Tests for the Claude Desktop 3P (third-party inference) client manager."""

import os

from mcpm.clients.client_registry import ClientRegistry
from mcpm.clients.managers.claude_desktop import ClaudeDesktopManager
from mcpm.clients.managers.claude_desktop_3p import ClaudeDesktop3pManager


def test_claude_desktop_3p_is_registered():
    mgr = ClientRegistry.get_client_manager("claude-desktop-3p")
    assert isinstance(mgr, ClaudeDesktop3pManager)
    assert mgr.client_key == "claude-desktop-3p"


def test_claude_desktop_3p_uses_3p_data_dir():
    mgr = ClaudeDesktop3pManager()
    one_p = ClaudeDesktopManager()
    # 3P config lives in the `-3p` data dir, separate from the 1P data dir,
    # but with the same file name and schema.
    assert os.path.basename(os.path.dirname(mgr.config_path)) == "Claude-3p"
    assert os.path.basename(os.path.dirname(one_p.config_path)) == "Claude"
    assert mgr.config_path != one_p.config_path
    assert os.path.basename(mgr.config_path) == "claude_desktop_config.json"


def test_claude_desktop_3p_respects_override(tmp_path):
    override = str(tmp_path / "custom_config.json")
    mgr = ClaudeDesktop3pManager(config_path_override=override)
    assert mgr.config_path == override
