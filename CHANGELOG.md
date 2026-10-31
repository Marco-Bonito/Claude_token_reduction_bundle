# Changelog

## 1.1.0 — 2026-10-31

- Community feedback loop: `community.py export` (anonymous, aggregated), GitHub issue form, `feedback-intake` workflow (strict validation, stores data in the `community-feedback` branch), weekly `community-aggregate` workflow (report + pull request with better defaults).
- Classification findings: drift per tier-score component (S, C, R, V) and per score total, to tune the decompose rubric.
- `community.py sync-defaults`: adopt new defaults for cells not tuned locally. `/improve` runs it first.
- Fairness rules: min 3 contributors, contributor weight cap, max 1 ladder step per cycle.
- `rollback` now marks restored cells as fresh, not as tuned locally.
- Tier scores are now stored in metrics.

## 1.0.0 — 2026-10-31

- `/orchestrate`: plan → questions → plan v2 → high-level tasks → decompose → route → route map → dispatch → review → retry with escalation → close.
- `/decompose`: micro-tasks with goal, acceptance check, category, tier score (scope, clarity, risk, verification), size and dependency checks. Works alone too.
- `/improve` + `improver` agent + `metrics.py`: metrics after every batch, table tuning with guardrails, lessons, prompt proposals, versioned table with rollback.
- Routing table: 10-step ladder (haiku/low → fable/high), 10 categories × 5 tiers, ceilings, failure-type retry policy.
- `worker`, `reviewer` agents with per-call model and effort.
- Plugin marketplace, manual install scripts (bash, PowerShell), end-to-end tests, CI on Linux, Windows and macOS.
