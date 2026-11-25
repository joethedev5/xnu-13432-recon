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
                   type_offset INTEGER, inline INTEGER, declaration INTEGER,
                   abstract_origin INTEGER, specification INTEGER);
CREATE TABLE func_param (id INTEGER PRIMARY KEY, func_id INTEGER, ordinal INTEGER,
                         name TEXT, type_offset INTEGER);
CREATE TABLE func_range (func_id INTEGER, lo INTEGER, hi INTEGER);
CREATE TABLE type (id INTEGER PRIMARY KEY, cu_id INTEGER, die_offset INTEGER,
                   tag TEXT, name TEXT, byte_size INTEGER, encoding INTEGER,
                   decl_file INTEGER, decl_line INTEGER, type_offset INTEGER,
                   specification INTEGER, array_count INTEGER);
CREATE TABLE member (id INTEGER PRIMARY KEY, type_id INTEGER, ordinal INTEGER,
                     name TEXT, type_offset INTEGER, byte_offset INTEGER,
                     bit_offset INTEGER, bit_size INTEGER, data_bit_offset INTEGER);
CREATE TABLE enumerator (id INTEGER PRIMARY KEY, type_id INTEGER, name TEXT,
                         value INTEGER);
CREATE TABLE line (cu_id INTEGER, addr INTEGER, file_idx INTEGER, line INTEGER,
                   column INTEGER, is_stmt INTEGER, end_sequence INTEGER);
CREATE TABLE variable (id INTEGER PRIMARY KEY, cu_id INTEGER, func_id INTEGER,
                       die_offset INTEGER, name TEXT, decl_file INTEGER,
                       decl_line INTEGER, type_offset INTEGER, location TEXT,
                       const_value TEXT, abstract_origin INTEGER);
CREATE TABLE call_site (id INTEGER PRIMARY KEY, cu_id INTEGER, func_id INTEGER,
                        die_offset INTEGER, call_return_pc INTEGER,
                        call_origin INTEGER, call_target TEXT);
CREATE INDEX idx_func_cu ON func(cu_id);
CREATE INDEX idx_func_name ON func(name);
CREATE INDEX idx_type_cu ON type(cu_id);
CREATE INDEX idx_type_name ON type(name);
CREATE INDEX idx_member_type ON member(type_id);
CREATE INDEX idx_source_path ON source_file(path);
CREATE INDEX idx_line_cu_addr ON line(cu_id,addr);
CREATE INDEX idx_func_die ON func(die_offset);
CREATE INDEX idx_var_die ON variable(die_offset);
CREATE INDEX idx_type_die ON type(die_offset);
CREATE INDEX idx_member_typeref ON member(type_offset);
CREATE INDEX idx_param_typeref ON func_param(type_offset);
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


def saddr(v):
    """SQLite integers are signed 64-bit; kernel addresses are unsigned 64-bit."""
    if v is None:
        return None
    v = int(v)
    return v - (1 << 64) if v >= (1 << 63) else v


def refaddr(cu, die, name):
    """Resolve a DW_AT_type-style reference to an absolute .debug_info offset."""
    a = die.attributes.get(name)
    if a is None or not isinstance(a.value, int):
        return None
    if a.form in ("DW_FORM_ref1", "DW_FORM_ref2", "DW_FORM_ref4",
                  "DW_FORM_ref8", "DW_FORM_ref_udata"):
        return cu.cu_offset + a.value
    return a.value


def safe_int(v):
    return int(v) if isinstance(v, int) else None


