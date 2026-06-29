"""Tests for the Claude Desktop 3P (third-party inference) client manager."""

import json
import os

from mcpm.clients.client_registry import ClientRegistry
from mcpm.clients.managers.claude_desktop import ClaudeDesktopManager
from mcpm.clients.managers.claude_desktop_3p import ClaudeDesktop3pManager
from mcpm.core.schema import STDIOServerConfig


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


# ---------------------------------------------------------------------------
# Managed-mode tests
# ---------------------------------------------------------------------------


def _build_fake_3p(tmp_path):
    """Build a fake 3P data dir with a configLibrary + active profile.

    Returns (config_path_override, profile_path).
    """
    config_lib = tmp_path / "configLibrary"
    config_lib.mkdir(parents=True, exist_ok=True)

    (config_lib / "_meta.json").write_text(json.dumps({"appliedId": "prof1"}))

    profile = {
        "inferenceModels": ["model-a", "model-b"],
        "inferenceGatewayBaseUrl": "https://gateway.example.com",
        "managedMcpServers": [
            {
                "name": "github",
                "transport": "stdio",
                "command": "mcpm",
                "args": ["run", "github"],
                "toolPolicy": {"create_issue": "allow"},
            }
        ],
    }
    profile_path = config_lib / "prof1.json"
    profile_path.write_text(json.dumps(profile, indent=2))

    config_path_override = str(tmp_path / "claude_desktop_config.json")
    return config_path_override, str(profile_path)


def test_managed_resolve_active_profile_path(tmp_path):
    config_path_override, profile_path = _build_fake_3p(tmp_path)
    mgr = ClaudeDesktop3pManager(config_path_override=config_path_override, managed=True)
    assert mgr._resolve_active_profile_path() == profile_path
    assert mgr._resolve_active_profile_path() == str(tmp_path / "configLibrary" / "prof1.json")


def test_managed_add_server_new_entry(tmp_path):
    config_path_override, profile_path = _build_fake_3p(tmp_path)
    mgr = ClaudeDesktop3pManager(config_path_override=config_path_override, managed=True)

    # Command layer passes a mcpm_-prefixed name; manager strips it to clean name.
    mgr.add_server(STDIOServerConfig(name="mcpm_filesystem", command="mcpm", args=["run", "filesystem"]))

    with open(profile_path, "r", encoding="utf-8") as f:
        profile = json.load(f)

    # Other keys preserved untouched.
    assert profile["inferenceModels"] == ["model-a", "model-b"]
    assert profile["inferenceGatewayBaseUrl"] == "https://gateway.example.com"

    assert isinstance(profile["managedMcpServers"], list)
    entry = next(e for e in profile["managedMcpServers"] if e["name"] == "filesystem")
    assert entry["transport"] == "stdio"
    assert entry["name"] == "filesystem"  # clean name, no mcpm_ prefix
    assert entry["command"] == "mcpm"
    assert entry["args"] == ["run", "filesystem"]
    assert "toolPolicy" not in entry  # new servers get no toolPolicy


def test_managed_readd_preserves_tool_policy(tmp_path):
    config_path_override, profile_path = _build_fake_3p(tmp_path)
    mgr = ClaudeDesktop3pManager(config_path_override=config_path_override, managed=True)

    # Re-add the existing github server; its toolPolicy must be preserved.
    mgr.add_server(STDIOServerConfig(name="mcpm_github", command="mcpm", args=["run", "github"]))

    with open(profile_path, "r", encoding="utf-8") as f:
        profile = json.load(f)

    github = next(e for e in profile["managedMcpServers"] if e["name"] == "github")
    assert github["toolPolicy"] == {"create_issue": "allow"}
    assert github["command"] == "mcpm"
    assert github["args"] == ["run", "github"]
    assert github["transport"] == "stdio"
    # Other keys still intact.
    assert profile["inferenceModels"] == ["model-a", "model-b"]
    # Still exactly one github entry (upsert, not duplicate).
    assert len([e for e in profile["managedMcpServers"] if e["name"] == "github"]) == 1


