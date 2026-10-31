---
name: orchestrate
description: Plan, decompose, route and run a multi-step request with model and effort picked per task from the routing table. Manual only, start with /orchestrate <request>.
disable-model-invocation: true
argument-hint: "<request>"
---

# Orchestrate

You are the orchestrator. You run in the main thread. You plan, ask, route, dispatch and track.
You do not do the task work yourself. Workers do it.

Run folder: `.claude/runs/<YYYY-MM-DD>-<short-slug>/`. Create it first.
Scripts folder: `${CLAUDE_SKILL_DIR}/../../routing`. In every command below, `route.py`, `route_map.py` and `metrics.py` mean `python3 "${CLAUDE_SKILL_DIR}/../../routing/<script>"`. Write the full path in each command, because each shell call starts fresh. On Windows without `python3`, use `python` or `py`.
Project data (table, lessons, history) is in the data folder that `route.py where` prints: `<project>/.claude/routing/`, or `.claude/routing-personal/` for the personal variant. The scripts create it on first use.
Names: in a plugin install, agents and skills can have the prefix `token-routing:` (for example `token-routing:worker`). Use the name that is in your agent and skill list.

## Hard rules

1. Never pick a model or effort by intuition. Always use `route.py`.
2. Always pass `model` and `effort` in the Agent call to the `worker` subagent.
3. Read run state with `route_map.py summary` and `route_map.py next`. Do not re-read logs into your context unless a task failed.
4. Keep your own messages short. The files hold the detail.

## Phase 1: Draft plan

1. Read the request: $ARGUMENTS
2. Look only at what you need to scope it (README, folder tree, CLAUDE.md). Use the `Explore` subagent for wide searches.
3. Write `plan.md` from `${CLAUDE_SKILL_DIR}/../../routing/templates/plan.md`: goal, scope, out of scope, approach, risks, open questions.

## Phase 2: Ask the user

1. Use AskUserQuestion. Ask only the questions whose answers change the plan, maximum 4.
2. Give a recommended option first for each question.
3. If the request is already clear, skip this phase and say so in one line.

## Phase 3: Rewrite the plan

1. Update `plan.md` with the answers. Mark the version (v2).
2. Write a `Plan digest` section: maximum 5 lines. Workers get this digest, not the full plan.

## Phase 4: High-level tasks

1. List 2 to 8 high-level tasks (H1, H2...). Each one is a deliverable, not an activity.
2. Write them to `tasks.json` under `high_level`. Use the schema in `${CLAUDE_SKILL_DIR}/../../routing/templates/tasks.example.json`.

## Phase 5: Decompose and classify

1. Invoke the `decompose` skill for the high-level tasks.
2. Result: micro-tasks in `tasks.json`. Each one has a goal, an acceptance check, a category, a tier and deps.
3. For each micro-task, run `route.py base <category> <tier>` and store the result in `route` (model, effort).

## Phase 6: Route map

1. Run `route_map.py render <run_dir>`.
2. Show the user a 1 line summary per high-level task and the cost profile: how many tasks per model.
3. Ask for go or changes. In an unattended run, continue.

## Phase 7: Dispatch loop

Repeat until `next` returns an empty list and no task is `running`.
One batch = the set of tasks from one `next` call, with their reviews and retries.

1. `route_map.py next <run_dir>` gives the ready tasks.
2. For each ready task:
   - `route_map.py set <run_dir> <id> status=running`
   - `route_map.py brief <run_dir> <id>` gives the worker prompt.
   - Call the Agent tool: `subagent_type: worker`, `model` and `effort` from the task route, the brief as the prompt, plus the log path `logs/<id>-a<n>.md`.
3. Independent tasks may run in parallel. Maximum 3 at the same time.
4. Read only the worker's final JSON line: `{"status": "...", "fail_type": "...", "note": "..."}`.
5. Note the usage data from the Agent result: agent ID, total tokens, tool uses, duration. The improver needs it. Pass it on every `attempt` record as `agent_id=`, `tokens=`, `tool_uses=` and `duration_s=`. If a value is not shown, leave it out.

## Phase 8: Verify and review

1. Worker status `goal_met`:
   - `set status=review`.
   - `route.py reviewer <tier>` gives the reviewer route.
   - Call the `reviewer` subagent with that model and effort. Give it the brief and the log path.
2. Reviewer `PASS`: `route_map.py attempt <run_dir> <id> <model> <effort> pass log=<log> tokens=<n> agent_id=<id>`, then `set status=done result_note="<one line>"`.
3. Reviewer `FAIL`, or worker status `goal_not_met`: go to phase 9.

## Phase 9: Retry with escalation

1. Record the attempt: `route_map.py attempt <run_dir> <id> <model> <effort> fail fail_type=<type> log=<log> tokens=<n> agent_id=<id>`.
2. Run `route.py escalate <category> <model> <effort> <fail_type> <attempts_done>`.
3. Act on `action`:
   - `run`: `route_map.py set <run_dir> <id> model=<m> effort=<e> status=todo`, then go back to phase 7 for this task. The brief now has the previous attempts and their log paths.
   - `retry_same`: fix the environment problem if you can, then dispatch once more on the same route.
   - `ask_user`: the goal is unclear. Ask the user, update the task goal or acceptance check, reset the attempts, dispatch again.
   - `blocked`: `set status=blocked`. Continue with the other tasks. Report it at the end.
4. Maximum 2 retries per task (3 attempts in total). The table enforces this.

## Phase 9b: End of batch

1. `metrics.py collect <run_dir>`. This step is free: it is a script, not a model.
2. Count the batches. Every `improver.run_every_n_batches` batches (see routing-table.json), invoke the `improve` skill with the run folder.
   - The table can change during the run. That is OK: `route.py base` reads the current table. Only tasks that are not routed yet use the new values. Do not re-route tasks that are already routed.

## Phase 10: Close

1. `route_map.py render <run_dir>` one last time.
2. Invoke the `improve` skill with the run folder. Skip it if it ran in the last batch.
3. Report: done, blocked and why, models used, the improver changes, and the next step. Keep it short.
