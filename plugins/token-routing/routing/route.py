#!/usr/bin/env python3
"""Deterministic model/effort router. No model tokens are spent on the decision.

Usage:
  route.py base <category> <tier>
  route.py escalate <category> <model> <effort> <fail_type> <attempt_done>
  route.py reviewer <tier>
  route.py table                      # print the full first-route matrix

Output: one JSON line, e.g. {"action":"run","model":"sonnet","effort":"low","ladder_index":3}
action is one of: run | retry_same | ask_user | blocked
"""
import json
import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _paths import data_dir  # noqa: E402

TABLE = data_dir() / "routing-table.json"


def load():
    return json.loads(TABLE.read_text(encoding="utf-8"))


def out(obj):
    print(json.dumps(obj))
    sys.exit(0)


def fail(msg):
    print(json.dumps({"action": "error", "error": msg}))
    sys.exit(1)


def get_cat(t, category):
    cat = t["categories"].get(category)
    if not cat:
        fail(f"unknown category '{category}'. Known: {', '.join(t['categories'])}")
    return cat


def find_index(ladder, model, effort):
    for i, step in enumerate(ladder):
        if step["model"] == model and step["effort"] == effort:
            return i
    fail(f"route {model}/{effort} is not on the ladder")


def model_order(ladder):
    seen = []
    for s in ladder:
        if s["model"] not in seen:
            seen.append(s["model"])
    return seen


def step_effort(ladder, cur):
    """Next entry with the same model and higher effort. If none, step the model."""
    if cur + 1 < len(ladder) and ladder[cur + 1]["model"] == ladder[cur]["model"]:
        return cur + 1
    return step_model(ladder, cur)


def step_model(ladder, cur):
    """First entry of the next model. Keep the current effort if that model has it."""
    order = model_order(ladder)
    m = ladder[cur]["model"]
    pos = order.index(m)
    if pos + 1 >= len(order):
        return None
    nxt = order[pos + 1]
    candidates = [i for i, s in enumerate(ladder) if s["model"] == nxt]
    for i in candidates:
        if ladder[i]["effort"] == ladder[cur]["effort"]:
            return i
    return candidates[0]


def route(ladder, i, **extra):
    return {"action": "run", "model": ladder[i]["model"], "effort": ladder[i]["effort"], "ladder_index": i, **extra}


def main(argv):
    if len(argv) < 2:
        fail(__doc__)
    t = load()
    ladder = t["ladder"]
    cmd = argv[1]

    if cmd == "base":
        if len(argv) != 4:
            fail("usage: route.py base <category> <tier>")
        cat = get_cat(t, argv[2])
        tier = int(argv[3])
        if not 1 <= tier <= 5:
            fail("tier must be 1..5")
        out(route(ladder, cat["tiers"][tier - 1]))

    if cmd == "escalate":
        if len(argv) != 7:
            fail("usage: route.py escalate <category> <model> <effort> <fail_type> <attempt_done>")
        cat = get_cat(t, argv[2])
        cur = find_index(ladder, argv[3], argv[4])
        fail_type = argv[5] if argv[5] in t["retry"]["fail_types"] else t["retry"]["default_fail_type"]
        attempt_done = int(argv[6])
        max_attempts = 1 + t["retry"]["max_retries"]
        step = t["retry"]["fail_types"][fail_type]["step"]

        if step == "stop":
            out({"action": "ask_user", "reason": "spec", "fail_type": fail_type})
        if attempt_done >= max_attempts:
            out({"action": "blocked", "reason": f"max attempts ({max_attempts}) reached", "fail_type": fail_type})
        if step == "same":
            out({**route(ladder, cur), "action": "retry_same", "fail_type": fail_type})

        nxt = step_effort(ladder, cur) if step == "effort" else step_model(ladder, cur)
        if nxt is None or nxt > cat["ceiling"]:
            out({"action": "blocked", "reason": "category ceiling reached", "fail_type": fail_type})
        out(route(ladder, nxt, fail_type=fail_type, attempt_next=attempt_done + 1))

    if cmd == "reviewer":
        tier = int(argv[2]) if len(argv) > 2 else 3
        r = t["reviewer"]
        pick = r["upgrade_for_tier_5"] if tier >= 5 else r
        out({"action": "run", "model": pick["model"], "effort": pick["effort"]})

    if cmd == "table":
        rows = []
        for name, cat in t["categories"].items():
            cells = [f"{ladder[i]['model']}/{ladder[i]['effort']}" for i in cat["tiers"]]
            rows.append(f"{name:<13} " + " | ".join(f"{c:<14}" for c in cells))
        print("category      " + " | ".join(f"tier {n:<9}" for n in range(1, 6)))
        print("\n".join(rows))
        sys.exit(0)

    fail(f"unknown command '{cmd}'")


if __name__ == "__main__":
    main(sys.argv)
