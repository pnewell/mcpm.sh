"""
Claude Desktop (third-party inference, "3P") integration utilities for MCP.

3P mode is regular Claude Desktop pointed at a separate user-data directory:
on every platform Claude derives the 3P data dir by appending ``-3p`` to its
normal data dir. The MCP configuration schema is identical to 1P Claude
Desktop, so this manager differs only in the config file location and reuses
all of :class:`ClaudeDesktopManager`'s behavior (disable/enable, formatting,
remote->stdio proxying, etc.).

In addition, this manager supports an optional "managed" mode. When enabled,
sync operations are redirected to the ``managedMcpServers`` array inside the
ACTIVE configLibrary profile rather than the normal top-level ``mcpServers``
key. Only servers in ``managedMcpServers`` get the full Allow/Ask/Blocked
permission UI and ``toolPolicy`` pre-approval in Claude Desktop 3P. The active
profile is resolved via ``configLibrary/_meta.json`` (its top-level
``appliedId`` names the active profile json file). Managed mode touches only
``managedMcpServers`` and leaves every other profile key, plus the normal
``mcpServers`` key, untouched.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from mcpm.clients.managers.claude_desktop import ClaudeDesktopManager

logger = logging.getLogger(__name__)


class ClaudeDesktop3pManager(ClaudeDesktopManager):
    """Manages Claude Desktop (3P / third-party inference) MCP server configurations."""

    # Client information
    client_key = "claude-desktop-3p"
    display_name = "Claude Desktop (3P)"
    download_url = "https://claude.ai/download"

    def __init__(self, config_path_override: Optional[str] = None, managed: bool = False):
        """Initialize the Claude Desktop 3P client manager.

        Args:
            config_path_override: Optional path to override the default config file location
            managed: When True, sync operations target the ``managedMcpServers`` array
                in the active configLibrary profile instead of the top-level
                ``mcpServers`` key.
        """
        super().__init__(config_path_override=config_path_override)

        self.managed = managed

        if config_path_override:
            self.config_path = config_path_override
        else:
            # Same layout as 1P Claude Desktop, but in the `-3p` data directory.
            if self._system == "Darwin":  # macOS
                self.config_path = os.path.expanduser(
                    "~/Library/Application Support/Claude-3p/claude_desktop_config.json"
                )
            elif self._system == "Windows":
                self.config_path = os.path.join(
                    os.environ.get("APPDATA", ""), "Claude-3p", "claude_desktop_config.json"
                )
            else:
                # Linux (unsupported by Claude Desktop currently, but future-proofing)
                self.config_path = os.path.expanduser("~/.config/Claude-3p/claude_desktop_config.json")

    # ------------------------------------------------------------------
    # Managed-mode helpers
    # ------------------------------------------------------------------
    def _resolve_active_profile_path(self) -> str:
        """Resolve the path to the active configLibrary profile json.

        The 3P data dir is the directory containing ``self.config_path``. Inside
        it, ``configLibrary/_meta.json`` holds a top-level ``appliedId`` naming
        the active profile, whose json lives at
        ``configLibrary/<appliedId>.json``.

        Returns:
            Absolute path to the active profile json file.

        Raises:
            FileNotFoundError: If the meta file or the resolved profile json
                does not exist.
            ValueError: If ``appliedId`` is missing or empty in the meta file.
        """
        data_dir = os.path.dirname(self.config_path)
        meta_path = os.path.join(data_dir, "configLibrary", "_meta.json")

        if not os.path.exists(meta_path):
            raise FileNotFoundError(
                f"Claude 3P configLibrary meta file not found at: {meta_path}. "
                "Make sure Claude Desktop 3P has been launched and has an active profile."
            )

        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        applied_id = meta.get("appliedId")
        if not applied_id:
            raise ValueError(
                f"No active profile found: 'appliedId' is missing or empty in {meta_path}."
            )

        profile_path = os.path.join(data_dir, "configLibrary", f"{applied_id}.json")
        if not os.path.exists(profile_path):
            raise FileNotFoundError(
                f"Active Claude 3P profile json not found at: {profile_path} "
                f"(appliedId='{applied_id}')."
            )

        return profile_path

    @staticmethod
    def _clean_name(server_name: str) -> str:
        """Derive the clean server name by stripping a leading ``mcpm_`` prefix."""
        if server_name.startswith("mcpm_"):
            return server_name[len("mcpm_"):]
        return server_name

    # ------------------------------------------------------------------
    # Config load/save overrides
    # ------------------------------------------------------------------
    def _load_config(self) -> Dict[str, Any]:
        """Load configuration.

        In managed mode, read the active profile json (preserving all keys) and
        ensure ``managedMcpServers`` exists and is a list. Otherwise behave
        exactly like the standard JSON client manager (mcpServers).
        """
        if not self.managed:
            return super()._load_config()

        profile_path = self._resolve_active_profile_path()
        with open(profile_path, "r", encoding="utf-8") as f:
            config = json.load(f)

        if not isinstance(config.get("managedMcpServers"), list):
            config["managedMcpServers"] = []

        return config

    def _save_config(self, config: Dict[str, Any]) -> bool:
        """Save configuration.

        In managed mode, write the full profile dict back to the resolved
        profile path (preserving all other keys). Otherwise behave exactly like
        the standard JSON client manager.
        """
        if not self.managed:
            return super()._save_config(config)

        profile_path = self._resolve_active_profile_path()
        try:
            os.makedirs(os.path.dirname(profile_path), exist_ok=True)
            with open(profile_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Error saving Claude 3P managed profile config: {str(e)}")
            return False

    # ------------------------------------------------------------------
    # Server operations
    # ------------------------------------------------------------------
    def get_servers(self) -> Dict[str, Any]:
        """Get all MCP servers configured for this client.

        In managed mode, return a dict keyed by each entry's clean ``name`` ->
        the entry dict. Otherwise return the standard ``mcpServers`` dict.
        """
        if not self.managed:
            return super().get_servers()

        config = self._load_config()
        result: Dict[str, Any] = {}
        for entry in config.get("managedMcpServers", []):
            if isinstance(entry, dict) and "name" in entry:
                result[entry["name"]] = entry
        return result

    def add_server(self, server_config) -> bool:
        """Add or update a server in the client config.

        In managed mode, upsert an entry into the ``managedMcpServers`` array
        keyed by the clean server name. The command/args/env are rebuilt every
        sync from ``to_client_format``; any pre-existing ``toolPolicy`` for the
        same clean name is merged back onto the rebuilt entry. New servers get
        no ``toolPolicy``.
        """
        if not self.managed:
            return super().add_server(server_config)

        clean_name = self._clean_name(server_config.name)
        client_format = self.to_client_format(server_config)

        config = self._load_config()
        servers = config["managedMcpServers"]

        # Preserve an existing toolPolicy for this server, if any.
        existing_tool_policy = None
        for entry in servers:
            if isinstance(entry, dict) and entry.get("name") == clean_name:
                if isinstance(entry.get("toolPolicy"), dict):
                    existing_tool_policy = entry["toolPolicy"]
                break

        new_entry: Dict[str, Any] = {"name": clean_name, "transport": "stdio", **client_format}
        if existing_tool_policy is not None:
            new_entry["toolPolicy"] = existing_tool_policy

        # Upsert by clean name.
        for idx, entry in enumerate(servers):
            if isinstance(entry, dict) and entry.get("name") == clean_name:
                servers[idx] = new_entry
                break
        else:
            servers.append(new_entry)

        return self._save_config(config)

    def remove_server(self, server_name: str) -> bool:
        """Remove an MCP server from the client config.

        In managed mode, remove any ``managedMcpServers`` entry whose clean name
        matches the target (accepting both ``mcpm_<name>`` and clean ``<name>``).
        """
        if not self.managed:
            return super().remove_server(server_name)

        clean_name = self._clean_name(server_name)

        config = self._load_config()
        servers = config["managedMcpServers"]

        new_servers = [
            entry for entry in servers if not (isinstance(entry, dict) and entry.get("name") == clean_name)
        ]

        if len(new_servers) == len(servers):
            logger.warning(f"Server {server_name} not found in {self.display_name} managed config")
            return False

        config["managedMcpServers"] = new_servers
        return self._save_config(config)

    def list_servers(self) -> List[str]:
        """List all MCP server names in the client config.

        In managed mode, return the clean names from the ``managedMcpServers``
        array.
        """
        if not self.managed:
            return super().list_servers()

        config = self._load_config()
        return [
            entry["name"]
            for entry in config.get("managedMcpServers", [])
            if isinstance(entry, dict) and "name" in entry
        ]

    def get_server(self, server_name: str):
        """Get a server configuration.

        In managed mode, find the entry by clean name and convert it to a
        ServerConfig, passing only the keys ``from_client_format`` understands
        (command, args, env) so that extra keys like ``transport``/``toolPolicy``
        do not break pydantic validation.
        """
        if not self.managed:
            return super().get_server(server_name)

        clean_name = self._clean_name(server_name)
        config = self._load_config()

        for entry in config.get("managedMcpServers", []):
            if isinstance(entry, dict) and entry.get("name") == clean_name:
                client_config: Dict[str, Any] = {}
                for key in ("command", "args", "env"):
                    if key in entry:
                        client_config[key] = entry[key]
                return self.from_client_format(clean_name, client_config)

        logger.debug(f"Server {server_name} not found in {self.display_name} managed config")
        return None
