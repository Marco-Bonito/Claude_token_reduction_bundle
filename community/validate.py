#!/usr/bin/env python3
"""Strict validation of one community feedback submission. Standard library only.

Usage:
  validate.py <file.json>                  # validate a JSON file
  validate.py --issue-body <file.md>       # extract the ```json block from an issue body, validate it
  Add --write <dir> to save the valid submission as <dir>/<contributor>.json (latest replaces older).

Exit 0 = valid. Exit 1 = invalid (reason on stdout). Untrusted input: nothing is executed or evaluated.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

MAX_CHARS = 60000
SCHEMA = "token-routing-feedback/1"
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ROUTE_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]{0,39}/(low|medium|high|xhigh|max)$")
CAT_RE = re.compile(r"^[a-z][a-z0-9_\-]{0,29}$")
CELL_RE = re.compile(r"^([a-z][a-z0-9_\-]{0,29}):([1-5])$")
SCORE_KEY_RE = re.compile(r"^([a-z][a-z0-9_\-]{0,29}):([1-5]):S[0-2] C[0-2] R[0-2] V[0-2]$")
FAIL_TYPES = {"depth", "capability", "review", "environment", "spec"}
TOP_KEYS = {"schema", "contributor", "plugin_version", "table_version", "defaults_version", "cells", "scores"}
CELL_KEYS = {"tasks", "first_pass", "solved", "first_routes", "win_routes", "fail_types", "avg_tokens"}
SCORE_KEYS = {"tasks", "first_pass", "win_routes"}
MAX_N = 1_000_000


class Invalid(Exception):
    pass


def req(cond, msg):
    if not cond:
        raise Invalid(msg)


def count(v, name):
    req(isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= MAX_N, f"{name}: must be an integer 0..{MAX_N}")
    return v


def route_counts(d, name, limit):
    req(isinstance(d, dict) and len(d) <= 30, f"{name}: must be an object with max 30 routes")
    total = 0
    for k, v in d.items():
        req(isinstance(k, str) and ROUTE_RE.match(k), f"{name}: bad route '{str(k)[:40]}'")
        total += count(v, f"{name}.{k}")
    req(total <= limit, f"{name}: total {total} > tasks {limit}")


def validate(doc):
    req(isinstance(doc, dict), "top level must be an object")
    req(set(doc) == TOP_KEYS, f"keys must be exactly {sorted(TOP_KEYS)}")
    req(doc["schema"] == SCHEMA, f"schema must be {SCHEMA}")
    req(isinstance(doc["contributor"], str) and UUID_RE.match(doc["contributor"]), "contributor must be a UUID")
    req(isinstance(doc["plugin_version"], str) and len(doc["plugin_version"]) <= 20, "bad plugin_version")
    count(doc["table_version"], "table_version")
    count(doc["defaults_version"], "defaults_version")
    cells, scores = doc["cells"], doc["scores"]
    req(isinstance(cells, dict) and 0 < len(cells) <= 200, "cells: 1..200 entries")
    for key, c in cells.items():
        req(isinstance(key, str) and CELL_RE.match(key), f"bad cell key '{str(key)[:40]}'")
        req(isinstance(c, dict) and set(c) == CELL_KEYS, f"{key}: keys must be exactly {sorted(CELL_KEYS)}")
        n = count(c["tasks"], f"{key}.tasks")
        req(n > 0, f"{key}.tasks must be > 0")
        req(count(c["first_pass"], f"{key}.first_pass") <= n, f"{key}.first_pass > tasks")
        req(count(c["solved"], f"{key}.solved") <= n, f"{key}.solved > tasks")
        req(c["first_pass"] <= c["solved"], f"{key}.first_pass > solved")
        route_counts(c["first_routes"], f"{key}.first_routes", n)
        route_counts(c["win_routes"], f"{key}.win_routes", c["solved"])
        req(isinstance(c["fail_types"], dict) and set(c["fail_types"]) <= FAIL_TYPES, f"{key}.fail_types: unknown type")
        for k, v in c["fail_types"].items():
            count(v, f"{key}.fail_types.{k}")
        req(c["avg_tokens"] is None or (isinstance(c["avg_tokens"], int) and 0 <= c["avg_tokens"] <= 50_000_000),
            f"{key}.avg_tokens: null or 0..50M")
    req(isinstance(scores, dict) and len(scores) <= 4000, "scores: max 4000 entries")
    for key, s in scores.items():
        req(isinstance(key, str) and SCORE_KEY_RE.match(key), f"bad score key '{str(key)[:60]}'")
        req(isinstance(s, dict) and set(s) == SCORE_KEYS, f"{key}: keys must be exactly {sorted(SCORE_KEYS)}")
        n = count(s["tasks"], f"{key}.tasks")
        req(count(s["first_pass"], f"{key}.first_pass") <= n, f"{key}.first_pass > tasks")
        route_counts(s["win_routes"], f"{key}.win_routes", n)
    return doc


def extract_json_block(body):
    m = re.search(r"```(?:json)?\s*\n(.*?)\n```", body, re.S)
    req(m, "no ```json block found in the issue body")
    return m.group(1)


def main(argv):
    args = argv[1:]
    write_dir = None
    if "--write" in args:
        i = args.index("--write")
        write_dir = Path(args[i + 1])
        del args[i:i + 2]
    try:
        if args and args[0] == "--issue-body":
            text = extract_json_block(Path(args[1]).read_text(encoding="utf-8"))
        else:
            text = Path(args[0]).read_text(encoding="utf-8")
        req(len(text) <= MAX_CHARS, f"too large: {len(text)} > {MAX_CHARS} chars")
        try:
            doc = json.loads(text)
        except json.JSONDecodeError as e:
            raise Invalid(f"not valid JSON: {e.msg} at line {e.lineno}")
        validate(doc)
    except Invalid as e:
        print(f"INVALID: {e}")
        return 1
    tasks = sum(c["tasks"] for c in doc["cells"].values())
    if write_dir:
        write_dir.mkdir(parents=True, exist_ok=True)
        stored = {"received": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "data": doc}
        (write_dir / f"{doc['contributor']}.json").write_text(json.dumps(stored, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"VALID: contributor {doc['contributor'][:8]}…, {len(doc['cells'])} cells, {tasks} tasks")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
