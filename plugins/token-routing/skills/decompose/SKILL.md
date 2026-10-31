---
name: decompose
description: Break a request or high-level tasks into micro-tasks, each with a goal, acceptance check, category, complexity tier (1-5) and dependencies, as a table and tasks.json. Use from /orchestrate or alone with /decompose. Not for single small edits.
argument-hint: "[run_dir | task description]"
---

# Decompose into micro-tasks

## Modes

- **Orchestrate mode.** $ARGUMENTS is a run folder that has `tasks.json` with `high_level`. Read `high_level` and `plan.md`. Write the `tasks` array into the same `tasks.json`.
- **Standalone mode.** $ARGUMENTS is a task description, or nothing (then use the current request).
  1. Make 2 to 8 high-level tasks (H1, H2...). Each one is a deliverable, not an activity.
  2. Decompose them as described below.
  3. If the routing scripts exist (`${CLAUDE_SKILL_DIR}/../../routing/route.py`), create `.claude/runs/<YYYY-MM-DD>-<slug>/tasks.json` and run `python3 "${CLAUDE_SKILL_DIR}/../../routing/route.py" base <category> <tier>` for each task to fill `route`.
  4. If it does not exist, show the result as a table in the reply only.

Look only at the code you need to size the tasks. Use Grep and the folder tree, not full file reads.

## Step 1: Write the micro-tasks

For each high-level task, write micro-tasks T1, T2... with `parent` set to the high-level ID. Every micro-task has these fields:

| Field | Rule |
|---|---|
| `title` | Max 6 words, verb first: "Add refresh timer". |
| `goal` | One sentence. The state that is true when the task is done, not the activity. Good: "AuthRepository refreshes the session 60 s before expiry." Bad: "Work on refresh." |
| `acceptance` | A check that a different agent can do without guessing. Prefer a command. If there is no command, write 1 to 3 checkable criteria. |
| `files` | The files the task will touch, if you know them. |
| `deps` | The task IDs that must be done first. |
| `category` | One value from the category table. |
| `tier` | 1 to 5, from the scoring rubric. |
| `constraints` | Optional: what the task must not change. |

### Acceptance check patterns

| Kind of task | Good acceptance check |
|---|---|
| code / refactor | `<linter> <path> && <test command> <path>` passes |
| test | `<test file>` passes, has N+ cases, covers <cases> |
| debug | a repro test that failed before now passes, and the full suite passes |
| data | the migration applies on a branch, the linter or advisor shows no new issues, the RLS test passes |
| ops | the command exits with 0, and `<check command>` shows the expected state |
| explore / browse | the log answers <questions>, with file:line or URL sources |
| docs | the section exists and matches the code (names, defaults, examples run) |
| architecture | an ADR with options, choice, trade-offs, and the interface signatures |

If you cannot write a check for a task, the goal is not clear. Split the task or ask.

## Step 2: Classify the category

| Category | Use when the main work is |
|---|---|
| explore | reading or searching code and summarizing it |
| ops | terminal work: install, build, run, git, deploy steps |
| browse | web browsing or web research |
| docs | writing docs, comments, READMEs |
| test | writing or fixing tests |
| code | implementing a feature or a change |
| refactor | changing structure, same behavior |
| debug | finding a cause and fixing a bug |
| data | SQL, migrations, RLS, data pipelines |
| architecture | design decisions, interfaces, structure |

If two categories fit, pick the one that is harder to get right.

## Step 3: Score the tier

Score each task on 4 questions. Add the points.

| Question | 0 | 1 | 2 |
|---|---|---|---|
| Scope: how many files or modules? | 1 file | 2 to 4 files | cross-module |
| Clarity: is the path known? | known steps | some judgment | unknown cause or design choice |
| Risk: what breaks if it is wrong? | nothing, easy to undo | local bug | security, data, production |
| Verification: how hard is the check? | one command | several checks | manual or subtle reasoning |

Total → tier: 0-1 → T1 · 2-3 → T2 · 4-5 → T3 · 6-7 → T4 · 8 → T5.

Override rules:
- Risk = 2 → at least T4.
- Auth, payments, RLS, secrets, data deletion → risk = 2.
- An irreversible step (production migration, force push, deploy) → T5, and put it in a separate task.

Do not raise the tier "to be safe". The retry ladder handles underestimates, and that is cheaper than overestimating every task. Write the score in the task as `"score": "S1 C1 R0 V1 = 3"`, so the improver can check the rubric later.

## Step 4: Check the size

A good micro-task is one worker run: about 5 to 30 tool calls, one goal, one acceptance check.

- **Too big:** more than one goal, more than about 5 files, or "and" in the goal. Split it.
- **Too small:** under about 3 tool calls. Merge it with a neighbor that has the same category and the same files. Each subagent start costs context overhead, so tiny tasks waste tokens.
- **Mixed:** an explore part and a code part in one task. Split them, so the explore part can run on a cheap model.

## Step 5: Check the dependencies

1. No cycles.
2. Tasks that change the same file do not run in parallel. Add a dep between them.
3. Read-only tasks (explore, browse) have no deps on code tasks, unless they check the result.
4. Put tasks without deps first, so they can start in parallel.

## Step 6: Self-check, then output

Before you write the output, check each item:
- [ ] Every goal is a state, not an activity.
- [ ] Every acceptance check can be run or checked by a different agent.
- [ ] Every task has one category and a tier with its score.
- [ ] No task is too big or too small.
- [ ] The deps have no cycles and no parallel writes to the same file.

Output:
1. `tasks.json` (schema: `${CLAUDE_SKILL_DIR}/../../routing/templates/tasks.example.json`), when a run folder exists.
2. In the reply: a table with ID, title, category, tier, deps and route, plus one line with the count per tier. Do not repeat the goals in the reply. They are in the file.
3. A Mermaid `flowchart TD` of the deps, when there are more than 4 tasks.

## Example

Request: "Add token refresh to the Flutter auth flow, with tests."

| ID | Title | Cat | Score | Tier | Deps |
|---|---|---|---|---|---|
| T1 | Map auth calls | explore | S1 C0 R0 V0 = 1 | 1 | – |
| T2 | Add refresh timer | code | S0 C1 R2 V1 = 4 → override R2 | 4 | T1 |
| T3 | Test refresh cases | test | S0 C1 R0 V1 = 2 | 2 | T2 |
| T4 | Document refresh behavior | docs | S0 C0 R0 V1 = 1 | 1 | T2 |

T2 is tier 4 because auth gives risk = 2. T3 and T4 can run in parallel.
