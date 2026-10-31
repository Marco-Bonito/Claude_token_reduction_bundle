# Contributing

1. Fork the repo and create a branch.
2. Make one change per pull request.
3. Run `python3 tests/run_tests.py`. All tests must pass. Add a test when you change a script.
4. Keep the scripts dependency-free (Python standard library only, 3.9+).
5. Write docs and skill text in simple technical English: short sentences, active voice, one instruction per sentence.

## Good contributions

- Better default routes, backed by numbers from your `history/report.md`. Remove project details before you share them.
- New categories, with a clear "use when" rule and a ceiling.
- Better acceptance-check patterns in `skills/decompose/SKILL.md`.
- Support for more transcript formats in `metrics.py`.

## Versioning

Bump `version` in `plugins/token-routing/.claude-plugin/plugin.json` and `.claude-plugin/marketplace.json`, and add an entry to `CHANGELOG.md`.
