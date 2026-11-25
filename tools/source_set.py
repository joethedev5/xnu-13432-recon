#!/usr/bin/env python3
"""Compare the DWARF compile-unit source set with the public xnu tree."""
import argparse
import json
import os
from collections import Counter, defaultdict

from elftools.elf.elffile import ELFFile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("elf")
    ap.add_argument("public_tree")
    ap.add_argument("--json", dest="json_out", default=None)
    args = ap.parse_args()
    dwarf = ELFFile(open(args.elf, "rb")).get_dwarf_info()

    cus = []
    seen = set()
    attrs = Counter()
    for cu in dwarf.iter_CUs():
        top = cu.get_top_DIE()
        name = top.attributes.get("DW_AT_name")
        name = name.value.decode("utf-8", "replace") if name else None
        comp_dir = top.attributes.get("DW_AT_comp_dir")
        comp_dir = comp_dir.value.decode("utf-8", "replace") if comp_dir else None
        prod = top.attributes.get("DW_AT_producer")
        prod = prod.value.decode("utf-8", "replace") if prod else None
        for k in top.attributes:
            attrs[k] += 1
        rel = None
        if name:
            marker = "/Sources/xnu/"
            rel = name.split(marker, 1)[1] if marker in name else None
        key = rel or name
        if key in seen:
            continue
        seen.add(key)
        cus.append({"cu_offset": cu.cu_offset, "name": name, "rel": rel,
                    "comp_dir": comp_dir, "producer": prod})

    public = set()
    for root, dirs, files in os.walk(args.public_tree):
        dirs[:] = [d for d in dirs if d not in (".git", "build")]
        for f in files:
            if f.endswith((".c", ".cpp", ".m", ".s", ".S")):
                public.add(os.path.relpath(os.path.join(root, f), args.public_tree))

    cuset = {c["rel"] for c in cus if c["rel"]}
    missing = sorted(cuset - public)
    extra = sorted(public - cuset)
    bydir = Counter(os.path.dirname(c["rel"] or "") for c in cus)
    print("DWARF CUs: %d unique, %d with /Sources/xnu path" % (len(cus), len(cuset)))
    print("public source files: %d" % len(public))
    print("in 13432 DWARF but not public tree: %d" % len(missing))
    for p in missing:
        print("  +", p)
    print("public but no 13432 CU: %d" % len(extra))
    for p in extra[:80]:
        print("  -", p)
    if len(extra) > 80:
        print("  ... %d more" % (len(extra) - 80))
    print("top CU directories:")
    for d, n in bydir.most_common(20):
        print("  %4d %s" % (n, d))
    print("CU attributes present:", ", ".join(sorted(attrs)))

    if args.json_out:
        with open(args.json_out, "w") as f:
            json.dump({"cus": cus, "missing_from_public": missing,
                       "public_without_cu": extra,
                       "by_dir": bydir}, f, indent=1)
        print("wrote", args.json_out)


if __name__ == "__main__":
    main()
