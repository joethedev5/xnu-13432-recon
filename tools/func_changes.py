#!/usr/bin/env python3
"""Rank xnu-13432 source changes using DWARF line spans and line deltas."""
import argparse
import json
import os
import sqlite3
import statistics
from collections import Counter, defaultdict

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
    ap.add_argument("--dwarf", default="analysis/xnu-13432.dwarf.db")
    ap.add_argument("--public", default="analysis/public-funcs.db")
    ap.add_argument("--json", default="analysis/func-changes.json")
    ap.add_argument("--md", default="analysis/FUNCTION-CHANGES.md")
    args = ap.parse_args()
    dw = sqlite3.connect(args.dwarf)
    pub = sqlite3.connect(args.public)

    sf = {}
    for cu, idx, path in dw.execute("SELECT cu_id,idx,path FROM source_file"):
        sf[(cu, idx)] = path
    file_idx = defaultdict(lambda: defaultdict(set))  # cu -> rel -> {idx}
    for (cu, idx), path in sf.items():
        r = relpath(path)
        if r:
            file_idx[cu][r].add(idx)

    pub_rows = defaultdict(list)
    pub_by_file = defaultdict(list)
    for name, file, line, end in pub.execute("SELECT name,file,line,end_line FROM func"):
        pub_rows[(name, file)].append((line, end))
        pub_by_file[file].append((name, line, end))

    funcs = []
    for (fid, cu, name, link, decl_file, decl_line, low, high) in dw.execute(
            "SELECT id,cu_id,name,linkage_name,decl_file,decl_line,low_pc,high_pc "
            "FROM func WHERE decl_file IS NOT NULL AND declaration=0"):
        label = name or (link.lstrip("_") if link else None)
        if not label:
            continue
        rel = relpath(sf.get((cu, decl_file)))
        if not rel or rel not in pub_by_file:
            continue
        cands = pub_rows.get((label, rel))
        if not cands:
            continue
        pline, pend = min(cands, key=lambda x: abs(x[0] - decl_line))
        if low is None or high is None or high <= low:
            continue
        idxs = file_idx[cu].get(rel, set())
        if not idxs:
            continue
        q = ",".join("?" * len(idxs))
        row = dw.execute(
            "SELECT min(line),max(line),count(*) FROM line WHERE cu_id=? AND addr>=? AND addr<? "
            "AND file_idx IN (%s) AND line>0 AND end_sequence=0" % q,
            [cu, low, high] + list(idxs)).fetchone()
        if not row or row[2] == 0:
            continue
        dmin, dmax, _ = row
        dspan = dmax - dmin + 1
        pspan = pend - pline + 1
        funcs.append({"name": label, "file": rel, "dwarf_line": decl_line,
                      "public_line": pline, "delta": decl_line - pline,
                      "dwarf_span": dspan, "public_span": pspan,
                      "span_delta": dspan - pspan, "low": low, "high": high,
                      "dwarf_min_line": dmin, "dwarf_max_line": dmax})

    byfile = defaultdict(list)
    for f in funcs:
        byfile[f["file"]].append(f)
    out = {}
    total_changed = total_new = 0
    for rel, fs in byfile.items():
        fs.sort(key=lambda x: x["dwarf_line"])
        deltas = [x["delta"] for x in fs]
        med = statistics.median(deltas) if deltas else 0
        for f in fs:
            f["delta_vs_median"] = f["delta"] - med
        changed = [f for f in fs if abs(f["span_delta"]) >= max(8, 0.15 * f["public_span"])]
        # gaps between consecutive functions: added code between them
        gaps = []
        for a, b in zip(fs, fs[1:]):
            dgap = b["dwarf_line"] - a["dwarf_line"]
            pgap = b["public_line"] - a["public_line"]
            if dgap - pgap > 8:
                gaps.append({"after": a["name"], "before": b["name"],
                             "added_lines": dgap - pgap})
        pub_names = {n for n, _, _ in pub_by_file.get(rel, [])}
        dnames = {f["name"] for f in fs}
        missing_names = {n for n, _, _ in pub_by_file.get(rel, [])} - dnames
        new = [f for f in fs if f["name"] not in pub_names]
        total_changed += len(changed)
        total_new += len(new)
        out[rel] = {"median_delta": med, "functions": len(fs),
                    "changed": changed, "new": new, "gaps": gaps,
                    "missing_count": len(missing_names)}

    with open(args.json, "w") as f:
        json.dump(out, f, indent=1)

    ranked = sorted(out.items(), key=lambda kv: -(len(kv[1]["changed"]) * 3 +
                                                len(kv[1]["gaps"]) + len(kv[1]["new"])))
    lines = ["# xnu-13432 function change analysis\n",
             "DWARF line-table spans compared with public xnu-12377.121.6 source spans.\n",
             "Changed functions: %d; new functions in compared files: %d.\n" %
             (total_changed, total_new),
             "## Ranked files\n",
             "| file | funcs | changed spans | new | insertion gaps | median line delta |",
             "|---|---|---|---|---|---|"]
    for rel, d in ranked[:80]:
        lines.append("| %s | %d | %d | %d | %d | %s |" %
                     (rel, d["functions"], len(d["changed"]), len(d["new"]),
                      len(d["gaps"]), d["median_delta"]))
    lines.append("\n## Largest function-span changes\n")
    allch = []
    for rel, d in out.items():
        for f in d["changed"]:
            allch.append((abs(f["span_delta"]), rel, f))
    allch.sort(reverse=True)
    lines.append("| file | function | dwarf span | public span | delta | dwarf line | public line |")
    lines.append("|---|---|---|---|---|---|---|")
    for _, rel, f in allch[:120]:
        lines.append("| %s | %s | %d | %d | %+d | %d | %d |" %
                     (rel, f["name"], f["dwarf_span"], f["public_span"],
                      f["span_delta"], f["dwarf_line"], f["public_line"]))
    with open(args.md, "w") as f:
        f.write("\n".join(lines) + "\n")
    print("functions compared", len(funcs), "changed", total_changed, "new", total_new)
    print("wrote", args.md)


if __name__ == "__main__":
    main()
