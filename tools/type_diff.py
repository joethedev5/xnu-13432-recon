#!/usr/bin/env python3
"""Diff DWARF struct/union/enum definitions against public xnu source."""
import argparse
import json
import os
import sqlite3
from collections import defaultdict

MARKER = "/Sources/xnu/"


def relpath(path):
    if not path:
        return None
    if MARKER in path:
        return path.split(MARKER, 1)[1]
    if path.startswith("EXTERNAL_HEADERS/"):
        return path
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="analysis/xnu-13432.dwarf.db")
    ap.add_argument("--public-types", default="analysis/public-types.json")
    ap.add_argument("--json", default="analysis/type-diff.json")
    ap.add_argument("--md", default="analysis/TYPE-DIFF.md")
    args = ap.parse_args()
    db = sqlite3.connect(args.db)
    pub = json.load(open(args.public_types))

    by_file = defaultdict(list)
    by_name = defaultdict(list)
    for t in pub:
        by_file[(t["kind"], t["name"], t["file"])].append(t)
        by_name[(t["kind"], t["name"])].append(t)

    sf = {}
    for cu, idx, path in db.execute("SELECT cu_id,idx,path FROM source_file"):
        sf[(cu, idx)] = path

    seen = set()
    rows = []
    for (tid, cu, tag, name, size, decl_file, decl_line) in db.execute(
            "SELECT id,cu_id,tag,name,byte_size,decl_file,decl_line FROM type "
            "WHERE tag IN ('DW_TAG_structure_type','DW_TAG_union_type','DW_TAG_enumeration_type') "
            "AND name IS NOT NULL AND decl_file IS NOT NULL"):
        rel = relpath(sf.get((cu, decl_file)))
        if not rel:
            continue
        kind = {"DW_TAG_structure_type": "struct", "DW_TAG_union_type": "union",
                "DW_TAG_enumeration_type": "enum"}[tag]
        if kind == "enum":
            items = tuple(x[0] for x in db.execute(
                "SELECT name FROM enumerator WHERE type_id=? ORDER BY value", (tid,)))
        else:
            items = tuple(x[0] for x in db.execute(
                "SELECT name FROM member WHERE type_id=? ORDER BY ordinal", (tid,)))
        key = (kind, name, rel, size, items)
        if key in seen:
            continue
        seen.add(key)
        rows.append({"kind": kind, "name": name, "file": rel, "size": size,
                     "line": decl_line, "items": items})

    out = {"new": [], "changed": [], "moved": [], "same": 0}
    for r in rows:
        cands = by_file.get((r["kind"], r["name"], r["file"]))
        if not cands:
            others = by_name.get((r["kind"], r["name"]))
            if others:
                r["public_files"] = sorted({c["file"] for c in others})
                out["moved"].append(r)
            else:
                out["new"].append(r)
            continue
        # choose the candidate with the smallest symmetric difference
        best = None
        for c in cands:
            if r["kind"] == "enum":
                pitems = tuple(e["name"] for e in c.get("enumerators", []))
            else:
                pitems = tuple(f["name"] for f in c.get("fields", []))
            diff = len(set(r["items"]) ^ set(pitems)) + abs(len(r["items"]) - len(pitems))
            if best is None or diff < best[0]:
                best = (diff, pitems, c)
        diff, pitems, c = best
        if diff == 0:
            out["same"] += 1
        else:
            r["public_line"] = c["line"]
            r["public_items"] = list(pitems)
            r["removed"] = [x for x in pitems if x not in r["items"]]
            r["added"] = [x for x in r["items"] if x not in pitems]
            out["changed"].append(r)

    with open(args.json, "w") as f:
        json.dump(out, f, indent=1)

    lines = ["# xnu-13432 type diff vs public xnu-12377.121.6\n",
             "Struct/union/enum definitions compared by name and member sequence.\n",
             "- unchanged: %d" % out["same"],
             "- new (name absent from public): %d" % len(out["new"]),
             "- changed member sequence: %d" % len(out["changed"]),
             "- moved to a different file: %d\n" % len(out["moved"]),
             "## Changed types\n",
             "| file | type | 13432 members | public members | added | removed |",
             "|---|---|---|---|---|---|"]
    for r in sorted(out["changed"], key=lambda x: (-(len(x["added"]) + len(x["removed"])), x["file"]))[:120]:
        lines.append("| %s | %s %s | %d | %d | %s | %s |" %
                     (r["file"], r["kind"], r["name"], len(r["items"]),
                      len(r["public_items"]), ", ".join(r["added"][:8]) or "-",
                      ", ".join(r["removed"][:8]) or "-"))
    lines.append("\n## New types (public name absent)\n")
    for r in sorted(out["new"], key=lambda x: (x["file"], x["name"]))[:200]:
        lines.append("- `%s %s` in `%s` (size %s)" % (r["kind"], r["name"], r["file"], r["size"]))
    lines.append("\n## Types moved between files\n")
    for r in sorted(out["moved"], key=lambda x: (x["name"], x["file"]))[:120]:
        lines.append("- `%s %s`: 13432 `%s`; public `%s`" %
                     (r["kind"], r["name"], r["file"], ", ".join(r["public_files"])))
    with open(args.md, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("types compared", len(rows), "same", out["same"], "new", len(out["new"]),
          "changed", len(out["changed"]), "moved", len(out["moved"]))
    print("wrote", args.md)


if __name__ == "__main__":
    main()
