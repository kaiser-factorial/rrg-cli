# CLI Agent Validator Reference

Extracted commands for all supported RRG dispatch validators.

## Summary Table

| Agent      | Non-interactive cmd              | Model flag      | Resume/continue                    | Session ID source        | Model provenance           |
|------------|---------------------------------|-----------------|-------------------------------------|--------------------------|---------------------------|
| hermes     | `hermes -z "prompt"`            | `-m slug`       | `--resume <session_id>`             | `hermes sessions list`   | `hermes status`           |
| claude     | `claude -p "prompt"`            | `--model alias` | `--resume <session_id>` or `-c`    | `--output-format json`   | config / json output       |
| codex      | `codex exec "prompt"`           | `-m model`      | `codex exec resume <id> "next"`     | `--json` output          | `~/.codex/config.toml`    |
| grok       | `grok -p "prompt" --single`     | `-m model`      | `--continue` / `--resume <id>`      | `grok sessions list`     | `~/.grok/models_cache.json`|
| pool       | `pool exec -p "prompt"`        | `--agent-name`  | `--continue <run_id>`               | `-o json` output         | `pool config`              |
| antigravity| (TUI only — no CLI mode)        | `/model` (TUI)  | `/resume` (TUI)                     | N/A                      | N/A                       |
| openrouter | (direct API via httpx)          | slug in payload | message accumulation                 | N/A                      | slug in payload            |

## Detailed Commands

### Hermes (Nous Research)
- **One-shot**: `hermes -z "prompt" -m model_slug --provider openrouter`
- **Without model** (uses configured default): `hermes -z "prompt"` — uses the model from `hermes status`
- **Resume**: `hermes -z "next prompt" --resume <session_id>`
- **Session ID**: parse `hermes sessions list` (first non-header row, last column)
- **Current model**: `hermes status` → "Model:" field
- **Config file**: `~/.hermes/config.yaml`
- **Notes**: Model is optional — if omitted, uses the configured default (currently qwen/qwen3.7-max).
  `--pass-session-id` puts the ID in the system prompt, not stdout.

### Claude Code (Anthropic)
- **One-shot**: `claude -p "prompt" --print --output-format json --dangerously-skip-permissions`
- **Without model**: uses the account's default model (sonnet-5 or configured)
- **Resume by ID**: `claude -p "next" --resume <session_id> --output-format json`
- **Continue last**: `claude -p "next" -c --output-format json`
- **Session ID**: parse `--output-format json` output → `session_id` field
- **Model**: `--model <alias>` (e.g., claude-sonnet-5, claude-opus-5)
- **Config**: `claude config list` (not available — model is per-session)

### Codex (OpenAI)
- **One-shot**: `codex exec "prompt" --json`
- **Without model**: uses `~/.codex/config.toml` default (currently gpt-5.6-terra)
- **Resume**: `codex exec resume <session_id> "next" --json`
- **Session ID**: parse `--json` JSONL output → `session_id` field
- **Model**: `-m <model>` (e.g., gpt-5.6-terra, o3)
- **Config file**: `~/.codex/config.toml`
- **Notes**: `approval_policy = "never"` in config bypasses approvals. Requires trusted dir.

### Grok Build (xAI)
- **One-shot**: `grok -p "prompt" --single`
- **Without model**: uses grok-4.5 (from `~/.grok/models_cache.json`)
- **Continue last**: `grok -p "next" --single -c` (continues most recent in cwd)
- **Resume by ID**: `grok -p "next" --single --resume <id>`
- **Session ID**: `grok sessions list`
- **Model**: `-m <model>` (e.g., grok-4.5)
- **Config**: `~/.grok/config.toml`, `~/.grok/models_cache.json`
- **Permission**: `permission_mode = "always-approve"` in config

### Poolside (Pool)
- **One-shot**: `pool exec -p "prompt" --unsafe-auto-allow -d <workdir>`
- **Without model**: uses poolside's default agent
- **Continue**: `pool exec -p "next" --continue <run_id>` (or `--continue` alone for last)
- **Session ID**: `--output json` (NLJSON with run ID)
- **Model**: `--agent-name <name>` (tenant mode)
- **Config**: `~/.config/poolside/settings.yaml`
- **Notes**: Requires Docker sandbox by default (use `--sandbox disabled` to skip).
  May fail without Docker daemon running.

### Antigravity (Google)
- **Status**: TUI-only — no documented non-interactive/print/exec mode
- **Model selection**: `/model` slash command inside TUI
- **Resume**: `/resume` slash command inside TUI
- **Notes**: Cannot be used as an RRG validator until a non-interactive mode is available.
  Listed here for reference only.

### OpenRouter (direct API)
- **Call**: `POST https://openrouter.ai/api/v1/chat/completions` with `Authorization: Bearer $OPENROUTER_API_KEY`
- **Model**: slug in the JSON payload (e.g., `qwen/qwen3.7-max`)
- **Multi-turn**: accumulate messages array across turns
- **No session**: conversation state is in the messages array only

## Normalized Interface

All validators expose the same RRG dispatch interface:
1. `send_turn(prompt, session_id=None) -> (response, session_id, model)`
2. First call with `session_id=None` creates a new session
3. Subsequent calls with the returned `session_id` continue the conversation
4. Each call returns the response text, session ID (for resume), and model slug (for provenance)

## Default Models (current machine)

| Agent    | Default model         | Source                    |
|----------|----------------------|---------------------------|
| hermes   | qwen/qwen3.7-max      | hermes status             |
| codex    | gpt-5.6-terra        | ~/.codex/config.toml      |
| grok     | grok-4.5             | ~/.grok/models_cache.json |
| claude   | (account default)    | per-session               |
| pool     | (poolside default)    | poolside server config    |
