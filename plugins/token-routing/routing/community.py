#!/usr/bin/env python3
"""Share anonymous routing results with the community, and adopt improved community defaults.

Usage:
  community.py export          # write history/community-export.json (anonymous, aggregated)
  community.py sync-defaults   # adopt new plugin defaults for cells you never tuned locally

What export contains: counts per category x tier and per tier-score pattern (S C R V), routes as
"model/effort" strings, failure-type counts, average tokens. Nothing else: no task titles, goals,
file names, paths, code, logs, run IDs or dates of single tasks.
Each export is cumulative and replaces your previous submission (same random contributor ID).
"""
import json
import re
import sys
import uuid
from collections import Counter, defaultdict
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import DEFAULTS, data_dir  # noqa: E402
import metrics  # noqa: E402

SCHEMA = "token-routing-feedback/1"
SCORE_RE = re.compile(r"S([0-2])\s*C([0-2])\s*R([0-2])\s*V([0-2])")
REPO = "Marco-Bonito/Claude_token_reduction_bundle"


def plugin_version():
    p = Path(__file__).resolve().parents[1] / ".claude-plugin" / "plugin.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))["version"]
    except (OSError, KeyError, ValueError):
        return "unknown"


def contributor_id():
    f = metrics.HIST / "contributor-id"
    metrics.HIST.mkdir(exist_ok=True)
    if not f.exists():
        f.write_text(str(uuid.uuid4()), encoding="utf-8")
    return f.read_text(encoding="utf-8").strip()


def route_name(row):
    return f"{row['model']}/{row['effort']}"


def norm_score(s):
    m = SCORE_RE.search(s or "")
    return "S{} C{} R{} V{}".format(*m.groups()) if m else None


def export():
    rows = metrics.read_metrics()
    if not rows:
        sys.exit("No metrics yet. Run some /orchestrate runs first.")
    tasks = defaultdict(list)
    for r in rows:
        tasks[(r["run_id"], r["task_id"])].append(r)

    cells = defaultdict(lambda: {"tasks": 0, "first_pass": 0, "solved": 0, "first_routes": Counter(),
                                 "win_routes": Counter(), "fail_types": Counter(), "tokens_sum": 0, "tokens_n": 0})
    scores = defaultdict(lambda: {"tasks": 0, "first_pass": 0, "win_routes": Counter()})
    for atts in tasks.values():
        atts.sort(key=lambda r: r["n"])
        first = atts[0]
        cat, tier = first["category"], first["tier"]
        win = next((a for a in atts if a["result"] == "pass"), None)
        c = cells[f"{cat}:{tier}"]
        c["tasks"] += 1
        c["first_pass"] += first["result"] == "pass"
        c["solved"] += win is not None
        c["first_routes"][route_name(first)] += 1
        if win:
            c["win_routes"][route_name(win)] += 1
        for a in atts:
            if a.get("fail_type"):
                c["fail_types"][a["fail_type"]] += 1
        tok = sum(a.get("tokens") or 0 for a in atts)
        if tok:
            c["tokens_sum"] += tok
            c["tokens_n"] += 1
        sc = norm_score(first.get("score"))
        if sc:
            s = scores[f"{cat}:{tier}:{sc}"]
            s["tasks"] += 1
            s["first_pass"] += first["result"] == "pass"
            if win:
                s["win_routes"][route_name(win)] += 1

    out_cells = {}
    for k, c in cells.items():
        out_cells[k] = {"tasks": c["tasks"], "first_pass": c["first_pass"], "solved": c["solved"],
                        "first_routes": dict(c["first_routes"]), "win_routes": dict(c["win_routes"]),
                        "fail_types": dict(c["fail_types"]),
                        "avg_tokens": int(c["tokens_sum"] / c["tokens_n"]) if c["tokens_n"] else None}
    out_scores = {k: {"tasks": s["tasks"], "first_pass": s["first_pass"], "win_routes": dict(s["win_routes"])}
                  for k, s in scores.items()}
    t = metrics.load_table()
    doc = {"schema": SCHEMA, "contributor": contributor_id(), "plugin_version": plugin_version(),
           "table_version": t.get("version", 1), "defaults_version": t.get("defaults_version", 1),
           "cells": out_cells, "scores": out_scores}
    path = metrics.HIST / "community-export.json"
    text = json.dumps(doc, indent=1, sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8")
    n_tasks = sum(c["tasks"] for c in out_cells.values())
    print(f"Wrote {path} ({len(text):,} chars, {n_tasks} tasks, {len(out_cells)} cells).")
    issue = metrics.HIST / "community-issue.md"
    issue.write_text("### Feedback JSON\n\n```json\n" + text + "\n```\n", encoding="utf-8")
    print("Check the file. It holds only counts, categories, tiers and model/effort names.")
    print("Share it, option 1 (browser): https://github.com/%s/issues/new?template=routing-feedback.yml" % REPO)
    print("  and paste the file content.")
    print("Share it, option 2 (GitHub CLI):")
    print(f'  gh issue create --repo {REPO} --title "Routing feedback" --body-file "{issue}"')

def sync_defaults():
    t = metrics.load_table()
    d = json.loads((DEFAULTS / "routing-table.json").read_text(encoding="utf-8"))
    if [tuple(s.values()) for s in t["ladder"]] != [tuple(s.values()) for s in d["ladder"]]:
        sys.exit("Your ladder differs from the plugin ladder. Sync skipped, to avoid wrong indexes.")
    local = t.get("improver_state", {}).get("cell_version", {})
    changes = []
    for cat, dc in d["categories"].items():
        if cat not in t["categories"]:
            t["categories"][cat] = dc
            changes.append(f"- new category {cat}")
            continue
        for i, idx in enumerate(dc["tiers"]):
            key = f"{cat}:{i + 1}"
            cur = t["categories"][cat]["tiers"][i]
            if key in local or cur == idx:
                continue  # tuned locally by your improver, or already equal
            lad = t["ladder"]
            changes.append(f"- {key}: {lad[cur]['model']}/{lad[cur]['effort']} -> {lad[idx]['model']}/{lad[idx]['effort']} (community default)")
            t["categories"][cat]["tiers"][i] = idx
    dv = d.get("defaults_version", 1)
    if not changes and t.get("defaults_version", 1) == dv:
        print(json.dumps({"synced": 0}))
        return
    old_v = t.get("version", 1)
    metrics.VERSIONS.mkdir(parents=True, exist_ok=True)
    (metrics.VERSIONS / f"v{old_v}.json").write_text(metrics.TABLE.read_text(encoding="utf-8"), encoding="utf-8")
    t["version"] = old_v + 1
    t["defaults_version"] = dv
    fresh = t.setdefault("improver_state", {}).setdefault("fresh_since", {})
    for line in changes:
        m = re.match(r"- (\w+:\d)", line)
        if m:
            # Old local data must not judge the new route. Not marked as "tuned locally",
            # so a later sync can still update this cell.
            fresh[m.group(1)] = t["version"]
    metrics.save_table(t)
    with (metrics.HIST / "CHANGELOG.md").open("a", encoding="utf-8") as f:
        f.write(f"\n## v{t['version']} — {metrics.now()} sync to community defaults v{dv}\n" + "\n".join(changes) + "\n")
    print(json.dumps({"synced": len(changes), "version": t["version"], "defaults_version": dv}))


def main(a):
    if len(a) < 2:
        sys.exit(__doc__)
    if a[1] == "export":
        return export()
    if a[1] == "sync-defaults":
        return sync_defaults()
    sys.exit(f"unknown command {a[1]}")


if __name__ == "__main__":
    main(sys.argv)
