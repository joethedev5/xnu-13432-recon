#!/usr/bin/env python3
"""Extract per-compile-unit build commands from DWARF DW_AT_APPLE_flags."""
import argparse
import json

from elftools.elf.elffile import ELFFile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("elf")
    ap.add_argument("out", nargs="?", default="analysis/build-flags.json")
    args = ap.parse_args()
    d = ELFFile(open(args.elf, "rb")).get_dwarf_info()
    out = []
    for cu in d.iter_CUs():
        top = cu.get_top_DIE()

        def s(k):
            a = top.attributes.get(k)
            if a is None:
                return None
            v = a.value
            return v.decode("utf-8", "replace") if isinstance(v, bytes) else v
        name = s("DW_AT_name")
        flags = s("DW_AT_APPLE_flags")
        rel = name.split("/Sources/xnu/", 1)[1] if name and "/Sources/xnu/" in name else None
        out.append({"cu_offset": cu.cu_offset, "source": name, "rel": rel,
                    "comp_dir": s("DW_AT_comp_dir"), "sdk": s("DW_AT_APPLE_sdk"),
                    "producer": s("DW_AT_producer"), "flags": flags})
    with open(args.out, "w") as f:
        json.dump(out, f, indent=1)
    n = sum(1 for x in out if x["flags"])
    print("wrote", args.out, "CUs", len(out), "with flags", n)


if __name__ == "__main__":
    main()
