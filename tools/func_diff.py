#!/usr/bin/env python3
"""Diff DWARF function definitions against tree-sitter-indexed public source."""
import argparse
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict

MARKER = "/Sources/xnu/"
IGNORE_RE = re.compile(r"^(_GLOBAL__|__cxx_global|__static_initialization|\.|_?__)")
SUFFIX_RE = re.compile(r"\.(cold|part\.\d+|constprop\.\d+|isra\.\d+|llvm\.\d+|lto_priv\.\d+)$")


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
    ap.add_argument("--dwarf", default="analysis/xnu-13432.dwarf.db")
    ap.add_argument("--public", default="analysis/public-funcs.db")
    ap.add_argument("--out", default="analysis/func-diff.json")
    ap.add_argument("--md", default="analysis/FUNCTION-DIFF.md")
    args = ap.parse_args()
    dw = sqlite3.connect(args.dwarf)
    pub = sqlite3.connect(args.public)

    sf = {}
    for cu, idx, path in dw.execute("SELECT cu_id,idx,path FROM source_file"):
        sf[(cu, idx)] = path

    pub_rows = defaultdict(list)       # (name,file) -> [(line,end)]
    pub_files_for_name = defaultdict(set)
    pub_by_file = defaultdict(list)    # file -> [(name,line,end)]
    for name, file, line, end in pub.execute("SELECT name,file,line,end_line FROM func"):
        pub_rows[(name, file)].append((line, end))
        pub_files_for_name[name].add(file)
        pub_by_file[file].append((name, line, end))

    cuset = set()
    for (cu, idx), path in sf.items():
        r = relpath(path)
        if r and r.endswith((".c", ".cpp", ".m", ".mm")):
            cuset.add(r)

    defs = []
    seen = set()
    for (fid, cu, name, link, decl_file, decl_line, low, high, inline) in dw.execute(
            "SELECT id,cu_id,name,linkage_name,decl_file,decl_line,low_pc,high_pc,inline "
            "FROM func WHERE decl_file IS NOT NULL AND declaration=0"):
        label = name or (link.lstrip("_") if link else None)
        if label:
            label = SUFFIX_RE.sub("", label)
        if not label:
            continue
        path = sf.get((cu, decl_file))
        rel = relpath(path)
        if not rel:
            continue
        key = (label, rel, decl_line)
        if key in seen:
            continue
        seen.add(key)
        defs.append({"name": label, "file": rel, "line": decl_line,
                     "low": low, "high": high, "inline": inline})

    files = defaultdict(lambda: {"new": [], "shifted": [], "moved": [],
                                 "missing": [], "matched": 0})
    totals = Counter()
    by_name_dwarf = defaultdict(set)
    for d in defs:
        by_name_dwarf[d["name"]].add(d["file"])
        f = files[d["file"]]
        same = pub_rows.get((d["name"], d["file"]))
        if same:
            pline = min(same, key=lambda x: abs(x[0] - d["line"]))[0]
            if pline == d["line"]:
                f["matched"] += 1
                totals["matched"] += 1
            else:
                f["shifted"].append({"name": d["name"], "line": d["line"],
                                     "public_line": pline, "delta": d["line"] - pline})
                totals["shifted"] += 1
        elif pub_files_for_name.get(d["name"]):
            f["moved"].append({"name": d["name"], "line": d["line"],
                               "public_files": sorted(pub_files_for_name[d["name"]])})
            totals["moved"] += 1
        else:
            f["new"].append({"name": d["name"], "line": d["line"],
                             "low": d["low"], "high": d["high"]})
            totals["new"] += 1

    for rel in sorted(cuset):
        if rel not in pub_by_file:
            continue
        known = {d["name"] for d in defs if d["file"] == rel}
        for name, line, end in pub_by_file[rel]:
            if name in known:
                continue
            files[rel]["missing"].append({"name": name, "line": line, "end": end})
            totals["missing"] += 1

    ordered = sorted(files.items(),
                     key=lambda kv: (-(len(kv[1]["new"]) + len(kv[1]["shifted"]) + len(kv[1]["missing"])), kv[0]))
    out = {"summary": dict(totals), "files": dict(ordered)}
    with open(args.out, "w") as f:
        json.dump(out, f, indent=1)

    new_files = [rel for rel in cuset if rel not in pub_by_file and rel.endswith(".c")]
    lines = ["# xnu-13432 vs public xnu-12377.121.6: function diff\n"]
    lines.append("DWARF definitions compared: %d; matched %d, shifted %d, moved %d, new %d; "
                 "public functions absent from DWARF in compiled files: %d\n" %
                 (len(defs), totals["matched"], totals["shifted"], totals["moved"],
                  totals["new"], totals["missing"]))
    lines.append("## Most changed compiled files\n")
    lines.append("| file | new | shifted | moved | missing | matched |")
    lines.append("|---|---|---|---|---|---|")
    for rel, f in ordered[:60]:
        if not (f["new"] or f["shifted"] or f["moved"] or f["missing"]):
            continue
        lines.append("| %s | %d | %d | %d | %d | %d |" %
                     (rel, len(f["new"]), len(f["shifted"]), len(f["moved"]),
                      len(f["missing"]), f["matched"]))
    lines.append("\n## New source files (DWARF CU, absent from public tree)\n")
    for rel in sorted(new_files):
        f = files.get(rel)
        if f and f["new"]:
            lines.append("- `%s` — %d functions: %s" %
                         (rel, len(f["new"]), ", ".join(x["name"] for x in f["new"][:12])))
    lines.append("\n## New functions in existing files\n")
    for rel, f in ordered:
        if rel in new_files or not f["new"]:
            continue
        lines.append("- `%s`: %s" % (rel, ", ".join(x["name"] for x in f["new"][:20])))
    lines.append("\n## Public functions with no 13432 DWARF definition (compiled .c files)\n")
    for rel, f in ordered:
        if not f["missing"]:
            continue
        lines.append("- `%s`: %s" % (rel, ", ".join(x["name"] for x in f["missing"][:20])))
    with open(args.md, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("wrote", args.out, args.md)
    print(dict(totals))
    print("new files:", len(new_files))


if __name__ == "__main__":
    main()
