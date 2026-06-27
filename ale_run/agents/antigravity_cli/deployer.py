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

GUI comes from the cua MCP bridge declared in ``agy``'s native
``~/.gemini/config/mcp_config.json`` (NOT the gemini-cli ``settings.json``).
``agy`` has no ``--output-format``, so the transcript is its captured stdout;
the richer step log is a sqlite ``.db`` under
``~/.gemini/antigravity-cli/conversations/`` (outside ``work_dir``) — a follow-up
can parse it for structured tool-call steps.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import time
from pathlib import Path
from typing import ClassVar

from ale_run.base_interface import (
    AgentRunResult,
    BaseAgentDeployer,
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
        # stdin=DEVNULL: a bare `agy --version` can otherwise wait on a TTY /
        # trip Defender on Windows.
        probe = subprocess.run(
            [agy_path, "--version"], capture_output=True, text=True, timeout=30,
            stdin=subprocess.DEVNULL,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    m = _VERSION_RE.search((probe.stdout or "") + (probe.stderr or ""))
    return m.group(1) if m else None


def _win_appdata_bin(home: str) -> str:
    """``%LOCALAPPDATA%\\agy\\bin`` — where install.ps1 drops ``agy.exe``."""
    local_appdata = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
    return os.path.join(local_appdata, "agy", "bin")


def _find_agy(home: str, *, is_windows: bool) -> str | None:
    """Resolve the agy binary, preferring the installer's drop location.

    The sandbox entry runs without a login shell, so the install dir may not be
    on PATH and ``shutil.which`` misses the installer-dropped binary. Linux:
    ``~/.local/bin/agy``; Windows: ``%LOCALAPPDATA%\\agy\\bin\\agy.exe``."""
    p = shutil.which("agy.exe" if is_windows else "agy") or shutil.which("agy")
    if p:
        return p
    cand = (os.path.join(_win_appdata_bin(home), "agy.exe") if is_windows
            else os.path.join(home, ".local", "bin", "agy"))
    return cand if os.path.isfile(cand) else None


class AntigravityCliDeployer(BaseAgentDeployer):
    """Stdlib-only deployer for the Google ``agy`` CLI."""

    default_executor: ClassVar[str] = "sandbox"
    supported_executors: ClassVar[frozenset[str]] = frozenset({"sandbox"})
    hot_artifacts: ClassVar[tuple[str, ...]] = ("transcript.txt", "stderr.log", "agy_cli.log")

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
        self._is_windows = not sandbox.is_linux

        home = os.path.expanduser("~")

        # 1. locate / install agy. Probe first, then install when missing or
        #    version-stale. NOTE: the official installer refuses (no-op) if agy
        #    already exists, so a version bump only takes effect when
        #    `download_url` (a pinned tarball, Linux-only) is set — `_install_agy`
        #    removes the existing binary first either way.
        agy = _find_agy(home, is_windows=self._is_windows)
        installed = await asyncio.to_thread(_installed_version, agy) if agy else None
        stale = bool(agy and cfg.cli_version and installed and installed != cfg.cli_version)
        if not agy or (stale and cfg.download_url and not self._is_windows):
            if stale:
                logger.info("antigravity_cli: %s != pinned %s — reinstalling",
                            installed, cfg.cli_version)
            await self._install_agy(cfg, home)
            agy = _find_agy(home, is_windows=self._is_windows)
            if not agy:
                raise RuntimeError("antigravity_cli: 'agy' not found after install")
            installed = await asyncio.to_thread(_installed_version, agy)
        elif stale:
            # Version drift but no pinned tarball to enforce it: the installer
            # would just re-fetch latest, so reuse what's installed.
            logger.warning("antigravity_cli: installed %s != pinned %s but no "
                           "download_url to pin — reusing installed agy",
                           installed, cfg.cli_version)
        self._agy_path = agy
        # Put the install dir on PATH so launch() and any self-update find it.
        bin_dir = (_win_appdata_bin(home) if self._is_windows
                   else os.path.join(home, ".local", "bin"))
        if bin_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
        logger.info("antigravity_cli: CLI ok — agy %s at %s", installed or "?", agy)

        # 2. clean work dir
        wd = Path(self.executor.work_dir)
        wd.mkdir(parents=True, exist_ok=True)

        # 3. inject the OAuth credential the operator produced on the host.
        self._write_oauth_token()

        # 4. cua GUI bridge + agy config. Idempotent bridge install.
        from ale_run.agents._bootstrap import cua_bridge_env, ensure_cua_mcp_server
        await ensure_cua_mcp_server(sandbox)

        gemini_home = Path(home) / ".gemini"
        gemini_home.mkdir(parents=True, exist_ok=True)
        self._gemini_dir = str(gemini_home)
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

        # 5. Windows: pre-warm node + the cua bridge modules. A COLD node start
        #    on Windows (Defender scan + ESM module load of the MCP SDK) is slow
        #    enough to intermittently miss agy's MCP tool-discovery window at
        #    launch, so the cua GUI tools register only ~1 run in 4. One warm-up
        #    run loads the modules into the OS file cache and lets Defender scan
        #    them once, so agy's spawn of the bridge at launch is fast and wins
        #    the race. (Linux node start is fast; no warm-up needed there.)
        if self._is_windows:
            self._ensure_grep_windows()
            await self._prewarm_bridge(sandbox)
            await self._prewarm_agy()

    def _ensure_grep_windows(self) -> None:
        """Put ``grep`` on PATH for agy's ``grep_search`` tool.

        agy shells out to ``grep``, which isn't on the Windows sandbox PATH by
        default — so ``grep_search`` fails with ``exec: 'grep': ... not found``.
        Git for Windows (baked into ale-win10) already ships a real GNU grep at
        ``…\\Git\\usr\\bin\\grep.exe`` (with its DLLs co-located); it's just not
        on PATH. Prepend that dir. As a fallback for an image WITHOUT Git, fetch
        a single-file busybox-w32 and run it as ``grep.exe``. Best-effort: a
        failure only loses ``grep_search``, not the run.
        """
        if shutil.which("grep"):
            return
        home = os.path.expanduser("~")
        for d in (
            r"C:\Program Files\Git\usr\bin",
            r"C:\Program Files (x86)\Git\usr\bin",
            os.path.join(home, "AppData", "Local", "Programs", "Git", "usr", "bin"),
        ):
            if os.path.isfile(os.path.join(d, "grep.exe")):
                self._prepend_path(d)
                logger.info("antigravity_cli: grep via Git for Windows (%s on PATH)", d)
                return
        # No Git grep — fetch busybox-w32 (single exe; run as grep.exe → grep applet).
        bin_dir = _win_appdata_bin(home)
        try:
            import urllib.request
            os.makedirs(bin_dir, exist_ok=True)
            grep_exe = os.path.join(bin_dir, "grep.exe")
            urllib.request.urlretrieve(
                "https://frippery.org/files/busybox/busybox.exe", grep_exe)
            self._prepend_path(bin_dir)
            logger.info("antigravity_cli: installed busybox grep at %s", grep_exe)
        except Exception as e:  # noqa: BLE001 — best-effort, non-fatal
            logger.warning("antigravity_cli: could not provision grep (grep_search "
                           "will be unavailable on Windows): %s", e)

    @staticmethod
    def _prepend_path(directory: str) -> None:
        if directory not in os.environ.get("PATH", ""):
            os.environ["PATH"] = directory + os.pathsep + os.environ.get("PATH", "")

    async def _prewarm_agy(self) -> None:
        """Run ``agy models`` once so the FIRST-run side effects (config
        migration, the background auto-updater) are done before the real launch.
        On a fresh Windows VM those first-run steps otherwise race with MCP tool
        discovery, so the cua tools register only intermittently; priming makes
        the real launch a reliable 'subsequent' run.

        Uses ``models`` (a metadata call), NOT a ``-p`` generation turn, so it
        consumes **no model quota** — a per-task generation warm-up would double
        quota usage across a benchmark and exhaust the account.
        """
        argv = [self._agy_path, "models", f"--gemini_dir={self._gemini_dir}"]
        try:
            await asyncio.to_thread(
                subprocess.run, argv, stdin=subprocess.DEVNULL,
                capture_output=True, timeout=60, env=os.environ.copy(),
            )
            logger.info("antigravity_cli: warmed up agy (first-run migration primed, no quota used)")
        except subprocess.TimeoutExpired:
            logger.info("antigravity_cli: agy warm-up timed out (continuing)")
        except (OSError, subprocess.SubprocessError) as e:
            logger.info("antigravity_cli: agy warm-up skipped: %s", e)

    async def _prewarm_bridge(self, sandbox) -> None:
        """Spawn the cua bridge once so node + its modules are warm/cached."""
        from ale_run.agents._bootstrap import cua_bridge_env
        index_js = self._join(sandbox.mcp_server_dir, "src", "index.js",
                              is_linux=sandbox.is_linux)
        env = {**os.environ, **cua_bridge_env(self.executor)}
        try:
            # stdin=DEVNULL → the stdio MCP server gets EOF and idles/exits once
            # its modules are loaded; the timeout caps the (slow, one-time) cold
            # start. We only care that the modules end up cached, not the output.
            await asyncio.to_thread(
                subprocess.run, [sandbox.node, index_js],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=45, env=env,
            )
        except subprocess.TimeoutExpired:
            pass
        except (OSError, subprocess.SubprocessError) as e:
            logger.info("antigravity_cli: bridge pre-warm skipped: %s", e)
            return
        logger.info("antigravity_cli: pre-warmed cua bridge (node modules cached)")

    async def _install_agy(self, cfg: AntigravityCliConfig, home: str) -> None:
        """Install agy via the official installer (Linux: curl, Windows: ps1) or
        a pinned tarball URL (Linux only).

        Removes any existing binary first: both installers are a no-op when the
        binary already exists, so without this a reinstall would silently keep
        the old version.
        """
        env = {**os.environ}
        if self._is_windows:
            target = os.path.join(_win_appdata_bin(home), "agy.exe")
            ps = (
                f"$ErrorActionPreference='Stop'; "
                f"if (Test-Path '{target}') {{ Remove-Item '{target}' -Force }}; "
                "irm https://antigravity.google/cli/install.ps1 | iex"
            )
            argv = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps]
        else:
            bin_dir = os.path.join(home, ".local", "bin")
            if cfg.download_url:
                # Pinned tarball: extract the `agy` binary into ~/.local/bin.
                os.makedirs(bin_dir, exist_ok=True)
                cmd = (
                    f"set -e; rm -f {bin_dir}/agy; tmp=$(mktemp -d); "
                    f"curl -fsSL {shlex.quote(cfg.download_url)} -o $tmp/agy.tgz; "
                    f"tar -xzf $tmp/agy.tgz -C $tmp; "
                    f"f=$(find $tmp -name agy -type f | head -1); "
                    f"install -m755 $f {bin_dir}/agy; rm -rf $tmp"
                )
            else:
                cmd = (
                    f"rm -f {bin_dir}/agy; "
                    "curl -fsSL https://antigravity.google/cli/install.sh | bash"
                )
            argv = ["bash", "-lc", cmd]
        proc = await asyncio.to_thread(
            subprocess.run, argv,
            capture_output=True, text=True, timeout=300, env=env,
            stdin=subprocess.DEVNULL,
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
        # Pin the gemini dir to an ABSOLUTE path: agy resolves a relative
        # ".gemini" against CWD on Windows and falls back to a default, which
        # makes config discovery (incl. the cua MCP server) non-deterministic.
        gemini_dir = getattr(self, "_gemini_dir", "")
        if gemini_dir:
            argv.append(f"--gemini_dir={gemini_dir}")
        if cfg.model:
            argv += ["--model", cfg.model]
        # Raise agy's print-mode timeout well above the wall budget — its 5m
        # default silently truncates longer tasks (no output written).
        if getattr(cfg, "print_timeout", ""):
            argv.append(f"--print-timeout={cfg.print_timeout}")
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
        # The OAuth credential reaches agy via the file written in install(), NOT
        # the env. Strip the transport vars so the long-lived refresh token never
        # enters agy's process env (and thus any shell command the agent runs).
        for cred_var in ("ANTIGRAVITY_OAUTH_TOKEN", "ANTIGRAVITY_GOOGLE_ACCOUNTS"):
            env.pop(cred_var, None)
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

        # Capture agy's own internal log (MCP connection / auth / quota) into the
        # work dir so it's pulled as an artifact — invaluable for debugging (e.g.
        # why cua MCP tools did/didn't load). Best-effort; cli.log is a symlink to
        # the latest log/cli-*.log, copyfile follows it.
        try:
            agy_log = Path(os.path.expanduser("~")) / ".gemini" / "antigravity-cli" / "cli.log"
            if agy_log.exists():
                shutil.copyfile(agy_log, wd / "agy_cli.log")
        except OSError:
            pass

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
