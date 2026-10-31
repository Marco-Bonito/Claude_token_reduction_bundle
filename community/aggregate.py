#!/usr/bin/env python3
"""Combine all community submissions and propose better defaults and classification rules.

Usage:
  aggregate.py --submissions <dir> --table <defaults routing-table.json> --out <dir> [--apply]

Writes <out>/aggregate.json and <out>/report.md.
With --apply, it also updates the default table (max 1 ladder step per cell) and bumps defaults_version.
Rubric (classification) findings are written to the report only: a maintainer edits the decompose skill.

Fairness: each contributor's weight per cell is capped (community.cap_per_contributor tasks),
and a change needs community.min_contributors different contributors.
"""
import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from validate import Invalid, validate  # noqa: E402

COMPONENTS = ("S", "C", "R", "V")
DEFAULT_CFG = {"min_contributors": 3, "min_tasks": 30, "cap_per_contributor": 50, "max_step": 1,
               "rubric_min_tasks": 30, "rubric_drift": 0.75}


def wmedian(hist):
    """Weighted median of {value: weight}."""
    items = sorted(hist.items())
    total = sum(w for _, w in items)
    if total <= 0:
        return None
    acc = 0.0
    for v, w in items:
        acc += w
        if acc >= total / 2:
            return v
    return items[-1][0]