def test_managed_get_servers_keyed_by_clean_name(tmp_path):
    config_path_override, _ = _build_fake_3p(tmp_path)
    mgr = ClaudeDesktop3pManager(config_path_override=config_path_override, managed=True)

    mgr.add_server(STDIOServerConfig(name="mcpm_filesystem", command="mcpm", args=["run", "filesystem"]))

    servers = mgr.get_servers()
    assert set(servers.keys()) == {"github", "filesystem"}
    assert servers["github"]["command"] == "mcpm"
    assert servers["filesystem"]["args"] == ["run", "filesystem"]


def test_managed_get_server_returns_server_config(tmp_path):
    config_path_override, _ = _build_fake_3p(tmp_path)
    mgr = ClaudeDesktop3pManager(config_path_override=config_path_override, managed=True)

    mgr.add_server(STDIOServerConfig(name="mcpm_filesystem", command="mcpm", args=["run", "filesystem"]))

    # Both the mcpm_-prefixed and clean names resolve.
    by_prefixed = mgr.get_server("mcpm_filesystem")
    by_clean = mgr.get_server("filesystem")
    assert by_prefixed is not None
    assert by_clean is not None
    assert by_prefixed.command == "mcpm"
    assert by_clean.command == "mcpm"
    assert by_clean.args == ["run", "filesystem"]

    # An entry that carries a toolPolicy still converts cleanly.
    github = mgr.get_server("github")
    assert github is not None
    assert github.command == "mcpm"


def test_managed_remove_server(tmp_path):
    config_path_override, profile_path = _build_fake_3p(tmp_path)
    mgr = ClaudeDesktop3pManager(config_path_override=config_path_override, managed=True)

    mgr.add_server(STDIOServerConfig(name="mcpm_filesystem", command="mcpm", args=["run", "filesystem"]))

    # Remove via the mcpm_-prefixed name.
    assert mgr.remove_server("mcpm_github") is True

    with open(profile_path, "r", encoding="utf-8") as f:
        profile = json.load(f)
    names = [e["name"] for e in profile["managedMcpServers"]]
    assert "github" not in names
    assert "filesystem" in names

    # Removing via the clean name also works.
    assert mgr.remove_server("filesystem") is True
    with open(profile_path, "r", encoding="utf-8") as f:
        profile = json.load(f)
    assert profile["managedMcpServers"] == []

    # Removing a missing server returns False.
    assert mgr.remove_server("nope") is False


def test_managed_does_not_touch_mcp_servers_file(tmp_path):
    config_path_override, _ = _build_fake_3p(tmp_path)
    mgr = ClaudeDesktop3pManager(config_path_override=config_path_override, managed=True)

    mgr.add_server(STDIOServerConfig(name="mcpm_filesystem", command="mcpm", args=["run", "filesystem"]))
    mgr.remove_server("mcpm_github")

    # Managed operations never write the standard claude_desktop_config.json.
    if os.path.exists(config_path_override):
        with open(config_path_override, "r", encoding="utf-8") as f:
            standard = json.load(f)
        assert not standard.get("mcpServers")
    else:
        assert not os.path.exists(config_path_override)


def test_non_managed_uses_standard_mcp_servers(tmp_path):
    # With managed=False the 3P manager behaves like the standard manager:
    # add_server writes to mcpServers in claude_desktop_config.json, and does
    # NOT touch the profile json.
    config_path_override, profile_path = _build_fake_3p(tmp_path)
    mgr = ClaudeDesktop3pManager(config_path_override=config_path_override, managed=False)

    mgr.add_server(STDIOServerConfig(name="mcpm_filesystem", command="mcpm", args=["run", "filesystem"]))

    with open(config_path_override, "r", encoding="utf-8") as f:
        standard = json.load(f)
    assert "mcpm_filesystem" in standard["mcpServers"]
    assert standard["mcpServers"]["mcpm_filesystem"]["command"] == "mcpm"

    # The profile json's managedMcpServers is untouched (still just github).
    with open(profile_path, "r", encoding="utf-8") as f:
        profile = json.load(f)
    names = [e["name"] for e in profile["managedMcpServers"]]
    assert names == ["github"]
