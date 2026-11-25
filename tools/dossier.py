#!/usr/bin/env python3
"""Per-source-file DWARF dossiers for new xnu-13432 files."""
import argparse
import json
import os
import re
import sqlite3
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


class Types:
    def __init__(self, db):
        self.db = db
        self.cache = {}

    def row(self, off):
        if off in self.cache:
            return self.cache[off]
        r = self.db.execute("SELECT tag,name,byte_size,encoding,type_offset,array_count "
                            "FROM type WHERE die_offset=? LIMIT 1", (off,)).fetchone()
        self.cache[off] = r
        return r

    def desc(self, off, depth=0):
        if not off or depth > 12:
            return "void"
        r = self.row(off)
        if not r:
            return "void"
        tag, name, size, enc, toff, count = r
        if tag == "DW_TAG_typedef":
            return name or self.desc(toff, depth + 1)
        if tag == "DW_TAG_base_type":
            return name or "base%d" % (enc or 0)
        if tag == "DW_TAG_structure_type":
            return "struct " + (name or "<anon>")
        if tag == "DW_TAG_union_type":
            return "union " + (name or "<anon>")
        if tag == "DW_TAG_enumeration_type":
            return "enum " + (name or "<anon>")
        if tag == "DW_TAG_pointer_type":
            return self.desc(toff, depth + 1) + " *"
        if tag == "DW_TAG_const_type":
            return "const " + self.desc(toff, depth + 1)
        if tag == "DW_TAG_volatile_type":
            return "volatile " + self.desc(toff, depth + 1)
        if tag == "DW_TAG_restrict_type":
            return "restrict " + self.desc(toff, depth + 1)
        if tag == "DW_TAG_array_type":
            return self.desc(toff, depth + 1) + "[%s]" % (count if count is not None else "")
        if tag == "DW_TAG_subroutine_type":
            return "function"
        return name or tag.replace("DW_TAG_", "").lower()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="analysis/xnu-13432.dwarf.db")
    ap.add_argument("--public", default="/srv/sandboxes/deepsbx/work/xnu-12377.121.6")
    ap.add_argument("--outdir", default="analysis/dossiers")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    db = sqlite3.connect(args.db)
    types = Types(db)

    sf = {}
    cu_name = {}
    for cu, idx, path in db.execute("SELECT cu_id,idx,path FROM source_file"):
        sf[(cu, idx)] = path
    for cu, name in db.execute("SELECT id,name FROM cu"):
        cu_name[cu] = name

    cus_of_file = defaultdict(list)
    for cu, name in cu_name.items():
        r = relpath(name)
        if r:
            cus_of_file[r].append(cu)

    func_by_offset = {}
    for (off, name, link) in db.execute("SELECT die_offset,name,linkage_name FROM func"):
        func_by_offset[off] = name or (link.lstrip("_") if link else "?")

    all_cus = set(cus_of_file)
    public = set()
    for root, dirs, files in os.walk(args.public):
        dirs[:] = [d for d in dirs if d not in (".git", "build")]
        for f in files:
            if f.endswith((".c", ".cpp", ".m", ".mm")):
                public.add(os.path.relpath(os.path.join(root, f), args.public))
    new_files = sorted(p for p in all_cus if p not in public)
    index = ["# xnu-13432 new-file dossiers\n",
             "Files present in the 13432 VMAPPLE DWARF but absent from public xnu-12377.121.6:\n"]
    for rel in new_files:
        cus = cus_of_file[rel]
        q = ",".join("?" * len(cus))
        funcs = db.execute(
            "SELECT id,name,linkage_name,decl_line,low_pc,high_pc,inline FROM func "
            "WHERE cu_id IN (%s) AND declaration=0 ORDER BY decl_line" % q, cus).fetchall()
        # keep functions declared in this file (or all when the CU is tiny)
        own = []
        for fid, name, link, line, low, high, inline in funcs:
            label = name or (link.lstrip("_") if link else "?")
            own.append((fid, label, line, low, high, inline))
        params = defaultdict(list)
        own_ids = [x[0] for x in own]
        for fid, ordinal, name, toff in db.execute(
                "SELECT func_id,ordinal,name,type_offset FROM func_param WHERE func_id IN (%s)"
                " ORDER BY func_id,ordinal" % ",".join("?" * len(own)),
                [x[0] for x in own] or [0]):
            params[fid].append((name or "arg", types.desc(toff)))
        var_count = dict(db.execute(
            "SELECT func_id,count(*) FROM variable WHERE func_id IN (%s) GROUP BY func_id"
            % ",".join("?" * len(own)) if own else "SELECT 1,0 WHERE 0", own_ids).fetchall())
        calls = defaultdict(Counter)
        for fid, origin in db.execute(
                "SELECT func_id,call_origin FROM call_site WHERE func_id IN (%s)"
                % ",".join("?" * len(own)) if own else "SELECT 1,0 WHERE 0", own_ids):
            callee = func_by_offset.get(origin)
            if callee:
                calls[fid][callee] += 1
        trows = []
        for (tid, tag, name, size, decl_file, decl_line) in db.execute(
                "SELECT id,tag,name,byte_size,decl_file,decl_line FROM type "
                "WHERE cu_id IN (%s) AND decl_file IS NOT NULL AND decl_line IS NOT NULL"
                % q, cus):
            path = sf.get((cus[0], decl_file))
            if relpath(path) != rel:
                continue
            members = []
            if tag in ("DW_TAG_structure_type", "DW_TAG_union_type"):
                for m in db.execute(
                        "SELECT name,type_offset,byte_offset,bit_size FROM member WHERE type_id=? ORDER BY ordinal",
                        (tid,)):
                    members.append(m)
            enums = []
            if tag == "DW_TAG_enumeration_type":
                enums = db.execute("SELECT name,value FROM enumerator WHERE type_id=? ORDER BY value",
                                   (tid,)).fetchall()
            trows.append((tag, name, size, decl_line, members, enums))
        gvars = db.execute(
            "SELECT name,decl_line FROM variable WHERE cu_id IN (%s) AND func_id IS NULL "
            "AND decl_file IS NOT NULL" % q, cus).fetchall()

        lines = ["# `%s`\n" % rel,
                 "CU offset(s): %s" % ", ".join(hex(db.execute(
                     "SELECT cu_offset FROM cu WHERE id=?", (c,)).fetchone()[0]) for c in cus),
                 "Functions: %d; file-scope debug variables: %d\n" % (len(own), len(gvars)),
                 "## Functions\n"]
        for fid, label, line, low, high, inline in own:
            size = None
            if low is not None and high is not None:
                size = (high - low) & ((1 << 64) - 1)
            sig = ", ".join("%s %s" % (t, n) for n, t in params.get(fid, []))
            lines.append("### `%s`\n" % label)
            lines.append("- decl line %s%s; size %s bytes; %d locals; %s" %
                         (line, " (inline)" if inline else "",
                          size if size is not None else "?", var_count.get(fid, 0),
                          ("callees: " + ", ".join("%s×%d" % (k, v) for k, v in calls[fid].most_common(8)))
                          if calls.get(fid) else "no call sites recorded"))
            if sig:
                lines.append("- args: `%s`" % sig)
            lines.append("")
        if trows:
            lines.append("## Types defined here\n")
            for tag, name, size, line, members, enums in trows:
                kind = tag.replace("DW_TAG_", "").replace("_type", "")
                lines.append("- `%s %s` (line %s, size %s)" %
                             (kind, name or "<anon>", line, size if size is not None else "?"))
                for mname, mtoff, moff, mbits in members:
                    lines.append("  - `%s %s` @%s%s" %
                                 (types.desc(mtoff), mname, moff,
                                  (" bitfield %d" % mbits) if mbits else ""))
                for ename, eval_ in enums:
                    lines.append("  - `%s = %s`" % (ename, eval_))
            lines.append("")
        if gvars:
            lines.append("## File-scope variables\n")
            lines.append(", ".join("`%s`" % n for n, _ in gvars[:60]))
            lines.append("")
        path = os.path.join(args.outdir, rel.replace("/", "__") + ".md")
        with open(path, "w") as f:
            f.write("\n".join(lines) + "\n")
        index.append("- [`%s`](%s) — %d functions" % (rel, os.path.basename(path), len(own)))
    with open(os.path.join(args.outdir, "INDEX.md"), "w") as f:
        f.write("\n".join(index) + "\n")
    print("wrote %d dossiers" % len(new_files))


if __name__ == "__main__":
    main()
