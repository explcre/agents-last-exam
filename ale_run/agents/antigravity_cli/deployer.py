"""AntigravityCliDeployer — drives the Google Antigravity CLI (``agy``).

Shape: in-sandbox CLI (``executor=sandbox``), same as gemini_cli/claude_code.

The one thing that makes Antigravity different from every other ALE agent is
auth. ``agy`` is a closed native Go binary that authenticates **only** via Google
OAuth against Google's own backend — no OpenRouter, no API key, no service
account. So instead of forwarding an API key, this deployer forwards a
**credential file** the operator produced by logging in once on the host:

  1. host (one-time):   ``agy``  → browser login → writes
     ``~/.gemini/antigravity-cli/antigravity-oauth-token`` (contains a refresh_token).
  2. env passthrough:   the lifecycle materialises that file's content into
     ``ANTIGRAVITY_OAUTH_TOKEN`` (or passes ``ANTIGRAVITY_OAUTH_TOKEN_PATH``).
  3. install() here:    writes it back to the same path inside the sandbox and
     ``chmod 600`` it, after which ``agy`` silent-auths headlessly.

GUI comes from the shared cua MCP bridge via ``~/.gemini/settings.json`` (agy
reads the same gemini-cli settings file). ``agy`` has no ``--output-format``, so
the transcript is the captured stdout; the rich step log is a sqlite ``.db``
under ``conversations/`` which is pulled as a hot artifact for later parsing.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import ClassVar

from ale_run.base_interface import (
    AgentRunResult,
    BaseAgentDeployer,
    StepMetrics,
    TrajectoryBuilder,
)

from .config import AntigravityCliConfig

logger = logging.getLogger(__name__)

_POLL_INTERVAL_S = 2.0
_TERM_GRACE_S = 2.0
_VERSION_RE = re.compile(r"(\d+\.\d+\.\d+)")

# agy stores its OAuth credential here (shared ~/.gemini home, agy-specific dir).
_TOKEN_RELPATH = (".gemini", "antigravity-cli", "antigravity-oauth-token")
_ACCOUNTS_RELPATH = (".gemini", "google_accounts.json")


def _installed_version(agy_path: str) -> str | None:
    try:
        probe = subprocess.run(
            [agy_path, "--version"], capture_output=True, text=True, timeout=30,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    m = _VERSION_RE.search((probe.stdout or "") + (probe.stderr or ""))
    return m.group(1) if m else None


def _find_agy(local_prefix: str) -> str | None:
    """Resolve the agy binary, preferring our ``~/.local/bin`` install.

    The sandbox entry runs without a login shell, so ``~/.local/bin`` may not be
    on PATH and ``shutil.which`` misses the installer-dropped binary."""
    p = shutil.which("agy")
    if p:
        return p
    cand = os.path.join(local_prefix, "bin", "agy")
    return cand if os.path.isfile(cand) else None


class AntigravityCliDeployer(BaseAgentDeployer):
    """Stdlib-only deployer for the Google ``agy`` CLI."""

    default_executor: ClassVar[str] = "sandbox"
    supported_executors: ClassVar[frozenset[str]] = frozenset({"sandbox"})
    hot_artifacts: ClassVar[tuple[str, ...]] = ("transcript.txt", "stderr.log")

    @property
    def version(self) -> str | None:
        cfg: AntigravityCliConfig = self.config  # type: ignore[assignment]
        return cfg.cli_version

    # =========================================================================
    # install
    # =========================================================================

    async def install(self) -> None:
        cfg: AntigravityCliConfig = self.config  # type: ignore[assignment]
        sandbox = self.executor.sandbox

        home = os.path.expanduser("~")
        local_prefix = os.path.join(home, ".local")

        # 1. locate / install agy. The official installer drops a native binary
        #    at ~/.local/bin/agy and refuses if one already exists, so probe
        #    first and only (re)install when missing or the version mismatches.
        agy = _find_agy(local_prefix)
        installed = await asyncio.to_thread(_installed_version, agy) if agy else None
        if not agy or (cfg.cli_version and installed and installed != cfg.cli_version):
            if agy and installed != cfg.cli_version:
                logger.info("antigravity_cli: %s != pinned %s — reinstalling",
                            installed, cfg.cli_version)
            await self._install_agy(cfg, local_prefix)
            agy = _find_agy(local_prefix)
            if not agy:
                raise RuntimeError("antigravity_cli: 'agy' not found after install")
            installed = await asyncio.to_thread(_installed_version, agy)
        self._agy_path = agy
        # ~/.local/bin on PATH so launch() and any self-update find it.
        bin_dir = os.path.join(local_prefix, "bin")
        if bin_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        logger.info("antigravity_cli: CLI ok — agy %s at %s", installed or "?", agy)

        # 2. clean work dir
        wd = Path(self.executor.work_dir)
        wd.mkdir(parents=True, exist_ok=True)

        # 3. inject the OAuth credential the operator produced on the host.
        self._write_oauth_token()

        # 4. cua GUI bridge + settings.json (agy reads ~/.gemini/settings.json,
        #    same file gemini-cli uses). Idempotent bridge install.
        from ale_run.agents._bootstrap import cua_bridge_env, ensure_cua_mcp_server
        await ensure_cua_mcp_server(sandbox)

        gemini_home = Path(home) / ".gemini"
        gemini_home.mkdir(parents=True, exist_ok=True)
        cua_server = {
            "cua": {
                "command": sandbox.node,
                "args": [self._join(sandbox.mcp_server_dir, "src", "index.js",
                                    is_linux=sandbox.is_linux)],
                "env": cua_bridge_env(self.executor),
            },
        }
        # agy reads its MCP servers from ~/.gemini/config/mcp_config.json (its
        # NATIVE config), NOT the gemini-cli settings.json — that is where the
        # cua GUI tools (screenshot/click/type/…) must be declared to load.
        config_dir = gemini_home / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        (config_dir / "mcp_config.json").write_text(
            json.dumps({"mcpServers": cua_server}, indent=2), encoding="utf-8",
        )
        # settings.json carries gemini-compat knobs agy may honor (tool excludes,
        # session-turn cap). Harmless if ignored.
        settings = {
            "tools": {"exclude": list(cfg.disabled_tools)},
            "maxSessionTurns": cfg.max_session_turns,
        }
        (gemini_home / "settings.json").write_text(
            json.dumps(settings, indent=2), encoding="utf-8",
        )
        logger.info("antigravity_cli: config staged at %s (cua -> config/mcp_config.json)",
                    gemini_home)

    async def _install_agy(self, cfg: AntigravityCliConfig, local_prefix: str) -> None:
        """Install agy via the official installer (or a pinned tarball URL)."""
        env = {**os.environ}
        if cfg.download_url:
            # Pinned tarball: extract the `agy` binary into ~/.local/bin.
            bin_dir = os.path.join(local_prefix, "bin")
            os.makedirs(bin_dir, exist_ok=True)
            cmd = (
                f"set -e; tmp=$(mktemp -d); "
                f"curl -fsSL {cfg.download_url!r} -o $tmp/agy.tgz; "
                f"tar -xzf $tmp/agy.tgz -C $tmp; "
                f"f=$(find $tmp -name agy -type f | head -1); "
                f"install -m755 $f {bin_dir}/agy; rm -rf $tmp"
            )
        else:
            cmd = "curl -fsSL https://antigravity.google/cli/install.sh | bash"
        proc = await asyncio.to_thread(
            subprocess.run, ["bash", "-lc", cmd],
            capture_output=True, text=True, timeout=300, env=env,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                f"antigravity_cli: install failed (rc={proc.returncode}): "
                f"{(proc.stderr or '')[:500]}"
            )
        logger.info("antigravity_cli: installed — %s", (proc.stdout or "").strip()[-200:])

    def _write_oauth_token(self) -> None:
        """Write agy's OAuth credential into place from env passthrough.

        Resolution order (mirrors cursor_cli's auth.json handling):
        1. ``ANTIGRAVITY_OAUTH_TOKEN``       — raw token-file JSON content.
        2. ``ANTIGRAVITY_OAUTH_TOKEN_PATH``  — path to the token file.
        Optional ``ANTIGRAVITY_GOOGLE_ACCOUNTS`` writes google_accounts.json.
        Security: never log the content, only byte counts.
        """
        home = Path(os.path.expanduser("~"))
        token_file = home.joinpath(*_TOKEN_RELPATH)
        token_file.parent.mkdir(parents=True, exist_ok=True)

        content = os.environ.get("ANTIGRAVITY_OAUTH_TOKEN", "").strip()
        if not content:
            path = os.environ.get("ANTIGRAVITY_OAUTH_TOKEN_PATH", "").strip()
            if path and Path(path).expanduser().is_file():
                content = Path(path).expanduser().read_text(encoding="utf-8")
        if not content:
            raise RuntimeError(
                "antigravity_cli: no OAuth credential. Log in once on the host "
                "(`agy`) then set ANTIGRAVITY_OAUTH_TOKEN_PATH to "
                "~/.gemini/antigravity-cli/antigravity-oauth-token (or "
                "ANTIGRAVITY_OAUTH_TOKEN to its content)."
            )
        token_file.write_text(content, encoding="utf-8")
        token_file.chmod(0o600)
        logger.info("antigravity_cli: wrote OAuth token (%d B)", len(content))

        accounts = os.environ.get("ANTIGRAVITY_GOOGLE_ACCOUNTS", "").strip()
        if accounts:
            af = home.joinpath(*_ACCOUNTS_RELPATH)
            af.write_text(accounts, encoding="utf-8")
            logger.info("antigravity_cli: wrote google_accounts.json (%d B)", len(accounts))

    # =========================================================================
    # launch
    # =========================================================================

    async def launch(self, prompt: str) -> AgentRunResult:
        cfg: AntigravityCliConfig = self.config  # type: ignore[assignment]
        wd = Path(self.executor.work_dir)
        wd.mkdir(parents=True, exist_ok=True)

        prompt_file = wd / "prompt.txt"
        transcript_file = wd / "transcript.txt"
        stderr_log = wd / "stderr.log"
        pid_file = wd / "agy.pid"
        for f in (transcript_file, stderr_log, pid_file):
            if f.exists():
                try:
                    f.unlink()
                except OSError:
                    pass
        prompt_file.write_text(prompt, encoding="utf-8")

        argv = [self._agy_path, "-p", "-"]
        if cfg.model:
            argv += ["--model", cfg.model]
        if cfg.dangerously_skip_permissions:
            argv.append("--dangerously-skip-permissions")
        # agy file tools reject paths outside the workspace; add the task data
        # root (outside cwd) as an extra workspace dir.
        task_data_root = getattr(self.executor.sandbox, "task_data_root", "")
        if task_data_root:
            argv += ["--add-dir", task_data_root]

        env = os.environ.copy()
        for k, v in (self.executor.env or {}).items():
            env[k] = v
        env["NO_COLOR"] = "1"
        env["TERM"] = "dumb"
        logger.info("antigravity_cli: argv=%s", argv)

        t0 = time.monotonic()
        with open(prompt_file, "rb") as pin, \
             open(transcript_file, "wb") as tout, \
             open(stderr_log, "wb") as terr:
            proc = await asyncio.to_thread(
                subprocess.Popen, argv,
                stdin=pin, stdout=tout, stderr=terr, env=env, cwd=str(wd),
                start_new_session=True if hasattr(os, "setsid") else False,
            )
        pid_file.write_text(str(proc.pid), encoding="ascii")
        logger.info("antigravity_cli: spawned pid=%s", proc.pid)

        try:
            while proc.poll() is None:
                await asyncio.sleep(_POLL_INTERVAL_S)
        except asyncio.CancelledError:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=_TERM_GRACE_S)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            raise

        duration_s = time.monotonic() - t0
        exit_code = proc.returncode
        status = "completed" if exit_code == 0 else "failed"
        error: str | None = None
        if status == "failed":
            error = self._diagnose_failure(stderr_log, transcript_file, exit_code)
        return AgentRunResult(
            status=status, pid=proc.pid, exit_code=exit_code,
            transcript_path=str(transcript_file), stderr_path=str(stderr_log),
            duration_s=duration_s, error=error,
        )

    # =========================================================================
    # internals
    # =========================================================================

    @staticmethod
    def _join(*parts: str, is_linux: bool) -> str:
        sep = "/" if is_linux else "\\"
        head = parts[0].rstrip("/\\")
        tail = sep.join(p.strip("/\\") for p in parts[1:])
        return f"{head}{sep}{tail}" if tail else head

    def _diagnose_failure(self, stderr_log: Path, transcript: Path, exit_code: int | None) -> str:
        parts = [f"agent failed (rc={exit_code})"]
        st = _read_text_tolerant(stderr_log)
        tx = _read_text_tolerant(transcript)
        if st.strip():
            parts.append(f"stderr tail: ...{st[-800:]}")
        if tx.strip():
            parts.append(f"transcript tail: ...{tx[-800:]}")
        return " | ".join(parts)

    # =========================================================================
    # parse_artifacts
    # =========================================================================

    @classmethod
    def parse_artifacts(
        cls, *, work_dir: Path, config: AntigravityCliConfig,
        run_result: AgentRunResult, builder: TrajectoryBuilder,
    ) -> None:
        """agy has no machine-readable stream output, so the transcript is its
        captured stdout: a sequence of plain-text action narration lines ("I will
        …") followed by a final summary. Map the non-empty lines to a single
        agent step (the run's text), which is enough to score (scoring reads the
        task's output file, not the trajectory). Richer structured steps live in
        the conversations/*.db sqlite log, pulled separately for offline parsing.
        """
        transcript_file = work_dir / "transcript.txt"
        if not transcript_file.exists():
            builder.add_step(source="system",
                             message=f"antigravity-cli: no transcript at {transcript_file}",
                             extra={"reason": "no_transcript"})
            return
        raw = _strip_ansi(transcript_file.read_text(encoding="utf-8", errors="replace"))
        lines = [ln.rstrip() for ln in raw.splitlines() if ln.strip()]
        if lines:
            builder.add_step(source="agent", message="\n".join(lines))
        builder.trajectory.extra.setdefault("antigravity_cli", {}).update({
            "exit_code": run_result.exit_code,
            "transcript_path": str(transcript_file),
        })


_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


def _read_text_tolerant(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, OSError):
        return ""
