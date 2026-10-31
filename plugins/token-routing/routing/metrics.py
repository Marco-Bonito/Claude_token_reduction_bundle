#!/usr/bin/env python3
"""Metrics and table tuning for the routing kit. Deterministic, no model tokens.

Usage:
  metrics.py collect  <run_dir>        # after every batch: append new attempts to history/metrics.jsonl
  metrics.py report                    # stats per category x tier -> history/report.md + history/proposals.json
  metrics.py apply    [--dry-run]      # apply auto table proposals (guardrails in routing-table.json "improver")
  metrics.py rollback [version]        # restore an earlier routing-table.json (default: previous)
  metrics.py versions                  # list table versions

Statistics only count samples recorded with the CURRENT table version of each cell,
so a change is judged on new data, not on the data that caused it.
"""
import glob
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import data_dir  # noqa: E402

HERE = data_dir()
TABLE = HERE / "routing-table.json"
HIST = HERE / "history"
METRICS = HIST / "metrics.jsonl"
VERSIONS = HIST / "table-versions"


def now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_table():
    return json.loads(TABLE.read_text(encoding="utf-8"))


def save_table(t):
    TABLE.write_text(json.dumps(t, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def ladder_index(t, model, effort):
    for i, s in enumerate(t["ladder"]):
        if s["model"] == model and s["effort"] == effort:
            return i
    return None


def read_metrics():
    if not METRICS.exists():
        return []
    return [json.loads(l) for l in METRICS.read_text(encoding="utf-8").splitlines() if l.strip()]


def transcript_usage(t, agent_id):
    pattern = os.path.expanduser(t["improver"]["transcripts_glob"].format(agent_id=agent_id))
    files = glob.glob(pattern)
    if not files:
        return None
    u = Counter()
    for line in Path(files[0]).read_text(encoding="utf-8").splitlines():
        try:
            msg = json.loads(line).get("message") or {}
        except json.JSONDecodeError:
            continue
        usage = msg.get("usage") or {}
        for k in ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens"):
            u[k] += usage.get(k) or 0
    return {"tokens_in": u["input_tokens"] + u["cache_creation_input_tokens"],
            "tokens_out": u["output_tokens"], "cache_read": u["cache_read_input_tokens"],
            "tokens": u["input_tokens"] + u["cache_creation_input_tokens"] + u["output_tokens"]}


def cell_key(category, tier):
    return f"{category}:{tier}"


# ---------------------------------------------------------------- collect
def collect(run_dir):
    t = load_table()
    HIST.mkdir(exist_ok=True)
    data = json.loads((Path(run_dir) / "tasks.json").read_text(encoding="utf-8"))
    seen = {(m["run_id"], m["task_id"], m["n"]) for m in read_metrics()}
    added = 0
    with METRICS.open("a", encoding="utf-8") as f:
        for task in data["tasks"]:
            atts = task.get("attempts") or []
            if not atts:
                continue
            # Only collect finished tasks, so first-pass and final result are known.
            if task.get("status") not in ("done", "blocked"):
                continue
            for a in atts:
                key = (data["run_id"], task["id"], a["n"])
                if key in seen:
                    continue
                rec = {
                    "ts": now(), "run_id": data["run_id"], "task_id": task["id"],
                    "category": task["category"], "tier": task["tier"],
                    "n": a["n"], "model": a["model"], "effort": a["effort"],
                    "ladder_index": ladder_index(t, a["model"], a["effort"]),
                    "result": a["result"], "fail_type": a.get("fail_type"),
                    "task_status": task.get("status"), "log": a.get("log"),
                    "tokens": a.get("tokens"), "tool_uses": a.get("tool_uses"),
                    "duration_s": a.get("duration_s"), "agent_id": a.get("agent_id"),
                    "table_version": t.get("version", 1),
                }
                if rec["log"] and not os.path.isabs(rec["log"]):
                    rec["log"] = str(Path(run_dir) / rec["log"])
                if rec["agent_id"]:
                    u = transcript_usage(t, rec["agent_id"])  # transcript beats the reported number
                    if u:
                        rec["tokens_reported"] = rec["tokens"]
                        rec.update(u)
                f.write(json.dumps(rec) + "\n")
                added += 1
    print(json.dumps({"added": added, "metrics_file": str(METRICS)}))


# ---------------------------------------------------------------- report
def task_view(rows):
    """Group attempt rows into tasks."""
    tasks = defaultdict(list)
    for r in rows:
        tasks[(r["run_id"], r["task_id"])].append(r)
    out = []
    for key, atts in tasks.items():
        atts.sort(key=lambda r: r["n"])
        win = next((a for a in atts if a["result"] == "pass"), None)
        out.append({
            "key": key, "category": atts[0]["category"], "tier": atts[0]["tier"],
            "base_index": atts[0]["ladder_index"], "attempts": len(atts),
            "first_pass": atts[0]["result"] == "pass", "solved": win is not None,
            "win_index": win["ladder_index"] if win else None,
            "tokens": sum(a.get("tokens") or 0 for a in atts),
            "fail_types": [a["fail_type"] for a in atts if a.get("fail_type")],
            "logs": [a["log"] for a in atts if a["result"] != "pass" and a.get("log")],
            "status": atts[-1]["task_status"], "rows": atts,
        })
    return out


def report():
    t = load_table()
    cfg = t["improver"]
    w = cfg["cost_weights"]
    state = t.setdefault("improver_state", {}).setdefault("cell_version", {})
    rows = read_metrics()
    if not rows:
        print(json.dumps({"error": "no metrics yet; run collect first"}))
        return
    # Keep only rows newer than the last change of their cell.
    fresh = [r for r in rows if r["table_version"] >= state.get(cell_key(r["category"], r["tier"]), 0)]
    tasks = task_view(fresh)
    for tk in tasks:
        tk["cost"] = round(sum((a.get("tokens") or 0) / 1000 * w.get(a["model"], 1) for a in tk["rows"]), 1)

    cells = defaultdict(list)
    for tk in tasks:
        cells[(tk["category"], tk["tier"])].append(tk)

    proposals, lines = [], []
    lines += [f"# Routing report — {now()}", "", f"Table version: {t.get('version', 1)} · attempts: {len(rows)} · fresh attempts: {len(fresh)}", ""]
    lines += ["## Cells (category × tier)", "",
              "| Cell | Route | Tasks | First pass | Avg attempts | Blocked | Avg tokens/task | Cost units/task | Proposal |",
              "|---|---|---|---|---|---|---|---|---|"]
    for (cat, tier), tks in sorted(cells.items()):
        c = t["categories"].get(cat)
        if not c:
            continue
        base = c["tiers"][tier - 1]
        route = f"{t['ladder'][base]['model']}/{t['ladder'][base]['effort']}"
        n = len(tks)
        fp = sum(x["first_pass"] for x in tks) / n
        avg_att = sum(x["attempts"] for x in tks) / n
        blocked = sum(not x["solved"] for x in tks)
        avg_tok = int(sum(x["tokens"] for x in tks) / n)
        avg_cost = round(sum(x["cost"] for x in tks) / n, 1)
        prop = ""
        wins = [x["win_index"] for x in tks if x["win_index"] is not None]
        target = int(statistics.median(wins)) if wins else base + 1
        step = max(-cfg["max_step_per_cycle"], min(cfg["max_step_per_cycle"], target - base))
        if n >= cfg["min_samples"] and fp < cfg["raise_if_first_pass_below"]:
            step = max(step, 1)
            new = min(base + step, c["ceiling"])
            if new != base:
                proposals.append({"type": "table", "cell": cell_key(cat, tier), "from": base, "to": new,
                                  "reason": f"first pass {fp:.0%} < {cfg['raise_if_first_pass_below']:.0%} over {n} tasks; median winning route index {target}",
                                  "auto": cfg["auto_apply_table"]})
                prop = f"raise → {t['ladder'][new]['model']}/{t['ladder'][new]['effort']}"
        elif n >= cfg["lower_min_samples"] and fp > cfg["lower_if_first_pass_above"] and base > 0:
            new = base - 1
            proposals.append({"type": "table", "cell": cell_key(cat, tier), "from": base, "to": new,
                              "reason": f"first pass {fp:.0%} > {cfg['lower_if_first_pass_above']:.0%} over {n} tasks; probe a cheaper route",
                              "auto": cfg["auto_apply_table"]})
            prop = f"lower → {t['ladder'][new]['model']}/{t['ladder'][new]['effort']}"
        elif n < cfg["min_samples"]:
            prop = f"wait ({n}/{cfg['min_samples']} samples)"
        lines.append(f"| {cat}:T{tier} | {route} | {n} | {fp:.0%} | {avg_att:.2f} | {blocked} | {avg_tok} | {avg_cost} | {prop} |")

    # Category ceilings: blocked tasks that used the ceiling route.
    blocked_at_ceiling = Counter(tk["category"] for tk in tasks if not tk["solved"]
                                 and tk["rows"][-1]["ladder_index"] == t["categories"][tk["category"]]["ceiling"])
    for cat, k in blocked_at_ceiling.items():
        if k >= 2:
            proposals.append({"type": "ceiling", "category": cat, "from": t["categories"][cat]["ceiling"],
                              "to": min(t["categories"][cat]["ceiling"] + 1, len(t["ladder"]) - 1),
                              "reason": f"{k} tasks blocked at the ceiling route", "auto": False})

    # Signals for the improver agent (qualitative work).
    ft = defaultdict(Counter)
    for tk in tasks:
        for f in tk["fail_types"]:
            ft[tk["category"]][f] += 1
    drift = [tk for tk in tasks if tk["win_index"] is not None and tk["base_index"] is not None
             and tk["win_index"] - tk["base_index"] >= 2]
    lines += ["", "## Failure types per category", ""]
    for cat, cnt in sorted(ft.items()):
        lines.append(f"- {cat}: " + ", ".join(f"{k} {v}" for k, v in cnt.most_common()))
    lines += ["", "## Tier drift (solved 2+ ladder steps above the first route)", ""]
    lines += [f"- {tk['key'][0]}/{tk['key'][1]} {tk['category']} T{tk['tier']}: base {tk['base_index']} → won at {tk['win_index']}" for tk in drift] or ["- none"]
    failed_logs = [l for tk in tasks for l in tk["logs"]][-10:]
    lines += ["", "## Failure logs to read (latest 10)", ""] + [f"- {l}" for l in failed_logs] + (["- none"] if not failed_logs else [])
    by_model = Counter()
    for r in fresh:
        by_model[r["model"]] += r.get("tokens") or 0
    lines += ["", "## Tokens by model (fresh data)", ""] + [f"- {m}: {v:,}" for m, v in by_model.most_common()]
    missing = sum(1 for r in fresh if not r.get("tokens"))
    if missing:
        lines.append(f"- {missing} attempts have no token data. Pass tokens= or agent_id= to route_map.py attempt.")
    lines += ["", "## Proposals", ""] + [f"- [{p['type']}] {p.get('cell', p.get('category'))}: {p['from']} → {p['to']} · {p['reason']} · auto={p['auto']}" for p in proposals] + (["- none"] if not proposals else [])

    HIST.mkdir(exist_ok=True)
    (HIST / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (HIST / "proposals.json").write_text(json.dumps({"generated": now(), "table_version": t.get("version", 1),
                                                     "proposals": proposals, "failed_logs": failed_logs,
                                                     "drift": [list(tk["key"]) for tk in drift]}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(HIST / "report.md"), "proposals": len(proposals)}))


# ---------------------------------------------------------------- apply / rollback
def apply(dry):
    t = load_table()
    pfile = HIST / "proposals.json"
    if not pfile.exists():
        sys.exit("no proposals.json; run report first")
    props = json.loads(pfile.read_text(encoding="utf-8"))
    if props["table_version"] != t.get("version", 1):
        sys.exit("proposals are for an older table version; run report again")
    todo = [p for p in props["proposals"] if p.get("auto") and not p.get("applied")]
    if not todo:
        print(json.dumps({"applied": 0}))
        return
    old_v = t.get("version", 1)
    new_v = old_v + 1
    changes = []
    for p in todo:
        if p["type"] == "table":
            cat, tier = p["cell"].split(":")
            t["categories"][cat]["tiers"][int(tier) - 1] = p["to"]
            t.setdefault("improver_state", {}).setdefault("cell_version", {})[p["cell"]] = new_v
        elif p["type"] == "ceiling":
            t["categories"][p["category"]]["ceiling"] = p["to"]
        lad = t["ladder"]
        changes.append(f"- {p.get('cell', p.get('category'))}: {lad[p['from']]['model']}/{lad[p['from']]['effort']} → "
                       f"{lad[p['to']]['model']}/{lad[p['to']]['effort']} — {p['reason']}")
        p["applied"] = True
    if dry:
        print("\n".join(changes))
        return
    VERSIONS.mkdir(parents=True, exist_ok=True)
    (VERSIONS / f"v{old_v}.json").write_text(TABLE.read_text(encoding="utf-8"), encoding="utf-8")
    t["version"] = new_v
    save_table(t)
    pfile.write_text(json.dumps(props, indent=2) + "\n", encoding="utf-8")
    with (HIST / "CHANGELOG.md").open("a", encoding="utf-8") as f:
        f.write(f"\n## v{new_v} — {now()} (metrics.py apply)\n" + "\n".join(changes) + "\n")
    print(json.dumps({"applied": len(changes), "version": new_v}))


def rollback(version):
    t = load_table()
    cur = t.get("version", 1)
    target = int(version) if version else cur - 1
    src = VERSIONS / f"v{target}.json"
    if not src.exists():
        sys.exit(f"no saved version v{target}")
    VERSIONS.mkdir(parents=True, exist_ok=True)
    (VERSIONS / f"v{cur}.json").write_text(TABLE.read_text(encoding="utf-8"), encoding="utf-8")
    restored = json.loads(src.read_text(encoding="utf-8"))
    restored["version"] = cur + 1  # versions only go up, so metrics stay comparable
    cv = restored.setdefault("improver_state", {}).setdefault("cell_version", {})
    for cat, c in restored["categories"].items():
        now_tiers = t["categories"].get(cat, {}).get("tiers", [])
        for i, idx in enumerate(c["tiers"]):
            if i >= len(now_tiers) or now_tiers[i] != idx:
                cv[cell_key(cat, i + 1)] = cur + 1
    save_table(restored)
    with (HIST / "CHANGELOG.md").open("a", encoding="utf-8") as f:
        f.write(f"\n## v{cur + 1} — {now()} rollback to the content of v{target}\n")
    print(json.dumps({"restored_from": target, "version": cur + 1}))


def main(a):
    if len(a) < 2:
        sys.exit(__doc__)
    cmd = a[1]
    if cmd == "collect":
        return collect(a[2])
    if cmd == "report":
        return report()
    if cmd == "apply":
        return apply("--dry-run" in a)
    if cmd == "rollback":
        return rollback(a[2] if len(a) > 2 else None)
    if cmd == "versions":
        print("\n".join(sorted(p.name for p in VERSIONS.glob("v*.json"))) if VERSIONS.exists() else "none")
        return
    sys.exit(f"unknown command {cmd}")


if __name__ == "__main__":
    main(sys.argv)
