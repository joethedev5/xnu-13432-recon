#!/usr/bin/env python3
"""Build a SQLite model of an ELF (synthetic) DWARF file.

Captures compile units, source file tables, subprograms/params, types,
members/enumerators and line-table rows.  Only standard-library deps plus
pyelftools.
"""
import argparse
import json
import os
import sqlite3
import sys
import time

from elftools.elf.elffile import ELFFile

SCHEMA = """
PRAGMA journal_mode=OFF;
PRAGMA synchronous=OFF;
CREATE TABLE cu (id INTEGER PRIMARY KEY, cu_offset INTEGER, name TEXT,
                 comp_dir TEXT, producer TEXT, low_pc INTEGER, high_pc INTEGER,
                 stmt_list INTEGER, language INTEGER);
CREATE TABLE source_file (id INTEGER PRIMARY KEY, cu_id INTEGER, idx INTEGER,
                          path TEXT);
CREATE TABLE func (id INTEGER PRIMARY KEY, cu_id INTEGER, die_offset INTEGER,
                   name TEXT, linkage_name TEXT, decl_file INTEGER,
                   decl_line INTEGER, low_pc INTEGER, high_pc INTEGER,
                   type_offset INTEGER, inline INTEGER, declaration INTEGER);
CREATE TABLE func_param (id INTEGER PRIMARY KEY, func_id INTEGER, ordinal INTEGER,
                         name TEXT, type_offset INTEGER);
CREATE TABLE func_range (func_id INTEGER, lo INTEGER, hi INTEGER);
CREATE TABLE type (id INTEGER PRIMARY KEY, cu_id INTEGER, die_offset INTEGER,
                   tag TEXT, name TEXT, byte_size INTEGER, encoding INTEGER,
                   decl_file INTEGER, decl_line INTEGER, type_offset INTEGER,
                   specification INTEGER);
CREATE TABLE member (id INTEGER PRIMARY KEY, type_id INTEGER, ordinal INTEGER,
                     name TEXT, type_offset INTEGER, byte_offset INTEGER,
                     bit_offset INTEGER, bit_size INTEGER, data_bit_offset INTEGER);
CREATE TABLE enumerator (id INTEGER PRIMARY KEY, type_id INTEGER, name TEXT,
                         value INTEGER);
CREATE TABLE line (cu_id INTEGER, addr INTEGER, file_idx INTEGER, line INTEGER,
                   column INTEGER, is_stmt INTEGER, end_sequence INTEGER);
CREATE INDEX idx_func_cu ON func(cu_id);
CREATE INDEX idx_func_name ON func(name);
CREATE INDEX idx_type_cu ON type(cu_id);
CREATE INDEX idx_type_name ON type(name);
CREATE INDEX idx_member_type ON member(type_id);
CREATE INDEX idx_source_path ON source_file(path);
"""


def attr(die, name):
    return die.attributes.get(name)


def val(die, name, default=None):
    a = die.attributes.get(name)
    return a.value if a is not None else default


def sval(die, name):
    v = val(die, name)
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v


def file_paths(dwarf, cu):
    try:
        lp = dwarf.line_program_for_CU(cu)
    except Exception:
        return []
    if lp is None:
        return []
    dirs = lp.header.get("include_directory") or []
    dirs = [d.decode("utf-8", "replace") if isinstance(d, bytes) else str(d) for d in dirs]
    out = []
    for e in lp.header.get("file_entry") or []:
        name = e.name.decode("utf-8", "replace") if isinstance(e.name, bytes) else str(e.name)
        d = int(e.dir_index) if e.dir_index is not None else 0
        if os.path.isabs(name):
            p = name
        elif 0 < d <= len(dirs):
            p = os.path.normpath(os.path.join(dirs[d - 1], name))
        else:
            p = name
        out.append(p)
    return out


