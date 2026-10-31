# Changelog

## 1.0.0 — 2026-10-31

- `/orchestrate`: plan → questions → plan v2 → high-level tasks → decompose → route → route map → dispatch → review → retry with escalation → close.
- `/decompose`: micro-tasks with goal, acceptance check, category, tier score (scope, clarity, risk, verification), size and dependency checks. Works alone too.
- `/improve` + `improver` agent + `metrics.py`: metrics after every batch, table tuning with guardrails, lessons, prompt proposals, versioned table with rollback.
- Routing table: 10-step ladder (haiku/low → fable/high), 10 categories × 5 tiers, ceilings, failure-type retry policy.
- `worker`, `reviewer` agents with per-call model and effort.
- Plugin marketplace, manual install scripts (bash, PowerShell), end-to-end tests, CI on Linux, Windows and macOS.
