# Antigravity CLI Integration Notes

## Source

- Binary: `agy` — Google's Antigravity CLI (successor to Gemini CLI), a closed
  native Go binary. **No fork** (it cannot be patched like the JS gemini-cli).
- Install: official installer `https://antigravity.google/cli/install.sh` drops
  `~/.local/bin/agy`. Pinnable tarball via the updater manifest
  (`.../manifests/linux_amd64.json` → `storage.googleapis.com/antigravity-public/...`).
- Auth: **Google OAuth only** — no OpenRouter, no API key, no service account.
  See README.md for the host-login → token-file → in-sandbox-injection flow.

## Install

`AntigravityCliDeployer.install()` probes `agy --version` and (re)installs via
the official installer when missing or version-mismatched, then writes the
OAuth credential, the CUA MCP config, and `settings.json`. OS-branched: Linux
uses the curl installer → `~/.local/bin/agy`; Windows uses `install.ps1` →
`%LOCALAPPDATA%\agy\bin\agy.exe` (see Windows section for the cua caveat).

## Runtime

The deployer launches:

```bash
agy -p - --model "<display name>" --dangerously-skip-permissions --add-dir <task_data_root>
```

- `--model` takes the `agy models` display names verbatim (e.g.
  `Gemini 3.1 Pro (High)`, `Claude Sonnet 4.6 (Thinking)`, `GPT-OSS 120B (Medium)`).
- `agy` has **no `--output-format`**, so the transcript is its captured stdout
  (`transcript.txt`); the structured step log is a SQLite DB under
  `~/.gemini/antigravity-cli/conversations/`.
- Auth at launch is **silent**: `agy` reads the injected
  `~/.gemini/antigravity-cli/antigravity-oauth-token` and refreshes it itself.

## Tool Surface

`agy` exposes a rich native toolset **plus** the CUA MCP tools. Unlike
gemini-cli, the CUA bridge must be declared in `agy`'s **native**
`~/.gemini/config/mcp_config.json` (NOT `settings.json`), or no GUI tools load.

The matrix below is the agent's own self-report from `demo/tool_smoke` on
`ale-ubuntu22` (Gemini 3.1 Pro): **36 tools identified, 33 passed, 0 failed,
3 untested**.

### Native `agy` tools (19 — all exercised, all passed)

| Tool | Classification | Notes |
|---|---|---|
| `run_command` | supported | VM shell execution. |
| `view_file`, `write_to_file` | supported | VM filesystem read/write. |
| `replace_file_content`, `multi_replace_file_content` | supported | In-place edits. |
| `list_dir`, `grep_search` | supported | File discovery / content search. |
| `search_web`, `read_url_content` | supported | Web access (internet is allowed). |
| `generate_image` | supported | Image generation. |
| `call_mcp_tool`, `list_resources`, `list_permissions` | supported | MCP meta / introspection. |
| `define_subagent`, `invoke_subagent`, `manage_subagents` | supported | Sub-agent orchestration. |
| `manage_task`, `schedule` | supported | Task list / scheduled work. |
| `send_message` | supported | Agent message channel. |

### CUA MCP GUI tools (14 — all exercised, all passed)

| Tool | Notes |
|---|---|
| `screenshot` | Desktop capture — the GUI→model image path (proven by `demo/seecheck`). |
| `click`, `mouse_move`, `mouse_down`, `mouse_up`, `drag` | Pointer actions. |
| `key`, `key_down`, `key_up`, `hold_key`, `type` | Keyboard actions. |
| `scroll`, `wait`, `cursor_position` | Scroll / pause / pointer query. |

> The CUA action tools require real arguments (e.g. `mouse_move` needs a
> `coordinate`). During the smoke test `agy`'s first degenerate probe calls
> returned `MCP -32602 Invalid arguments`; it then retried with proper args and
> all passed — so the errors are agent-side, not a bridge incompatibility.

### Untested (3)

| Tool | Reason |
|---|---|
| `ask_permission`, `ask_question` | Interactive — block headless; `agy` self-skips them. |
| `read_resource` | No MCP resources are exposed on the `cua` server. |

### Tool disabling

`config.disabled_tools` is written to `settings.json` `tools.exclude`, but those
are **gemini-cli** tool names (`save_memory`, `ask_user`, …) and do not match
`agy`'s native names — so the exclude list is effectively inert for `agy`, which
exposes its full native set. `agy` self-skips the interactive tools
(`ask_permission` / `ask_question`). Aligning the exclude list to `agy`'s real
tool names (and confirming `agy` honors `settings.json`) is a follow-up if we
want to disable e.g. `schedule` / `manage_task` / subagents for benchmark
integrity.

## Validation (OS × provider)

| Task | Linux / docker | Linux / gcloud | Windows / gcloud |
|---|---|---|---|
| `demo/seecheck` (GUI vision) | **1.0** | **1.0** | — (cua, see below) |
| `demo/tool_smoke` | **0.92** (33/36) | **0.92** (33/36) | n/a |
| `demo/tool_smoke_win` | n/a | n/a | **0.48–0.84** (native only) |

gcloud uses the operator's **active gcloud account** (compute access) when
`GCP_SA_KEY` is unset/missing — `gcloud_sa_key_path()` returns None and the
provider falls back to it. `output_path: local` needs no GCS key.

## Windows

The deployer supports Windows: it installs `agy.exe` via `install.ps1` into
`%LOCALAPPDATA%\agy\bin`, writes the OAuth token + MCP config under
`%USERPROFILE%\.gemini` (the Linux-generated token authenticates fine on
Windows), and launches `agy.exe -p -`. **agy's own native tools work**
(`run_command`, file tools, web, etc.) — except `grep_search`, which shells out
to `grep` (absent on Windows; agy's own limitation).

**Known limitation — cua GUI tools do not load on Windows.** Verified on a live
VM that everything the deployer controls is correct: `mcp_config.json` (cua +
the right `node.exe`/`index.js` paths), `node.exe`, the bridge `index.js`, and
its `node_modules` are all present. Yet agy's log shows **no MCP-server startup**
on Windows (it logs the cua connection on Linux), and the model gets
`unknown tool name: call_mcp_tool` / `mcp_cua_cursor_position` — i.e. agy does
not surface MCP (cua) tools to the model on Windows the way it does on Linux.
This is an agy-internal Windows behavior, not a wiring issue, and blocks GUI
tasks (incl. `demo/seecheck`) on Windows until agy fixes MCP exposure there.
(The deployer copies agy's `cli.log` → `work_dir/agy_cli.log`, pulled as a hot
artifact, to make this diagnosable.)

## Quota

Auth/routing is the operator's Google plan, not OpenRouter. The **free tier has
a limited rolling quota**: a normal task or a single ~36-tool smoke run
completes, but back-to-back heavy runs can exhaust it
(`RESOURCE_EXHAUSTED (429): Individual quota reached`, multi-day reset). Light
calls keep working while the heavy budget is depleted.