def pc_range(dwarf, cu, die):
    lo = val(die, "DW_AT_low_pc")
    hi = val(die, "DW_AT_high_pc")
    if lo is not None and hi is not None:
        if die.attributes["DW_AT_high_pc"].form == "DW_FORM_addr":
            return int(lo), int(hi)
        return int(lo), int(lo) + int(hi)
    try:
        ranges = list(dwarf.die_ranges(cu, die))
    except Exception:
        return None, None
    if not ranges:
        return None, None
    return int(min(r[0] for r in ranges)), int(max(r[1] for r in ranges))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("elf")
    ap.add_argument("db")
    ap.add_argument("--limit-cus", type=int, default=0)
    args = ap.parse_args()

    f = open(args.elf, "rb")
    dwarf = ELFFile(f).get_dwarf_info()
    db = sqlite3.connect(args.db)
    db.executescript(SCHEMA)

    ncu = nfunc = ntype = nmember = nline = 0
    t0 = time.time()
    for cu in dwarf.iter_CUs():
        if args.limit_cus and ncu >= args.limit_cus:
            break
        ncu += 1
        top = cu.get_top_DIE()
        try:
            lo, hi = pc_range(dwarf, cu, top)
        except Exception:
            lo = hi = None
        cur = db.execute(
            "INSERT INTO cu (cu_offset,name,comp_dir,producer,low_pc,high_pc,stmt_list,language)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (cu.cu_offset, sval(top, "DW_AT_name"), sval(top, "DW_AT_comp_dir"),
             sval(top, "DW_AT_producer"), lo, hi,
             val(top, "DW_AT_stmt_list"), val(top, "DW_AT_language")))
        cu_id = cur.lastrowid
        paths = file_paths(dwarf, cu)
        db.executemany("INSERT INTO source_file (cu_id,idx,path) VALUES (?,?,?)",
                       [(cu_id, i, p) for i, p in enumerate(paths)])

        def walk(node):
            nonlocal nfunc, ntype, nmember
            for die in node.iter_children():
                tag = die.tag
                if tag == "DW_TAG_subprogram":
                    try:
                        flo, fhi = pc_range(dwarf, cu, die)
                    except Exception:
                        flo = fhi = None
                    inline = 1 if val(die, "DW_AT_inline") is not None or val(die, "DW_AT_abstract_origin") is not None else 0
                    decl = 1 if val(die, "DW_AT_declaration") else 0
                    r = db.execute(
                        "INSERT INTO func (cu_id,die_offset,name,linkage_name,decl_file,decl_line,low_pc,high_pc,type_offset,inline,declaration)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (cu_id, die.offset, sval(die, "DW_AT_name"),
                         sval(die, "DW_AT_linkage_name") or sval(die, "DW_AT_MIPS_linkage_name"),
                         val(die, "DW_AT_decl_file"), val(die, "DW_AT_decl_line"),
                         flo, fhi, val(die, "DW_AT_type"), inline, decl))
                    fid = r.lastrowid
                    nfunc += 1
                    if flo is not None:
                        try:
                            for rr in dwarf.die_ranges(cu, die):
                                db.execute("INSERT INTO func_range VALUES (?,?,?)",
                                           (fid, int(rr[0]), int(rr[1])))
                        except Exception:
                            pass
                    ordinal = 0
                    for child in die.iter_children():
                        if child.tag == "DW_TAG_formal_parameter":
                            ordinal += 1
                            db.execute(
                                "INSERT INTO func_param (func_id,ordinal,name,type_offset) VALUES (?,?,?,?)",
                                (fid, ordinal, sval(child, "DW_AT_name"), val(child, "DW_AT_type")))
                    continue
                if tag in ("DW_TAG_structure_type", "DW_TAG_union_type",
                           "DW_TAG_enumeration_type", "DW_TAG_typedef",
                           "DW_TAG_base_type", "DW_TAG_pointer_type",
                           "DW_TAG_array_type", "DW_TAG_const_type",
                           "DW_TAG_volatile_type", "DW_TAG_restrict_type",
                           "DW_TAG_subroutine_type", "DW_TAG_unspecified_type"):
                    r = db.execute(
                        "INSERT INTO type (cu_id,die_offset,tag,name,byte_size,encoding,decl_file,decl_line,type_offset,specification)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (cu_id, die.offset, tag, sval(die, "DW_AT_name"),
                         val(die, "DW_AT_byte_size"), val(die, "DW_AT_encoding"),
                         val(die, "DW_AT_decl_file"), val(die, "DW_AT_decl_line"),
                         val(die, "DW_AT_type"),
                         val(die, "DW_AT_specification")))
                    tid = r.lastrowid
                    ntype += 1
                    ordinal = 0
                    for child in die.iter_children():
                        if child.tag == "DW_TAG_member":
                            ordinal += 1
                            db.execute(
                                "INSERT INTO member (type_id,ordinal,name,type_offset,byte_offset,bit_offset,bit_size,data_bit_offset)"
                                " VALUES (?,?,?,?,?,?,?,?)",
                                (tid, ordinal, sval(child, "DW_AT_name"),
                                 val(child, "DW_AT_type"),
                                 val(child, "DW_AT_data_member_location"),
                                 val(child, "DW_AT_bit_offset"), val(child, "DW_AT_bit_size"),
                                 val(child, "DW_AT_data_bit_offset")))
                            nmember += 1
                        elif child.tag == "DW_TAG_enumerator":
                            db.execute("INSERT INTO enumerator (type_id,name,value) VALUES (?,?,?)",
                                       (tid, sval(child, "DW_AT_name"), val(child, "DW_AT_const_value")))
                    continue
                walk(die)

        try:
            walk(cu.get_top_DIE())
        except Exception as e:
            print("CU %d parse error: %s" % (cu_id, e), file=sys.stderr)
            continue

        try:
            lp = dwarf.line_program_for_CU(cu)
        except Exception:
            lp = None
        if lp is not None:
            rows = []
            for entry in lp.get_entries():
                s = entry.state
                if s is None:
                    continue
                rows.append((cu_id, s.address, s.file, s.line, s.column, 1 if s.is_stmt else 0,
                             1 if s.end_sequence else 0))
                nline += 1
                if len(rows) >= 50000:
                    db.executemany("INSERT INTO line VALUES (?,?,?,?,?,?,?)", rows)
                    rows.clear()
            if rows:
                db.executemany("INSERT INTO line VALUES (?,?,?,?,?,?,?)", rows)
        db.commit()
        if ncu % 50 == 0:
            print("CU %d funcs=%d types=%d lines=%d elapsed=%.1fs" %
                  (ncu, nfunc, ntype, nline, time.time() - t0), flush=True)

    db.commit()
    for t in ("cu", "source_file", "func", "func_param", "type", "member", "enumerator", "line"):
        print(t, db.execute("SELECT count(*) FROM " + t).fetchone()[0])
    db.close()
    print("done in %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
