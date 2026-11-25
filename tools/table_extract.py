#!/usr/bin/env python3
"""Extract the xnu-13432 vmapple BSD syscall and Mach trap tables.

Addresses and struct layouts are taken from the DWARF variable/type DIEs in
the SQLite model, so this is evidence-driven rather than hard-coded.
"""
import argparse
import bisect
import json
import os
import re
import sqlite3
import sys

from macho import MachO


def loc_addr(loc):
    if not loc:
        return None
    v = json.loads(loc) if loc.startswith("[") else None
    if not v or v[0] != 0x03 or len(v) < 9:
        return None
    return int.from_bytes(bytes(v[1:9]), "little")


class FuncMap:
    def __init__(self, db):
        self.exact = {}
        self.intervals = []
        for name, link, lo, hi in db.execute(
                "SELECT name,linkage_name,low_pc,high_pc FROM func "
                "WHERE low_pc IS NOT NULL AND high_pc IS NOT NULL AND high_pc > low_pc"):
            addr = lo & ((1 << 64) - 1)
            end = hi & ((1 << 64) - 1)
            label = name or link
            if label:
                self.exact.setdefault(addr, label)
                self.intervals.append((addr, end, label))
        for name, link, lo, hi in db.execute(
                "SELECT f.name,f.linkage_name,r.lo,r.hi FROM func_range r "
                "JOIN func f ON f.id=r.func_id WHERE r.hi > r.lo"):
            addr = lo & ((1 << 64) - 1)
            end = hi & ((1 << 64) - 1)
            label = name or link
            if label:
                self.exact.setdefault(addr, label)
                self.intervals.append((addr, end, label))
        self.intervals.sort()
        self.los = [x[0] for x in self.intervals]

    def lookup(self, addr):
        if addr is None:
            return None
        if addr in self.exact:
            return self.exact[addr]
        i = bisect.bisect_right(self.los, addr) - 1
        best = None
        while i >= 0:
            lo, hi, name = self.intervals[i]
            if hi > addr:
                if best is None or (hi - lo) < best[0]:
                    best = (hi - lo, name)
            if lo < addr - (1 << 32):
                break
            i -= 1
        return best[1] if best else None


def struct_layout(db, name):
    row = db.execute("SELECT id,tag,name,byte_size,type_offset FROM type "
                     "WHERE tag='DW_TAG_structure_type' AND name=?", (name,)).fetchone()
    if row is None:
        row = db.execute("SELECT id,tag,name,byte_size,type_offset FROM type "
                         "WHERE tag='DW_TAG_typedef' AND name=?", (name,)).fetchone()
        if row is None:
            raise SystemExit("struct %s not found in DWARF" % name)
        st = db.execute("SELECT id,tag,name,byte_size,type_offset FROM type WHERE die_offset=?", (row[4],)).fetchone()
        if st is None:
            raise SystemExit("struct for typedef %s not found" % name)
        row = st
    tid, tag, tname, size, _ = row
    members = {}
    for mname, moff, mbits in db.execute(
            "SELECT name,byte_offset,bit_size FROM member WHERE type_id=? ORDER BY ordinal", (tid,)):
        members[mname] = (moff, mbits)
    return size, members


def get_var(db, name):
    rows = db.execute("SELECT location,type_offset,cu_id FROM variable "
                      "WHERE name=? AND func_id IS NULL ORDER BY id LIMIT 5", (name,)).fetchall()
    for loc, toff, cu in rows:
        a = loc_addr(loc)
        if a is not None:
            return a, toff, cu
    return None, None, None


def var_count(db, name):
    _, toff, _ = get_var(db, name)
    seen = set()
    while toff and toff not in seen:
        seen.add(toff)
        row = db.execute("SELECT tag,array_count,type_offset FROM type WHERE die_offset=?",
                         (toff,)).fetchone()
        if row is None:
            return None
        tag, count, nxt = row
        if tag == "DW_TAG_array_type" and count:
            return count
        toff = nxt
    return None


