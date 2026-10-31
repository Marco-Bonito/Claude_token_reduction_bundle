## Routing (paste this section into your CLAUDE.md)

- Multi-step work: run `/orchestrate <request>`. It plans, routes and tracks tasks in `.claude/runs/`.
- Model and effort per task come from `.claude/routing/routing-table.json` (created on first use) through the `route.py` script of the token-routing plugin. Never pick them by intuition.
- Every Agent call to `worker`, `reviewer` or `improver` passes `model` and `effort`.
- Wide code search: use the `Explore` subagent, not Read in the main thread.
- Git and GitHub: use the `gh` CLI, not an MCP server.
- Do not set `CLAUDE_CODE_EFFORT_LEVEL` or `CLAUDE_CODE_SUBAGENT_MODEL`. They override the per-call values and break routing.

# Compact instructions
Keep: the run folder path, the current phase, the IDs of running and blocked tasks. Drop: worker output and file contents. The state lives in tasks.json.
