#!/usr/bin/env python3
"""Route map: the single source of truth for a run. tasks.json in, route-map.md out.

Usage:
  route_map.py render   <run_dir>                       # write route-map.md (Mermaid diagram + table)
  route_map.py next     <run_dir>                       # tasks ready to start (all deps done)
  route_map.py set      <run_dir> <task_id> key=value [key=value ...]   # model=/effort= update the current route
  route_map.py attempt  <run_dir> <task_id> <model> <effort> <pass|fail> [fail_type=..] [log=..] [tokens=..] [tool_uses=..] [duration_s=..] [agent_id=..]
  route_map.py brief    <run_dir> <task_id>             # compact task brief for a worker prompt
  route_map.py summary  <run_dir>                       # one line per task, for the orchestrator

Status values: todo | running | review | done | failed | blocked
The orchestrator reads 'summary' and 'next' instead of re-reading files. This keeps its context small.
"""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import data_dir  # noqa: E402

STATUSES = ["todo", "running", "review", "done", "failed", "blocked"]
STYLE = {
    "todo": "fill:#F1EFE8,stroke:#888780,color:#2C2C2A",
    "running": "fill:#E6F1FB,stroke:#185FA5,color:#0C447C",
    "review": "fill:#EEEDFE,stroke:#534AB7,color:#3C3489",
    "done": "fill:#EAF3DE,stroke:#3B6D11,color:#27500A",
    "failed": "fill:#FAEEDA,stroke:#854F0B,color:#633806",
    "blocked": "fill:#FCEBEB,stroke:#A32D2D,color:#791F1F",
}


def load(run):
    p = Path(run) / "tasks.json"
    return p, json.loads(p.read_text(encoding="utf-8"))


def save(p, data):
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def task(data, tid):
    for t in data["tasks"]:
        if t["id"] == tid:
            return t
    sys.exit(f"task {tid} not found")


def last_route(t):
    r = t.get("route") or {}
    if r:
        return f"{r.get('model','?')}/{r.get('effort','?')}"
    a = t.get("attempts") or []
    return f"{a[-1]['model']}/{a[-1]['effort']}" if a else "?/?"


def render(run):
    p, data = load(run)
    lines = [f"# Route map: {data.get('goal','')}", "", f"Run: `{data.get('run_id','')}` · Plan: [plan.md](plan.md)", ""]
    lines += ["```mermaid", "flowchart TD"]
    for h in data.get("high_level", []):
        lines.append(f'  subgraph {h["id"]}["{h["id"]} · {h["title"]}"]')
        for t in [t for t in data["tasks"] if t.get("parent") == h["id"]]:
            label = f'{t["id"]} {t["title"]}<br/>{t["category"]} · T{t["tier"]} · {last_route(t)}'
            lines.append(f'    {t["id"]}["{label}"]')
        lines.append("  end")
    for t in data["tasks"]:
        for d in t.get("deps", []):
            lines.append(f"  {d} --> {t['id']}")
    for s, style in STYLE.items():
        lines.append(f"  classDef {s} {style}")
    for t in data["tasks"]:
        lines.append(f"  class {t['id']} {t.get('status','todo')}")
    lines += ["```", ""]
    lines += ["| ID | Task | Goal | Cat | Tier | Route | Attempts | Status |", "|---|---|---|---|---|---|---|---|"]
    for t in data["tasks"]:
        lines.append(
            f"| {t['id']} | {t['title']} | {t['goal']} | {t['category']} | {t['tier']} | "
            f"{last_route(t)} | {len(t.get('attempts', []))} | {t.get('status','todo')} |"
        )
    counts = {s: sum(1 for t in data["tasks"] if t.get("status", "todo") == s) for s in STATUSES}
    lines += ["", "Progress: " + " · ".join(f"{s} {n}" for s, n in counts.items() if n)]
    (Path(run) / "route-map.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {Path(run) / 'route-map.md'}")


def ready(data):
    done = {t["id"] for t in data["tasks"] if t.get("status") == "done"}
    return [t for t in data["tasks"] if t.get("status", "todo") in ("todo", "failed")
            and all(d in done for d in t.get("deps", []))]


def main(a):
    if len(a) < 3:
        sys.exit(__doc__)
    cmd, run = a[1], a[2]
    if cmd == "render":
        return render(run)
    p, data = load(run)
    if cmd == "next":
        r = ready(data)
        print(json.dumps([{"id": t["id"], "category": t["category"], "tier": t["tier"], "status": t.get("status", "todo")} for t in r]))
        return
    if cmd == "summary":
        for t in data["tasks"]:
            print(f"{t['id']} [{t.get('status','todo')}] {t['category']}/T{t['tier']} {last_route(t)} "
                  f"a={len(t.get('attempts', []))} deps={','.join(t.get('deps', [])) or '-'} :: {t['title']}")
        return
    if cmd == "brief":
        t = task(data, a[3])
        dep_notes = [f"- {d}: {task(data, d).get('result_note','done')}" for d in t.get("deps", [])]
        print(f"TASK {t['id']}: {t['title']}\nRUN: {run}\nPLAN CONTEXT: {data.get('plan_digest','see plan.md')}\n"
              f"GOAL: {t['goal']}\nACCEPTANCE: {t['acceptance']}\nFILES: {', '.join(t.get('files', [])) or 'not fixed'}\n"
              f"CONSTRAINTS: {t.get('constraints','none')}\nDEPENDENCY RESULTS:\n" + ("\n".join(dep_notes) or "- none"))
        lessons = data_dir() / "lessons.md"
        if lessons.exists():
            tags = (f"[{t['category']}]", "[all]")
            hits = [l.strip() for l in lessons.read_text(encoding="utf-8").splitlines()
                    if l.strip().startswith("- ") and any(tag in l for tag in tags)]
            if hits:
                print("LESSONS FROM PAST RUNS:\n" + "\n".join(hits[:6]))
        prev = t.get("attempts") or []
        if prev:
            print("PREVIOUS ATTEMPTS (do not repeat these mistakes):")
            for x in prev:
                print(f"- attempt {x['n']} {x['model']}/{x['effort']}: {x['result']} ({x.get('fail_type','-')}) log: {x.get('log','-')}")
        return
    if cmd == "set":
        t = task(data, a[3])
        for kv in a[4:]:
            k, v = kv.split("=", 1)
            if k == "status" and v not in STATUSES:
                sys.exit(f"bad status {v}")
            if k in ("model", "effort"):
                t.setdefault("route", {})[k] = v
            else:
                t[k] = int(v) if k == "tier" else v
        save(p, data)
        print("ok")
        return
    if cmd == "attempt":
        t = task(data, a[3])
        rec = {"n": len(t.setdefault("attempts", [])) + 1, "model": a[4], "effort": a[5], "result": a[6],
               "fail_type": None, "log": None}
        for kv in a[7:]:
            k, v = kv.split("=", 1)
            rec[k] = int(v) if k in ("tokens", "tool_uses", "duration_s") and v.isdigit() else v
        t["attempts"].append(rec)
        save(p, data)
        print(json.dumps({"attempts": len(t["attempts"])}))
        return
    sys.exit(f"unknown command {cmd}")


if __name__ == "__main__":
    main(sys.argv)
