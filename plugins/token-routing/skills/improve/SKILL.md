---
name: improve
description: Run the improvement cycle of the routing system - collect metrics, compute table proposals, apply the safe ones, and let the improver agent update lessons and propose prompt changes. Use /improve, or from /orchestrate at the end of a run.
argument-hint: "[run_dir]"
---

# Improve the routing foundation

Scripts folder: `${CLAUDE_SKILL_DIR}/../../routing`. In every command below, `route.py`, `route_map.py` and `metrics.py` mean `python3 "${CLAUDE_SKILL_DIR}/../../routing/<script>"`. Write the full path in each command, because each shell call starts fresh. On Windows without `python3`, use `python` or `py`.
Project data (table, lessons, history) is in `<project>/.claude/routing/`. The scripts create it on first use.
Names: in a plugin install, agents and skills can have the prefix `token-routing:` (for example `token-routing:worker`). Use the name that is in your agent and skill list.

1. If a run folder is given ($ARGUMENTS), run `metrics.py collect <run_dir>`. If no folder is given, collect every folder in `.claude/runs/` that has finished tasks. Collect skips duplicates.
2. Run `metrics.py report`.
3. Run `metrics.py apply --dry-run` and read the planned changes.
4. Call the `improver` subagent. Get its model and effort from the `improver.route` field in `routing-table.json`. Prompt: "Run the improvement cycle. Report: .claude/routing/history/report.md".
5. When the improver returns, run `metrics.py apply`. It skips the proposals that the improver vetoed.
6. Tell the user, in max 5 lines:
   - the table changes (old route → new route),
   - the lessons added,
   - the proposals waiting for approval in `history/improver-proposals.md`,
   - the top finding.
7. If proposals are waiting, ask the user which ones to apply. Apply only the approved ones, then log them in `CHANGELOG.md`.

Undo a table change with `metrics.py rollback`. List the versions with `metrics.py versions`.
