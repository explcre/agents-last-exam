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

# Deny-only tool policy (written to ``settings.json`` ``tools.exclude``).
# Principle: disable tools that (a) need a human in the loop, or (b) need extra
# config/capability the headless sandbox doesn't provide. These are agy's OWN
# tool names (a demonstration of the mechanism — extend per benchmark policy):
#   - ask_permission / ask_question : interactive, block a headless run.
#   - read_resource                 : needs MCP resources the cua server doesn't expose.
# Everything else (shell, files, web, GUI/cua, …) stays enabled.
_DISABLED_TOOLS = (
    "ask_permission",
    "ask_question",
    "read_resource",
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

    # agy print-mode wait, passed as ``--print-timeout``. agy's OWN default is
    # only 5m, which silently cuts off any longer task (e.g. a slow thinking
    # model, or a multi-step task) before it finishes — the run then has no
    # output. Set it well above any task's wall budget so the orchestration's
    # ``wall_time_s`` is the real cap, not agy's internal timer.
    print_timeout: str = "120m"
