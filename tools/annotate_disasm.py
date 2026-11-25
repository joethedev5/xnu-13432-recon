#!/usr/bin/env python3
"""Annotate a kernel function's disassembly with DWARF lines, callees and locals."""
import argparse
import bisect
import json
import re
import sqlite3
import subprocess
import sys

sys.path.insert(0, __import__("os").path.dirname(__file__))
from macho import MachO

MARKER = "/Sources/xnu/"
INSN_RE = re.compile(r"^\s*([0-9a-f]+):\s+(.*)$")


def relpath(path):
    if not path:
        return None
    return path.split(MARKER, 1)[1] if MARKER in path else path


class FuncMap:
    def __init__(self, db):
        self.exact = {}
        self.iv = []
        for name, link, lo, hi in db.execute(
                "SELECT name,linkage_name,low_pc,high_pc FROM func "
                "WHERE low_pc IS NOT NULL AND high_pc IS NOT NULL AND high_pc>low_pc"):
            self.exact.setdefault(lo & ((1 << 64) - 1), name or link)
            self.iv.append((lo & ((1 << 64) - 1), hi & ((1 << 64) - 1), name or link))
        self.iv.sort()
        self.los = [x[0] for x in self.iv]

    def lookup(self, addr):
        if addr in self.exact:
            return self.exact[addr]
        i = bisect.bisect_right(self.los, addr) - 1
        best = None
        while i >= 0:
            lo, hi, name = self.iv[i]
            if hi > addr:
                if best is None or hi - lo < best[0]:
                    best = (hi - lo, name)
            if lo < addr - (1 << 26):
                break
            i -= 1
        return best[1] if best else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name_or_addr")
    ap.add_argument("--db", default="analysis/xnu-13432.dwarf.db")
    ap.add_argument("--kernel", default="kdk/root/System/Library/Kernels/kernel.release.vmapple")
    ap.add_argument("--objdump", default="llvm-objdump")
    args = ap.parse_args()
    db = sqlite3.connect(args.db)
    fmap = FuncMap(db)
    sf = {(c, i): p for c, i, p in db.execute("SELECT cu_id,idx,path FROM source_file")}
    if args.name_or_addr.startswith("0x"):
        target = int(args.name_or_addr, 16)
        row = db.execute("SELECT id,cu_id,name,decl_file,decl_line,low_pc,high_pc,type_offset FROM func "
                         "WHERE low_pc<=? AND high_pc>? ORDER BY (high_pc-low_pc) LIMIT 1",
                         (target, target)).fetchone()
    else:
        row = db.execute("SELECT id,cu_id,name,decl_file,decl_line,low_pc,high_pc,type_offset FROM func "
                         "WHERE name=? AND low_pc IS NOT NULL ORDER BY id LIMIT 1",
                         (args.name_or_addr,)).fetchone()
    if not row:
        sys.exit("function not found")
    fid, cu, name, df, dl, lo, hi, toff = row
    path = relpath(sf.get((cu, df)))
    print("# %s  %s:%s  [%#x, %#x) size=%d" % (name, path, dl, lo & ((1 << 64) - 1),
                                                hi & ((1 << 64) - 1), hi - lo))
    print("## locals")
    for vn, vt, vfile, vline, loc in db.execute(
            "SELECT name,type_offset,decl_file,decl_line,location FROM variable WHERE func_id=? ORDER BY decl_line", (fid,)):
        print("  %-30s line %-6s loc %s" % (vn, vline, (loc or "")[:60]))
    out = subprocess.run([args.objdump, "-d", "--no-show-raw-insn",
                          "--start-address=%#x" % (lo & ((1 << 64) - 1)),
                          "--stop-address=%#x" % (hi & ((1 << 64) - 1)), args.kernel],
                         capture_output=True, text=True).stdout
    print("## disassembly")
    last_line = None
    for line in out.splitlines():
        m = INSN_RE.match(line)
        if not m:
            continue
        addr = int(m.group(1), 16)
        insn = m.group(2).strip()
        lr = db.execute("SELECT line FROM line WHERE cu_id=? AND addr<=? AND line>0 AND end_sequence=0 "
                        "ORDER BY addr DESC LIMIT 1", (cu, addr - (1 << 64) if addr >= (1 << 63) else addr)).fetchone()
        srcline = lr[0] if lr else None
        anno = ""
        if srcline != last_line:
            anno = "  ; line %s" % srcline
            last_line = srcline
        tm = re.search(r"\b(?:bl|b)\s+(0x[0-9a-f]+)", insn)
        callee = ""
        if tm:
            tgt = int(tm.group(1), 16)
            nm = fmap.lookup(tgt)
            if nm:
                callee = "  -> %s" % nm
        print("  %016x %-46s%s%s" % (addr, insn, anno, callee))


if __name__ == "__main__":
    main()
