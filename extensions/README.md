# pi_team extension

Load with:

```bash
cd /path/to/piPy
uv run pipy --extension /path/to/piPy-teams/extensions/team_extension.py
```

Ensure `pi-team` is installed (via uv sync in the piPy-teams repo).

Use `uv run pipy` (or `uv run pi` from the piPy repo) — not the global TypeScript `pi` CLI.

## OMA harness integration

oma-platform resolves the extension path via:

| Variable | Default |
|----------|---------|
| `PIPY_TEAMS_EXTENSION` | `../piPy-teams/extensions/team_extension.py` (sibling of oma-platform) |

The host must configure `TeamRuntime` before the extension loads (see `oma_adapter/team_bridge.py`).

## Tests

```bash
cd /path/to/piPy-teams
uv sync
uv run pytest packages/pi_team/tests/ -v
```

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `OMA_DATABASE_PATH` | `./data/oma.db` | Shared oma.db for teams / agents |
| `DATABASE_PATH` | (fallback) | Alternate DB path env name |
| `PIPY_TEAMS_EXTENSION` | sibling repo path | Override extension file location |
| `TEAMMATE_POLL_INTERVAL_SEC` | `2.0` | Mailbox poll loop interval |
| `TEAMMATE_IDLE_TIMEOUT_SEC` | `600` | Poll loop idle shutdown |
