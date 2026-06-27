# Antigravity CLI Agent (`agy`)

Google's Antigravity CLI — the successor to Gemini CLI — run as a one-shot
process inside the sandbox:

```text
agy -p - --model <name> --dangerously-skip-permissions
  → CUA MCP Server (stdio, from ~/.gemini/config/mcp_config.json)
  → sandbox desktop (screenshot / click / type) + filesystem
```

It is a generalist CLI **and** GUI agent: it gets the shell/files natively from
the sandbox OS, and the desktop (screenshot, click, type…) through the CUA MCP
bridge — so it can do real computer-use tasks, not just terminal ones.

> **Google account login only.** Unlike every other ALE agent, `agy` is a closed
> native binary that authenticates **only** through Google OAuth against
> Google's own backend. There is **no OpenRouter, no API key, no service
> account.** You log in once with your own Google account (one that has
> Antigravity / Gemini access) and ALE reuses that session. Routing and the
> available models come from your Google plan, **not** OpenRouter — so token /
> cost are not comparable to the OpenRouter-routed agents.

---

## Quick start

Everything below is a **one-time setup on your own machine**. After it, runs are
fully headless.

### 1. Install `agy` on your host

```bash
curl -fsSL https://antigravity.google/cli/install.sh | bash
# installs to ~/.local/bin/agy
```

### 2. Log in with your Google account

Run `agy` in an interactive terminal on the host and follow the prompt:

```bash
~/.local/bin/agy
```

- It prints a **Google sign-in URL**.
- Open it in a browser (on **any** machine — this also works on a headless
  server: just copy the URL to your laptop's browser).
- Approve with a **Google account that has Antigravity access**.
- The `antigravity.google/oauth-callback` page shows an **authorization code** —
  paste it back into the terminal.

That writes your credential to:

```text
~/.gemini/antigravity-cli/antigravity-oauth-token
```

> Tip: use the plain `agy` command to log in (it waits for you). Avoid the
> `agy -p "…"` one-shot form for login — it only gives a ~30-second window to
> paste the code, too short for a browser round-trip.

### 3. Verify the login works headlessly

```bash
~/.local/bin/agy -p "Reply with exactly: PONG"
# → PONG     (no browser, reusing the saved token)
```

If you see `PONG`, the credential is good. It carries a refresh token, so it
keeps working across runs without logging in again.

### 4. Point ALE at the credential

Add the path to `secret/.env` (or export it in your shell):

```bash
export ANTIGRAVITY_OAUTH_TOKEN_PATH=$HOME/.gemini/antigravity-cli/antigravity-oauth-token
```

ALE forwards that file into the sandbox each run and `agy` silent-auths there —
you never log in inside the sandbox.

### 5. Run it

Reference the agent preset from an experiment and run as usual:

```yaml
# my_exp.yaml
secret_file: secret/.env
agents:      [configs/agents/antigravity_cli.yaml]
environment: configs/environments/docker.yaml      # or your GCE env
tasks:       selected_tasks/seecheck.txt
```

```bash
uv run python -m ale_run run my_exp.yaml
```

---

## Choosing a model

`--model` takes the display names from `agy models` verbatim. Set it in the
preset's `model:` field:

```
Gemini 3.1 Pro (High)        Gemini 3.5 Flash (High)
Claude Sonnet 4.6 (Thinking) Claude Opus 4.6 (Thinking)
GPT-OSS 120B (Medium)
```

Which models you can use — and how much — depends on your Google plan. **Quota
is per account AND per model**, so if one model is throttled another may still
work (e.g. Gemini exhausted but Claude Sonnet 4.6 fine).

## Config

```yaml
# configs/agents/antigravity_cli.yaml
harness: antigravity_cli
model: Claude Sonnet 4.6 (Thinking)
config:
  dangerously_skip_permissions: true   # required headless
  max_session_turns: -1                # unbounded (wall-clock is the cap)
  cli_version: "1.0.10"                # probe-or-reinstall
```

## How auth gets into the sandbox

1. **Host (once):** you log in → `~/.gemini/antigravity-cli/antigravity-oauth-token`.
2. **Per run:** ALE reads that file (via `ANTIGRAVITY_OAUTH_TOKEN_PATH`) and
   forwards its content into the sandbox; the deployer writes it back into place
   and `chmod 600`s it.
3. **In sandbox:** `agy` finds the token and silent-auths — no browser, no
   re-login. The token self-renews via its refresh token.

Treat the token file as a secret — it's a long-lived credential for your Google
account.

## Troubleshooting

- **Which account am I logged in as?** `cat ~/.gemini/google_accounts.json`
  (the `active` field). There is no agy CLI quota command — the web
  **Settings → Models** tab (signed in as that account) shows your plan + usage.
- **Runs 429 with `Individual quota reached … please upgrade your
  subscription`** → you're on a **free-tier** account (the "upgrade" wording is
  the tell), or that model's quota is spent. Either switch `model:` to one with
  quota left (e.g. `Claude Sonnet 4.6 (Thinking)`), or re-login with the right
  account: delete `~/.gemini/antigravity-cli/antigravity-oauth-token` and redo
  step 2.
- **Windows GUI tasks**: the CUA tools load reliably (the deployer warms up the
  node bridge + primes agy's first-run migration so they win agy's MCP
  tool-discovery race). No action needed.

## Notes

- The CUA GUI tools are declared in `agy`'s **native** `~/.gemini/config/mcp_config.json`
  (not gemini-cli's `settings.json`).
- `agy` has no machine-readable stream output, so the trajectory transcript is
  its captured stdout (`transcript.txt`). The full step-by-step log is a SQLite
  DB under `~/.gemini/antigravity-cli/conversations/`.

## Smoke test

```bash
uv run python -m ale_run run exp_antigravity_seecheck.yaml
```

`demo/seecheck` (a vision smoke test: read a code off the desktop) is the
quickest end-to-end check that auth + the GUI bridge both work.