def sqi(v):
    """Signed-64-bit encoding for every integer bound for SQLite."""
    v = safe_int(v)
    return saddr(v)


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
    if os.path.exists(args.db):
        os.remove(args.db)
    db = sqlite3.connect(args.db)
    db.executescript(SCHEMA)

    ncu = nfunc = ntype = nmember = nline = nvar = ncall = 0
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
             sval(top, "DW_AT_producer"), saddr(lo), saddr(hi),
             sqi(val(top, "DW_AT_stmt_list")), sqi(val(top, "DW_AT_language"))))
        cu_id = cur.lastrowid
        paths = file_paths(dwarf, cu)
        db.executemany("INSERT INTO source_file (cu_id,idx,path) VALUES (?,?,?)",
                       [(cu_id, i, p) for i, p in enumerate(paths)])

        def walk_scope(children, fid):
            nonlocal nvar, ncall
            for child in children:
                if child.tag == "DW_TAG_variable":
                    loc = val(child, "DW_AT_location")
                    if isinstance(loc, list):
                        loc = json.dumps(loc)
                    elif loc is not None:
                        loc = str(loc)
                    cv = val(child, "DW_AT_const_value")
                    db.execute(
                        "INSERT INTO variable (cu_id,func_id,die_offset,name,decl_file,decl_line,type_offset,location,const_value,abstract_origin)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (cu_id, fid, child.offset, sval(child, "DW_AT_name"),
                         sqi(val(child, "DW_AT_decl_file")), sqi(val(child, "DW_AT_decl_line")),
                         refaddr(cu, child, "DW_AT_type"), loc,
                         json.dumps(cv) if isinstance(cv, (list, dict)) else (str(cv) if cv is not None else None),
                         refaddr(cu, child, "DW_AT_abstract_origin")))
                    nvar += 1
                elif child.tag == "DW_TAG_call_site":
                    tgt = val(child, "DW_AT_call_target") or val(child, "DW_AT_call_target_clobbered")
                    if isinstance(tgt, list):
                        tgt = json.dumps(tgt)
                    db.execute(
                        "INSERT INTO call_site (cu_id,func_id,die_offset,call_return_pc,call_origin,call_target)"
                        " VALUES (?,?,?,?,?,?)",
                        (cu_id, fid, child.offset,
                         sqi(val(child, "DW_AT_call_return_pc")),
                         refaddr(cu, child, "DW_AT_call_origin"),
                         str(tgt) if tgt is not None else None))
                    ncall += 1
                elif child.tag in ("DW_TAG_lexical_block", "DW_TAG_inlined_subroutine",
                                   "DW_TAG_try_block", "DW_TAG_catch_block"):
                    walk_scope(list(child.iter_children()), fid)

        def walk(node):
            nonlocal nfunc, ntype, nmember
            for die in node.iter_children():
                tag = die.tag
                if tag == "DW_TAG_variable":
                    loc = val(die, "DW_AT_location")
                    if isinstance(loc, list):
                        loc = json.dumps(loc)
                    elif loc is not None:
                        loc = str(loc)
                    db.execute(
                        "INSERT INTO variable (cu_id,func_id,die_offset,name,decl_file,decl_line,type_offset,location,const_value,abstract_origin)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?)",
                        (cu_id, None, die.offset, sval(die, "DW_AT_name"),
                         sqi(val(die, "DW_AT_decl_file")), sqi(val(die, "DW_AT_decl_line")),
                         refaddr(cu, die, "DW_AT_type"), loc, None,
                         refaddr(cu, die, "DW_AT_abstract_origin")))
                    continue
                if tag == "DW_TAG_subprogram":
                    try:
                        flo, fhi = pc_range(dwarf, cu, die)
                    except Exception:
                        flo = fhi = None
                    inline = 1 if val(die, "DW_AT_inline") is not None or val(die, "DW_AT_abstract_origin") is not None else 0
                    decl = 1 if val(die, "DW_AT_declaration") else 0
                    r = db.execute(
                        "INSERT INTO func (cu_id,die_offset,name,linkage_name,decl_file,decl_line,low_pc,high_pc,type_offset,inline,declaration,abstract_origin,specification)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (cu_id, die.offset, sval(die, "DW_AT_name"),
                         sval(die, "DW_AT_linkage_name") or sval(die, "DW_AT_MIPS_linkage_name"),
                         sqi(val(die, "DW_AT_decl_file")), sqi(val(die, "DW_AT_decl_line")),
                         saddr(flo), saddr(fhi), refaddr(cu, die, "DW_AT_type"), inline, decl,
                         refaddr(cu, die, "DW_AT_abstract_origin"),
                         refaddr(cu, die, "DW_AT_specification")))
                    fid = r.lastrowid
                    nfunc += 1
                    if flo is not None:
                        try:
                            for rr in dwarf.die_ranges(cu, die):
                                db.execute("INSERT INTO func_range VALUES (?,?,?)",
                                           (fid, saddr(rr[0]), saddr(rr[1])))
                        except Exception:
                            pass
                    children = list(die.iter_children())
                    ordinal = 0
                    for child in children:
                        if child.tag == "DW_TAG_formal_parameter":
                            ordinal += 1
                            db.execute(
                                "INSERT INTO func_param (func_id,ordinal,name,type_offset) VALUES (?,?,?,?)",
                                (fid, ordinal, sval(child, "DW_AT_name"), refaddr(cu, child, "DW_AT_type")))
                    walk_scope(children, fid)
                    continue
                if tag in ("DW_TAG_structure_type", "DW_TAG_union_type",
                           "DW_TAG_enumeration_type", "DW_TAG_typedef",
                           "DW_TAG_base_type", "DW_TAG_pointer_type",
                           "DW_TAG_array_type", "DW_TAG_const_type",
                           "DW_TAG_volatile_type", "DW_TAG_restrict_type",
                           "DW_TAG_subroutine_type", "DW_TAG_unspecified_type"):
                    r = db.execute(
                        "INSERT INTO type (cu_id,die_offset,tag,name,byte_size,encoding,decl_file,decl_line,type_offset,specification,array_count)"
                        " VALUES (?,?,?,?,?,?,?,?,?,?,NULL)",
                        (cu_id, die.offset, tag, sval(die, "DW_AT_name"),
                         val(die, "DW_AT_byte_size"), val(die, "DW_AT_encoding"),
                         sqi(val(die, "DW_AT_decl_file")), sqi(val(die, "DW_AT_decl_line")),
                         refaddr(cu, die, "DW_AT_type"),
                         refaddr(cu, die, "DW_AT_specification")))
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
                                 refaddr(cu, child, "DW_AT_type"),
                                 sqi(val(child, "DW_AT_data_member_location")),
                                 sqi(val(child, "DW_AT_bit_offset")), sqi(val(child, "DW_AT_bit_size")),
                                 sqi(val(child, "DW_AT_data_bit_offset"))))
                            nmember += 1
                        elif child.tag == "DW_TAG_subrange_type":
                            cnt = val(child, "DW_AT_count")
                            ub = val(child, "DW_AT_upper_bound")
                            if cnt is None and ub is not None:
                                cnt = int(ub) + 1
                            if cnt is not None:
                                db.execute("UPDATE type SET array_count=? WHERE id=?", (sqi(cnt), tid))
                        elif child.tag == "DW_TAG_enumerator":
                            db.execute("INSERT INTO enumerator (type_id,name,value) VALUES (?,?,?)",
                                       (tid, sval(child, "DW_AT_name"), sqi(val(child, "DW_AT_const_value"))))
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
                rows.append((cu_id, saddr(s.address), sqi(s.file), sqi(s.line), sqi(s.column), 1 if s.is_stmt else 0,
                             1 if s.end_sequence else 0))
                nline += 1
                if len(rows) >= 50000:
                    db.executemany("INSERT INTO line VALUES (?,?,?,?,?,?,?)", rows)
                    rows.clear()
            if rows:
                db.executemany("INSERT INTO line VALUES (?,?,?,?,?,?,?)", rows)
        db.commit()
        if ncu % 50 == 0:
            print("CU %d funcs=%d types=%d lines=%d vars=%d calls=%d elapsed=%.1fs" %
                  (ncu, nfunc, ntype, nline, nvar, ncall, time.time() - t0), flush=True)

    db.commit()
    # Resolve names through abstract_origin / specification chains (indexed).
    for _ in range(4):
        db.execute("UPDATE func SET name=(SELECT o.name FROM func o WHERE o.die_offset=func.abstract_origin AND o.name IS NOT NULL LIMIT 1) "
                   "WHERE name IS NULL AND abstract_origin IS NOT NULL")
        db.execute("UPDATE func SET name=(SELECT o.name FROM func o WHERE o.die_offset=func.specification AND o.name IS NOT NULL LIMIT 1) "
                   "WHERE name IS NULL AND specification IS NOT NULL")
        db.execute("UPDATE func SET linkage_name=(SELECT o.linkage_name FROM func o WHERE o.die_offset=func.abstract_origin AND o.linkage_name IS NOT NULL LIMIT 1) "
                   "WHERE linkage_name IS NULL AND abstract_origin IS NOT NULL")
        db.execute("UPDATE func SET linkage_name=(SELECT o.linkage_name FROM func o WHERE o.die_offset=func.specification AND o.linkage_name IS NOT NULL LIMIT 1) "
                   "WHERE linkage_name IS NULL AND specification IS NOT NULL")
    db.execute("UPDATE variable SET name=(SELECT o.name FROM variable o WHERE o.die_offset=variable.abstract_origin AND o.name IS NOT NULL LIMIT 1) "
               "WHERE name IS NULL AND abstract_origin IS NOT NULL")
    db.commit()
    for t in ("cu", "source_file", "func", "func_param", "type", "member", "enumerator", "line", "variable", "call_site"):
        print(t, db.execute("SELECT count(*) FROM " + t).fetchone()[0])
    db.close()
    print("done in %.1fs" % (time.time() - t0))


if __name__ == "__main__":
    main()
