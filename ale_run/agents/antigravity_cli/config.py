"""AntigravityCliConfig: per-episode knobs for the Google Antigravity CLI (``agy``).

Antigravity CLI is the successor to Gemini CLI. Unlike every other ALE agent it
is **OAuth-only against Google's own backend** — it cannot route through
OpenRouter and has no API-key / service-account auth. A run therefore reuses a
credential the operator obtains ONCE by logging in interactively on the host:

    ~/.gemini/antigravity-cli/antigravity-oauth-token   (carries a refresh_token)

That file's content is forwarded into the sandbox by the lifecycle env
passthrough (``ANTIGRAVITY_OAUTH_TOKEN`` inline, or ``ANTIGRAVITY_OAUTH_TOKEN_PATH``
pointing at the host file) and written back into place by the deployer, after
which ``agy`` silent-auths headlessly. See the module docstring on the deployer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

# Deny-only tool policy, mirrored from gemini_cli: agy shares the same tool
# catalog and reads the same ``~/.gemini/settings.json`` ``tools.exclude`` list.
# Only persistent-state / interactive / tracker tools are disabled; web + file
# tools stay enabled (internet is allowed by the benchmark).
_DISABLED_TOOLS = (
    "save_memory",
    "activate_skill",
    "get_internal_docs",
    "write_todos",
    "ask_user",
    "enter_plan_mode",
    "exit_plan_mode",
    "update_topic",
    "complete_task",
    "tracker_create_task",
    "tracker_update_task",
    "tracker_get_task",
    "tracker_list_tasks",
    "tracker_add_dependency",
    "tracker_visualize",
)


@dataclass
class AntigravityCliConfig:
    """Tunables for :class:`AntigravityCliDeployer`. Standalone (no shared base)."""

    name: ClassVar[str] = "antigravity-cli"

    # Model display name as printed by ``agy models`` (the CLI accepts these
    # verbatim). Examples: "Gemini 3.1 Pro (High)", "Claude Sonnet 4.6 (Thinking)",
    # "GPT-OSS 120B (Medium)". Empty => let agy use its configured default.
    model: str = "Gemini 3.1 Pro (High)"

    # Bypass all tool-permission prompts (required headless). Maps to
    # ``--dangerously-skip-permissions``.
    dangerously_skip_permissions: bool = True

    # maxSessionTurns in settings.json. -1 = unbounded (wall-clock is the cap).
    max_session_turns: int = -1

    disabled_tools: tuple[str, ...] = _DISABLED_TOOLS

    # Pinned CLI version. The deployer probes ``agy --version`` and (re)installs
    # via the official installer when missing / mismatched.
    cli_version: str = "1.0.10"

    # Override the install source. Empty => official curl installer
    # (https://antigravity.google/cli/install.sh). A direct tarball URL (from the
    # updater manifest) pins an exact build for reproducibility.
    download_url: str = ""
