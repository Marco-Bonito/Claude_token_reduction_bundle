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
        tasks.append({"id": f"C{i}", "parent": "H1", "title": "c", "goal": "g", "acceptance": "a", "category": "code", "tier": 3, "score": "S1 C1 R1 V1 = 4", "deps": [], "status": "done", "attempts": atts})
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

# ---- community: export → validate → aggregate → sync
import shutil  # noqa: E402
C = ROOT / "community"
out = run("community.py", "export")
exp = TMP / "data" / "history" / "community-export.json"
check("export written", exp.exists(), out)
doc = json.loads(exp.read_text())
check("export has no private fields", "C0" not in exp.read_text() and "logs/" not in exp.read_text() and "run0" not in exp.read_text())
check("export cell counts", doc["cells"]["code:3"]["tasks"] == 9 and doc["cells"]["code:3"]["first_pass"] == 3, doc["cells"].get("code:3"))
check("export score buckets", doc["scores"].get("code:3:S1 C1 R1 V1", {}).get("tasks") == 9, list(doc["scores"]))


def validate(*args):
    p = subprocess.run([sys.executable, str(C / "validate.py"), *map(str, args)], capture_output=True, text=True, env=ENV)
    return p.returncode, p.stdout.strip()


check("export validates", validate(exp)[0] == 0, validate(exp))
check("issue body validates", validate("--issue-body", TMP / "data" / "history" / "community-issue.md")[0] == 0)
bad_cases = {
    "extra key": {**doc, "title": "x"},
    "bad route": {**doc, "cells": {"code:3": {**doc["cells"]["code:3"], "win_routes": {"$(rm -rf /)/low": 1}}}},
    "bad cell": {**doc, "cells": {"code:9": doc["cells"]["code:3"]}},
    "first_pass > tasks": {**doc, "cells": {"code:3": {**doc["cells"]["code:3"], "first_pass": 99}}},
    "bad contributor": {**doc, "contributor": "me"},
}
for name, bad in bad_cases.items():
    f = TMP / "bad.json"
    f.write_text(json.dumps(bad))
    check(f"rejects {name}", validate(f)[0] == 1)
subs = TMP / "subs"
for k in range(3):
    d = {**doc, "contributor": f"0000000{k}-0000-4000-8000-000000000000"}
    f = TMP / f"s{k}.json"
    f.write_text(json.dumps(d))
    validate(f, "--write", subs)
validate(TMP / "s0.json", "--write", subs)  # same contributor again → replaces, not adds
check("one file per contributor", len(list(subs.glob("*.json"))) == 3)
deftable = TMP / "defaults"
shutil.copytree(R / "defaults", deftable)
cfg = json.loads((deftable / "routing-table.json").read_text())
cfg["community"]["min_tasks"] = 20
(deftable / "routing-table.json").write_text(json.dumps(cfg))
p = subprocess.run([sys.executable, str(C / "aggregate.py"), "--submissions", subs, "--table", deftable / "routing-table.json",
                    "--out", TMP / "agg", "--apply"], capture_output=True, text=True, env=ENV)
res = json.loads(p.stdout.strip().splitlines()[-1]) if p.returncode == 0 else {}
check("aggregate runs", p.returncode == 0, p.stderr[-300:])
check("aggregate proposes code:3 raise", res.get("proposals") == 1 and res.get("defaults_version") == 2, res)
agg = json.loads((TMP / "agg" / "aggregate.json").read_text())
check("contributor cap applied", agg["cells"][0]["tasks"] == 27.0, agg["cells"][0])
comp = {r["component"]: r for r in agg["rubric_components"]}
check("rubric drift found", comp.get("C=1", {}).get("avg_drift", 0) > 0, comp.get("C=1"))
newdef = json.loads((deftable / "routing-table.json").read_text())
check("defaults updated", newdef["categories"]["code"]["tiers"][2] == 4)
ENV["TOKEN_ROUTING_DEFAULTS"] = str(deftable)
js("route.py", "base", "code", 3)  # still seeded table
s1 = js("community.py", "sync-defaults")
check("sync adopts community default", s1.get("synced", 0) >= 1 and js("route.py", "base", "code", 3)["effort"] == "medium", s1)
check("sync is idempotent", js("community.py", "sync-defaults").get("synced") == 0)
tbl_path = TMP / "data" / "routing-table.json"
tbl = json.loads(tbl_path.read_text())
tbl.setdefault("improver_state", {}).setdefault("cell_version", {})["debug:4"] = 99
tbl["categories"]["debug"]["tiers"][3] = 7
tbl_path.write_text(json.dumps(tbl))
newdef["categories"]["debug"]["tiers"][3] = 5
newdef["defaults_version"] = 3
(deftable / "routing-table.json").write_text(json.dumps(newdef))
js("community.py", "sync-defaults")
check("sync keeps locally tuned cells", js("route.py", "base", "debug", 4)["model"] == "opus")

# ---- personal version
p = subprocess.run([sys.executable, str(R / "community.py"), "submit-personal"], capture_output=True, text=True, env=ENV, cwd=TMP)
pe = TMP / "data" / "history" / "personal-export.json"
check("personal export written without repo", p.returncode == 0 and pe.exists(), p.stdout + p.stderr)
pdoc = json.loads(pe.read_text())
check("personal export has lessons", pdoc["schema"] == "token-routing-personal/1" and len(pdoc["lessons"]) >= 1)
core = {k: v for k, v in pdoc.items() if k not in ("lessons", "project")}
core["schema"] = "token-routing-feedback/1"
f = TMP / "core.json"
f.write_text(json.dumps(core))
check("personal core passes strict schema", validate(f)[0] == 0)
p = subprocess.run([sys.executable, str(R / "community.py"), "submit-personal", "--repo", "marco-bonito/claude_token_reduction_bundle"],
                   capture_output=True, text=True, env=ENV, cwd=TMP)
check("refuses public repo as personal target", p.returncode != 0 and "Refused" in (p.stdout + p.stderr))
(deftable / "lessons.md").write_text((deftable / "lessons.md").read_text() + "- [code] Run the linter before goal_met.\n")
s2 = js("community.py", "sync-defaults")
check("sync adds new lessons", s2.get("lessons_added") == 1 and "Run the linter" in (TMP / "data" / "lessons.md").read_text(), s2)
check("lessons sync idempotent", js("community.py", "sync-defaults").get("lessons_added") == 0)

print(f"\n{'ALL PASSED' if not FAILS else f'{len(FAILS)} FAILED'}  (temp: {TMP})")
sys.exit(1 if FAILS else 0)
