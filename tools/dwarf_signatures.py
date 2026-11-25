#!/usr/bin/env python3
"""Resolve C function signatures from the xnu-13432 DWARF SQLite model."""
import argparse
import sqlite3
import sys

class SigResolver:
    def __init__(self, db):
        self.db = db
        self.cache = {}

    def type_row(self, off):
        if off not in self.cache:
            self.cache[off] = self.db.execute(
                "SELECT * FROM type WHERE die_offset=? LIMIT 1", (off,)).fetchone()
        return self.cache[off]

    def name(self, off, depth=0):
        if not off or depth > 8:
            return "void"
        t = self.type_row(off)
        if not t:
            return "void"
        tag, name = t["tag"], t["name"]
        if tag == "DW_TAG_typedef":
            return name or self.name(t["type_offset"], depth + 1)
        if tag == "DW_TAG_pointer_type":
            inner = self.name(t["type_offset"], depth + 1)
            return inner if inner.endswith("*") else inner + " *"
        if tag == "DW_TAG_const_type":
            return "const " + self.name(t["type_offset"], depth + 1)
        if tag == "DW_TAG_volatile_type":
            return "volatile " + self.name(t["type_offset"], depth + 1)
        if tag == "DW_TAG_restrict_type":
            return self.name(t["type_offset"], depth + 1) + " restrict"
        if tag == "DW_TAG_array_type":
            n = t["array_count"]
            return self.name(t["type_offset"], depth + 1) + (
                "[%d]" % n if n else "[]")
        if tag == "DW_TAG_subroutine_type":
            return "void (*)()"
        if name:
            prefix = {
                "DW_TAG_structure_type": "struct ",
                "DW_TAG_union_type": "union ",
                "DW_TAG_enumeration_type": "enum ",
            }.get(tag, "")
            return name if name.startswith(prefix) else prefix + name
        return "void"

    def signature(self, func):
        ret = self.name(func["type_offset"])
        params = []
        for p in self.db.execute(
                "SELECT name,type_offset FROM func_param WHERE func_id=? "
                "ORDER BY ordinal", (func["id"],)):
            params.append("%s %s" % (self.name(p["type_offset"]),
                                     p["name"] or "arg"))
        return ret, ", ".join(params) or "void"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--file", help="only functions from this source-file suffix")
    ap.add_argument("--func", help="only this function name")
    args = ap.parse_args()
    db = sqlite3.connect(args.db)
    db.row_factory = sqlite3.Row
    r = SigResolver(db)
    where, params = [], []
    if args.file:
        where.append("c.name LIKE ?")
        params.append("%/" + args.file)
    if args.func:
        where.append("f.name=?")
        params.append(args.func)
    sql = ("SELECT f.* FROM func f JOIN cu c ON c.id=f.cu_id "
           "WHERE f.name IS NOT NULL AND f.name!='?'")
    if where:
        sql += " AND " + " AND ".join(where)
    sql += " ORDER BY f.decl_line"
    for f in db.execute(sql, params):
        ret, ps = r.signature(f)
        print("%s %s(%s);" % (ret, f["name"], ps))


if __name__ == "__main__":
    sys.exit(main())
