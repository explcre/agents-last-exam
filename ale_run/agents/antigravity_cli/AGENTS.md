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
the official curl installer when missing or version-mismatched, then writes the
OAuth credential, the CUA MCP config, and `settings.json`. Linux only so far
(curl installer / `~/.local/bin` / `bash`); native-Windows is a follow-up.

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

## Quota

Auth/routing is the operator's Google plan, not OpenRouter. The **free tier has
a limited rolling quota**: a normal task or a single ~36-tool smoke run
completes, but back-to-back heavy runs can exhaust it
(`RESOURCE_EXHAUSTED (429): Individual quota reached`, multi-day reset). Light
calls keep working while the heavy budget is depleted.