def tier_from_total(total):
    return 1 if total <= 1 else 2 if total <= 3 else 3 if total <= 5 else 4 if total <= 7 else 5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--submissions", required=True)
    ap.add_argument("--table", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()

    table_path = Path(a.table)
    table = json.loads(table_path.read_text(encoding="utf-8"))
    cfg = {**DEFAULT_CFG, **table.get("community", {})}
    idx = {f"{s['model']}/{s['effort']}": i for i, s in enumerate(table["ladder"])}
    lad = table["ladder"]
    name = lambda i: f"{lad[i]['model']}/{lad[i]['effort']}"  # noqa: E731

    subs, skipped = [], []
    for f in sorted(Path(a.submissions).glob("*.json")):
        try:
            doc = json.loads(f.read_text(encoding="utf-8"))
            subs.append(validate(doc.get("data", doc)))
        except (Invalid, ValueError, AttributeError) as e:
            skipped.append(f"{f.name}: {e}")

    cells = defaultdict(lambda: {"tasks": 0.0, "first_pass": 0.0, "solved": 0.0, "win": defaultdict(float),
                                 "contributors": set(), "fail_types": defaultdict(float), "tok_sum": 0.0, "tok_w": 0.0})
    comp = defaultdict(lambda: {"drift_sum": 0.0, "w": 0.0, "contributors": set()})
    totals = defaultdict(lambda: {"drift_sum": 0.0, "w": 0.0, "contributors": set()})
    for doc in subs:
        who = doc["contributor"]
        for key, c in doc["cells"].items():
            w = min(1.0, cfg["cap_per_contributor"] / c["tasks"])
            agg = cells[key]
            agg["tasks"] += c["tasks"] * w
            agg["first_pass"] += c["first_pass"] * w
            agg["solved"] += c["solved"] * w
            agg["contributors"].add(who)
            for r, n in c["win_routes"].items():
                if r in idx:
                    agg["win"][idx[r]] += n * w
            for ft, n in c["fail_types"].items():
                agg["fail_types"][ft] += n * w
            if c["avg_tokens"]:
                agg["tok_sum"] += c["avg_tokens"] * c["tasks"] * w
                agg["tok_w"] += c["tasks"] * w
        per_cat_tasks = defaultdict(int)
        for key, s in doc["scores"].items():
            per_cat_tasks[key.rsplit(":", 1)[0]] += s["tasks"]
        for key, s in doc["scores"].items():
            cat, tier, score = key.split(":")
            if cat not in table["categories"]:
                continue
            w = min(1.0, cfg["cap_per_contributor"] / max(1, per_cat_tasks[f"{cat}:{tier}"]))
            parts = dict(zip(COMPONENTS, (int(p[1]) for p in score.split())))
            total = sum(parts.values())
            base = table["categories"][cat]["tiers"][tier_from_total(total) - 1]
            for r, n in s["win_routes"].items():
                if r not in idx:
                    continue
                drift = idx[r] - base
                for c_name, v in parts.items():
                    k = comp[f"{c_name}={v}"]
                    k["drift_sum"] += drift * n * w
                    k["w"] += n * w
                    k["contributors"].add(who)
                t = totals[total]
                t["drift_sum"] += drift * n * w
                t["w"] += n * w
                t["contributors"].add(who)

    # ---- table proposals
    proposals, cell_rows = [], []
    for key in sorted(cells):
        cat, tier = key.split(":")
        tier = int(tier)
        agg = cells[key]
        if cat not in table["categories"]:
            continue
        cdef = table["categories"][cat]
        base = cdef["tiers"][tier - 1]
        target = wmedian(agg["win"])
        n_c = len(agg["contributors"])
        row = {"cell": key, "route": name(base), "tasks": round(agg["tasks"], 1), "contributors": n_c,
               "first_pass": round(agg["first_pass"] / agg["tasks"], 3) if agg["tasks"] else None,
               "solved": round(agg["solved"] / agg["tasks"], 3) if agg["tasks"] else None,
               "median_win": name(target) if target is not None else None,
               "avg_tokens": int(agg["tok_sum"] / agg["tok_w"]) if agg["tok_w"] else None,
               "fail_types": {k: round(v, 1) for k, v in agg["fail_types"].items()}}
        if target is not None and n_c >= cfg["min_contributors"] and agg["tasks"] >= cfg["min_tasks"] and target != base:
            step = max(-cfg["max_step"], min(cfg["max_step"], target - base))
            new = max(0, min(base + step, cdef["ceiling"]))
            if new != base:
                proposals.append({"cell": key, "from": base, "to": new, "from_route": name(base), "to_route": name(new),
                                  "reason": f"median winning route {name(target)} over {row['tasks']} weighted tasks from {n_c} contributors"})
                row["proposal"] = f"{name(base)} → {name(new)}"
        cell_rows.append(row)

    # ---- classification (rubric) findings
    rubric = []
    for k, v in sorted(comp.items()):
        if v["w"] <= 0:
            continue
        d = v["drift_sum"] / v["w"]
        ok = v["w"] >= cfg["rubric_min_tasks"] and len(v["contributors"]) >= cfg["min_contributors"]
        rubric.append({"component": k, "avg_drift": round(d, 2), "tasks": round(v["w"], 1), "contributors": len(v["contributors"]),
                       "finding": (("under-classified: raise its points" if d >= cfg["rubric_drift"] else
                                    "over-classified: lower its points" if d <= -cfg["rubric_drift"] else "ok") if ok else "not enough data")})
    tier_map = []
    for total in range(9):
        v = totals.get(total)
        if not v or v["w"] <= 0:
            continue
        d = v["drift_sum"] / v["w"]
        ok = v["w"] >= cfg["rubric_min_tasks"] and len(v["contributors"]) >= cfg["min_contributors"]
        cur = tier_from_total(total)
        sug = cur + 1 if (ok and d >= cfg["rubric_drift"] and cur < 5) else cur - 1 if (ok and d <= -cfg["rubric_drift"] and cur > 1) else cur
        tier_map.append({"total": total, "tier": cur, "avg_drift": round(d, 2), "tasks": round(v["w"], 1),
                         "contributors": len(v["contributors"]), "suggested_tier": sug})

    # ---- outputs
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    result = {"generated": now, "submissions": len(subs), "skipped": skipped, "config": cfg,
              "defaults_version": table.get("defaults_version", 1), "cells": cell_rows,
              "proposals": proposals, "rubric_components": rubric, "score_total_to_tier": tier_map}
    (out / "aggregate.json").write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    L = [f"# Community routing report — {now}", "",
         f"Submissions: {len(subs)} · skipped: {len(skipped)} · rules: ≥{cfg['min_contributors']} contributors, "
         f"≥{cfg['min_tasks']} weighted tasks, max {cfg['cap_per_contributor']} tasks per contributor per cell", "",
         "## Default table proposals", ""]
    L += [f"- `{p['cell']}`: {p['from_route']} → {p['to_route']} — {p['reason']}" for p in proposals] or ["- none"]
    L += ["", "## Cells", "", "| Cell | Default route | Tasks (w) | Contrib. | First pass | Solved | Median win | Avg tokens |", "|---|---|---|---|---|---|---|---|"]
    for r in cell_rows:
        fp = f"{r['first_pass']:.0%}" if r["first_pass"] is not None else "-"
        sv = f"{r['solved']:.0%}" if r["solved"] is not None else "-"
        L.append(f"| {r['cell']} | {r['route']} | {r['tasks']} | {r['contributors']} | {fp} | {sv} | {r['median_win'] or '-'} | {r['avg_tokens'] or '-'} |")
    L += ["", "## Classification: tier-score components", "",
          "Drift = winning ladder index − default index for the scored tier. Positive = the rubric gives too low a tier.", "",
          "| Component | Avg drift | Tasks (w) | Contrib. | Finding |", "|---|---|---|---|---|"]
    L += [f"| {r['component']} | {r['avg_drift']:+} | {r['tasks']} | {r['contributors']} | {r['finding']} |" for r in rubric] or ["| – | | | | no score data |"]
    L += ["", "## Classification: score total → tier", "", "| Total | Tier now | Avg drift | Tasks (w) | Contrib. | Suggested tier |", "|---|---|---|---|---|---|"]
    L += [f"| {r['total']} | T{r['tier']} | {r['avg_drift']:+} | {r['tasks']} | {r['contributors']} | T{r['suggested_tier']} |" for r in tier_map] or ["| – | | | | | no score data |"]
    if skipped:
        L += ["", "## Skipped submissions", ""] + [f"- {s}" for s in skipped]
    (out / "report.md").write_text("\n".join(L) + "\n", encoding="utf-8")

    if a.apply and proposals:
        for p in proposals:
            cat, tier = p["cell"].split(":")
            table["categories"][cat]["tiers"][int(tier) - 1] = p["to"]
        table["defaults_version"] = table.get("defaults_version", 1) + 1
        table_path.write_text(json.dumps(table, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"submissions": len(subs), "skipped": len(skipped), "proposals": len(proposals),
                      "applied": bool(a.apply and proposals), "defaults_version": table.get("defaults_version", 1)}))


if __name__ == "__main__":
    main()
