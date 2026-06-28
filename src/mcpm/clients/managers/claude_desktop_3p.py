"""
Claude Desktop (third-party inference, "3P") integration utilities for MCP.

3P mode is regular Claude Desktop pointed at a separate user-data directory:
on every platform Claude derives the 3P data dir by appending ``-3p`` to its
normal data dir. The MCP configuration schema is identical to 1P Claude
Desktop, so this manager differs only in the config file location and reuses
all of :class:`ClaudeDesktopManager`'s behavior (disable/enable, formatting,
remote->stdio proxying, etc.).
"""

import logging
import os
from typing import Optional

from mcpm.clients.managers.claude_desktop import ClaudeDesktopManager

logger = logging.getLogger(__name__)


class ClaudeDesktop3pManager(ClaudeDesktopManager):
    """Manages Claude Desktop (3P / third-party inference) MCP server configurations."""

    # Client information
    client_key = "claude-desktop-3p"
    display_name = "Claude Desktop (3P)"
    download_url = "https://claude.ai/download"

    def __init__(self, config_path_override: Optional[str] = None):
        """Initialize the Claude Desktop 3P client manager.

        Args:
            config_path_override: Optional path to override the default config file location
        """
        super().__init__(config_path_override=config_path_override)

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