def read_var_int(db, macho, name, size):
    a, toff, cu = get_var(db, name)
    if a is None:
        return None
    return int.from_bytes(macho.read(a, size), "little")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="analysis/xnu-13432.dwarf.db")
    ap.add_argument("--kernel", default="kdk/root/System/Library/Kernels/kernel.release.vmapple")
    ap.add_argument("--public", default="xnu-12377.121.6")
    ap.add_argument("--outdir", default="analysis/tables")
    args = ap.parse_args()
    os.makedirs(args.outdir, exist_ok=True)
    db = sqlite3.connect(args.db)
    macho = MachO(args.kernel)
    fmap = FuncMap(db)

    sysent_addr, _, _ = get_var(db, "sysent")
    nsysent = var_count(db, "sysent") or read_var_int(db, macho, "nsysent", 4)
    sysent_size, sysent_members = struct_layout(db, "sysent")
    mt_addr, _, _ = get_var(db, "mach_trap_table")
    mt_count = var_count(db, "mach_trap_table") or read_var_int(db, macho, "mach_trap_count", 4)
    mt_size, mt_members = struct_layout(db, "mach_trap_t")
    mt_names_addr, _, _ = get_var(db, "mach_syscall_name_table")
    print("sysent %#x nsysent=%d entry=%d" % (sysent_addr, nsysent, sysent_size))
    print("mach_trap_table %#x count=%d entry=%d" % (mt_addr, mt_count, mt_size))

    def off(members, name):
        return members[name][0]

    sysent = []
    for i in range(nsysent):
        base = sysent_addr + i * sysent_size
        call = macho.decode_ptr(base + off(sysent_members, "sy_call"))
        munge = macho.decode_ptr(base + off(sysent_members, "sy_arg_munge32"))
        rt = int.from_bytes(macho.read(base + off(sysent_members, "sy_return_type"), 4), "little", signed=True)
        narg = int.from_bytes(macho.read(base + off(sysent_members, "sy_narg"), 2), "little", signed=True)
        ab = int.from_bytes(macho.read(base + off(sysent_members, "sy_arg_bytes"), 2), "little")
        sysent.append({"num": i, "handler_addr": call["addr"],
                       "handler": fmap.lookup(call["addr"]),
                       "munge_addr": munge["addr"], "munge": fmap.lookup(munge["addr"]),
                       "return_type": rt, "narg": narg, "arg_bytes": ab})

    traps = []
    for i in range(mt_count):
        base = mt_addr + i * mt_size
        fn = macho.decode_ptr(base + off(mt_members, "mach_trap_function"))
        arg_count = macho.read(base + off(mt_members, "mach_trap_arg_count"), 1)[0]
        u32 = macho.read(base + off(mt_members, "mach_trap_u32_words"), 1)[0]
        ret_port = macho.read(base + off(mt_members, "mach_trap_returns_port"), 1)[0]
        munge = macho.decode_ptr(base + off(mt_members, "mach_trap_arg_munge32"))
        name = None
        if mt_names_addr:
            p = macho.decode_ptr(mt_names_addr + i * 8)
            if p["addr"]:
                try:
                    name = macho.cstring(p["addr"])
                except ValueError:
                    name = None
        traps.append({"num": i, "handler_addr": fn["addr"],
                      "handler": fmap.lookup(fn["addr"]),
                      "name": name, "arg_count": arg_count,
                      "u32_words": u32, "returns_port": ret_port,
                      "munge_addr": munge["addr"]})

    with open(os.path.join(args.outdir, "sysent.json"), "w") as f:
        json.dump(sysent, f, indent=1)
    with open(os.path.join(args.outdir, "machtraps.json"), "w") as f:
        json.dump(traps, f, indent=1)

    # Public syscalls.master candidates per number.
    master = os.path.join(args.public, "bsd/kern/syscalls.master")
    pub_sys = {}
    buf = ""
    for line in open(master, errors="replace"):
        if not buf and not re.match(r"\s*\d+\s", line):
            continue
        buf += line
        if "}" not in buf:
            continue
        m = re.match(r"\s*(\d+)\s+(\S+)\s+(\S+)\s+\{(.*)\}", buf, re.S)
        buf = ""
        if not m:
            continue
        num = int(m.group(1))
        body = m.group(4)
        fm = re.search(r"([A-Za-z_][A-Za-z0-9_]*)\s*\(", body)
        if not fm:
            continue
        proto = body[fm.start():]
        params = proto[proto.find("(") + 1:proto.rfind(")")]
        depth = 0
        nparams = 0
        if params.strip() and params.strip() != "void":
            nparams = 1
            for c in params:
                if c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                elif c == "," and depth == 0:
                    nparams += 1
        pub_sys.setdefault(num, []).append({"handler": fm.group(1), "narg": nparams, "flags": m.group(3)})

    # Public Mach trap table.
    sw = open(os.path.join(args.public, "osfmk/kern/syscall_sw.c"), errors="replace").read()
    start = sw.find("mach_trap_table[MACH_TRAP_TABLE_COUNT] = {")
    end = sw.find("};", start)
    block = sw[start:end] if start >= 0 and end > start else sw
    pub_traps = []
    for m in re.finditer(r"MACH_TRAP\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*([^,]+),\s*([^,]+)", block):
        name, argc, u32 = m.group(1), m.group(2).strip(), m.group(3).strip()
        try:
            argc = int(argc, 0)
        except ValueError:
            pass
        pub_traps.append({"handler": name, "arg_count": argc})

    # Report.
    out = []
    out.append("# XNU 13432 vmapple dispatch tables\n")
    out.append("- sysent: %#x, nsysent=%d, entry size=%d" % (sysent_addr, nsysent, sysent_size))
    out.append("- mach_trap_table: %#x, count=%d, entry size=%d\n" % (mt_addr, mt_count, mt_size))
    out.append("## BSD syscall table vs public xnu-12377.121.6 syscalls.master\n")
    mism = []
    for e in sysent:
        cands = pub_sys.get(e["num"], [])
        names = [c["handler"] for c in cands]
        if not cands:
            mism.append((e["num"], e["handler"], "no public entry", e["narg"]))
        elif e["handler"] not in names:
            mism.append((e["num"], e["handler"], "public: " + ",".join(names), e["narg"]))
    out.append("Entries: %d. Handler-name mismatches: %d\n" % (len(sysent), len(mism)))
    if mism:
        out.append("| syscall | 13432 handler | public candidates | 13432 narg |")
        out.append("|---|---|---|---|")
        for num, h, pub, narg in mism:
            out.append("| %d | %s | %s | %d |" % (num, h or "?", pub, narg))
        out.append("")
    out.append("## Mach trap table vs public syscall_sw.c\n")
    tmism = []
    for e in traps:
        idx = e["num"]
        pub = pub_traps[idx] if idx < len(pub_traps) else None
        label = e["name"] or e["handler"]
        if pub is None:
            tmism.append((idx, e["handler"], e["name"], "no public entry", e["arg_count"]))
        elif pub["handler"] != label:
            tmism.append((idx, e["handler"], e["name"], pub["handler"], e["arg_count"]))
    out.append("Entries: %d (public table %d). Handler mismatches: %d\n" % (len(traps), len(pub_traps), len(tmism)))
    if tmism:
        out.append("| trap | 13432 handler | name table | public handler | 13432 argc |")
        out.append("|---|---|---|---|---|")
        for row in tmism:
            out.append("| %d | %s | %s | %s | %s |" % row)
    with open(os.path.join(args.outdir, "REPORT.md"), "w") as f:
        f.write("\n".join(out) + "\n")
    print("wrote", args.outdir)
    print("sysent mismatches", len(mism), "trap mismatches", len(tmism))


if __name__ == "__main__":
    main()
