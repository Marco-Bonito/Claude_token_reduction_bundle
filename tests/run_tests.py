#!/usr/bin/env python3
"""End-to-end tests for the routing scripts. No dependencies. Run: python3 tests/run_tests.py"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
R = ROOT / "plugins" / "token-routing" / "routing"
TMP = Path(tempfile.mkdtemp(prefix="token-routing-test-"))
ENV = {**os.environ, "PYTHONIOENCODING": "utf-8", "TOKEN_ROUTING_DIR": str(TMP / "data"), "HOME": str(TMP / "home"), "USERPROFILE": str(TMP / "home")}
FAILS = []
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def run(script, *args, ok=True):
    p = subprocess.run([sys.executable, str(R / script), *map(str, args)], capture_output=True, text=True, env=ENV, cwd=TMP)
    if ok and p.returncode != 0:
        raise AssertionError(f"{script} {args} failed: {p.stdout}{p.stderr}")
    return p.stdout.strip()


def js(script, *args):
    return json.loads(run(script, *args).splitlines()[-1])


def check(name, cond, detail=""):
    print(("PASS " if cond else "FAIL ") + name + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def make_run(name, tasks):
    d = TMP / "runs" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "tasks.json").write_text(json.dumps({"run_id": name, "goal": "sim", "high_level": [{"id": "H1", "title": "x"}], "tasks": tasks}))
    return d


# ---- route.py
check("seeds data folder", (lambda r: (TMP / "data" / "routing-table.json").exists())(js("route.py", "base", "code", 3)))
check("base code T3 = sonnet/low", js("route.py", "base", "code", 3)["effort"] == "low" and js("route.py", "base", "code", 3)["model"] == "sonnet")
check("base ops T3 = haiku/medium", js("route.py", "base", "ops", 3) == {"action": "run", "model": "haiku", "effort": "medium", "ladder_index": 1})
e = js("route.py", "escalate", "code", "sonnet", "low", "depth", 1)
check("depth → more effort", (e["model"], e["effort"]) == ("sonnet", "medium"), e)
e = js("route.py", "escalate", "code", "sonnet", "medium", "capability", 2)
check("capability → next model", e["model"] == "opus", e)
check("max attempts → blocked", js("route.py", "escalate", "code", "opus", "medium", "depth", 3)["action"] == "blocked")
check("ceiling → blocked", js("route.py", "escalate", "ops", "sonnet", "high", "depth", 1)["action"] == "blocked")
check("spec → ask_user", js("route.py", "escalate", "code", "sonnet", "low", "spec", 1)["action"] == "ask_user")
check("environment → retry_same", js("route.py", "escalate", "code", "sonnet", "low", "environment", 1)["action"] == "retry_same")
check("reviewer T5 upgrades", js("route.py", "reviewer", 5)["model"] == "opus")

# ---- route_map.py
example = json.loads((R / "templates" / "tasks.example.json").read_text())
rd = make_run("map", example["tasks"])
check("next = T1 only", [t["id"] for t in js("route_map.py", "next", rd)] == ["T1"])
run("route_map.py", "set", rd, "T1", "status=done", "result_note=mapped")
check("next after T1 = T2", [t["id"] for t in js("route_map.py", "next", rd)] == ["T2"])
run("route_map.py", "attempt", rd, "T2", "sonnet", "low", "fail", "fail_type=depth", "log=logs/T2-a1.md", "tokens=1234")
run("route_map.py", "set", rd, "T2", "model=sonnet", "effort=medium")
brief = run("route_map.py", "brief", rd, "T2")
check("brief has previous attempts", "PREVIOUS ATTEMPTS" in brief and "sonnet/low" in brief)
check("brief has lessons", "LESSONS FROM PAST RUNS" in brief)
run("route_map.py", "render", rd)
check("route-map.md rendered", "flowchart TD" in (rd / "route-map.md").read_text())

# ---- metrics.py: simulate 3 runs
tdir = TMP / "home" / ".claude" / "projects" / "p" / "s" / "subagents"
tdir.mkdir(parents=True)
(tdir / "agent-abc123.jsonl").write_text(json.dumps({"message": {"usage": {"input_tokens": 1000, "output_tokens": 500, "cache_creation_input_tokens": 2000}}}) + "\n")
for r in range(3):
    tasks = []
    for i in range(3):
        fail = i < 2
        atts = [{"n": 1, "model": "sonnet", "effort": "low", "result": "fail" if fail else "pass", "fail_type": "depth" if fail else None, "log": f"logs/C{i}-a1.md", "tokens": 40000}]
        if fail:
            atts.append({"n": 2, "model": "sonnet", "effort": "medium", "result": "pass", "tokens": 30000, "agent_id": "abc123" if r == 0 and i == 0 else None})
        tasks.append({"id": f"C{i}", "parent": "H1", "title": "c", "goal": "g", "acceptance": "a", "category": "code", "tier": 3, "deps": [], "status": "done", "attempts": atts})
    tasks.append({"id": "R1", "parent": "H1", "title": "r", "goal": "g", "acceptance": "a", "category": "code", "tier": 3, "deps": [], "status": "running",
                  "attempts": [{"n": 1, "model": "sonnet", "effort": "low", "result": "fail"}]})
    make_run(f"run{r}", tasks)
added = [js("metrics.py", "collect", TMP / "runs" / f"run{r}")["added"] for r in range(3)]
check("collect skips unfinished tasks", added == [5, 5, 5], added)
check("collect dedupes", js("metrics.py", "collect", TMP / "runs" / "run0")["added"] == 0)
rows = [json.loads(l) for l in (TMP / "data" / "history" / "metrics.jsonl").read_text().splitlines()]
tr = next(r for r in rows if r.get("agent_id") == "abc123")
check("transcript tokens win", tr["tokens"] == 3500 and tr["tokens_reported"] == 30000, tr)
check("log paths include run folder", rows[0]["log"].startswith(str(TMP / "runs")))
check("report proposes raise", js("metrics.py", "report")["proposals"] >= 1)
check("apply → v2", js("metrics.py", "apply")["version"] == 2)
check("table changed", js("route.py", "base", "code", 3)["effort"] == "medium")
js("metrics.py", "report")
check("old data ignored after change", "code:T3" not in (TMP / "data" / "history" / "report.md").read_text())
check("rollback → v3", js("metrics.py", "rollback")["version"] == 3)
check("route restored", js("route.py", "base", "code", 3)["effort"] == "low")

print(f"\n{'ALL PASSED' if not FAILS else f'{len(FAILS)} FAILED'}  (temp: {TMP})")
sys.exit(1 if FAILS else 0)
