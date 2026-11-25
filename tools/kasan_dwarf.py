#!/usr/bin/env python3
"""Inspect the KDK kasan companion kernel's DWARF.

The release kernel's dSYM is line-table oriented: it keeps function
signatures but drops most locals and types.  The kasan dSYM for the same
KDK keeps full DWARF (locals, types, inlined-subroutine trees) and the
`mach_assert_default` descriptors whose `expr` field is the assert source
text.  This tool exposes both.

Prepare the DWARF once with:

    python3 tools/macho_dwarf.py \
        kdk/root/System/Library/Kernels/kernel.kasan.vmapple.dSYM/Contents/Resources/DWARF/kernel.kasan.vmapple \
        analysis/kernel.kasan.vmapple.dwarf.elf

Then:

    # Dump the DIEs of a compilation unit (fnmatch on the CU name)
    tools/kasan_dwarf.py --cu '*amcc_rorgn_ppl.c' --depth 4

    # Dump one DIE by its .debug_info offset
    tools/kasan_dwarf.py --offset 0x8d2b42 --depth 5

    # Decode every mach_assert_default descriptor whose symbol contains
    # the given substring (needs llvm-nm on the kasan kernel image)
    tools/kasan_dwarf.py --desc lock_mmu

The assert descriptors live in __DATA_CONST and hold dyld chained
pointers; this tool decodes them with the kernel image base from the
Mach-O header.
"""
import argparse
import fnmatch
import struct
import subprocess
import sys

DEFAULT_ELF = "analysis/kernel.kasan.vmapple.dwarf.elf"
DEFAULT_KERNEL = "kdk/root/System/Library/Kernels/kernel.kasan.vmapple"


def tag(die):
    return die.tag.replace("DW_TAG_", "")


def sval(die, name):
    a = die.attributes.get(name)
    if a is None:
        return None
    v = a.value
    return v.decode("utf-8", "replace") if isinstance(v, bytes) else v


def die_at(cu, ref):
    """Resolve a CU-relative or absolute .debug_info reference."""
    try:
        return cu.get_DIE_from_refaddr(ref)
    except Exception:
        return cu.get_DIE_from_refaddr(ref + cu.cu_offset)


def type_name(cu, die, depth=0):
    t = die.attributes.get("DW_AT_type")
    if t is None or depth > 12:
        return None
    try:
        td = die_at(cu, t.value)
    except Exception:
        return "?"
    n = sval(td, "DW_AT_name")
    if n:
        return n
    if td.tag == "DW_TAG_pointer_type":
        return (type_name(cu, td, depth + 1) or "void") + " *"
    if td.tag == "DW_TAG_const_type":
        return "const " + (type_name(cu, td, depth + 1) or "")
    if td.tag == "DW_TAG_array_type":
        return (type_name(cu, td, depth + 1) or "?") + "[]"
    return tag(td)


def origin(cu, die):
    o = die.attributes.get("DW_AT_abstract_origin") or die.attributes.get(
        "DW_AT_specification")
    if o is None:
        return None
    try:
        return die_at(cu, o.value)
    except Exception:
        return None


def walk(cu, die, depth, maxdepth):
    name = sval(die, "DW_AT_name")
    org = origin(cu, die)
    disp = name or (sval(org, "DW_AT_name") if org is not None else None)
    tname = type_name(cu, die)
    extra = []
    if die.tag == "DW_TAG_inlined_subroutine":
        extra.append("call=%s:%s" % (sval(die, "DW_AT_call_line"),
                                     sval(die, "DW_AT_call_column")))
    if die.tag == "DW_TAG_variable" and "DW_AT_const_value" in die.attributes:
        extra.append("const=%s" % die.attributes["DW_AT_const_value"].value)
    if "DW_AT_low_pc" in die.attributes:
        extra.append("pc=%#x" % die.attributes["DW_AT_low_pc"].value)
    line = sval(die, "DW_AT_decl_line")
    col = sval(die, "DW_AT_decl_column")
    print("%s%s %s%s%s%s" % (
        "  " * depth, tag(die), disp or "",
        (" <%s>" % tname) if tname else "",
        (" line=%s%s" % (line, (":%s" % col) if col is not None else "")) if line else "",
        (" " + " ".join(extra)) if extra else ""))
    if depth >= maxdepth:
        return
    for child in die.iter_children():
        walk(cu, child, depth + 1, maxdepth)


def dump_cu(dw, cu, depth):
    walk(cu, cu.get_top_DIE(), 0, depth)


def dump_offset(dw, off, depth):
    for cu in dw.iter_CUs():
        if cu.cu_offset <= off < cu.cu_offset + cu.size:
            walk(cu, cu.get_DIE_from_refaddr(off), 0, depth)
            return
    sys.exit("offset %#x is not inside any CU" % off)


def find_cu(dw, die, depth):
    for cu in dw.iter_CUs():
        n = sval(cu.get_top_DIE(), "DW_AT_name") or ""
        if fnmatch.fnmatch(n, die):
            dump_cu(dw, cu, depth)


def desc(kernel, elf_glob):
    from macho import MachO  # local tools/macho.py

    m = MachO(kernel)
    base = m.base

    def target(raw):
        return (raw & ((1 << 43) - 1)) | (((raw >> 43) & 0xff) << 56)

    nm = subprocess.run(["llvm-nm", "-n", kernel], capture_output=True,
                        text=True).stdout
    for ln in nm.splitlines():
        p = ln.split()
        if len(p) < 3 or "__desc" not in p[2]:
            continue
        if elf_glob not in p[2]:
            continue
        a = int(p[0], 16)
        # mach_assert_default: type u8, lineno u24, filename ptr, expr ptr
        b = m.read(a, 0x14)
        lineno = b[1] | (b[2] << 8) | (b[3] << 16)
        fn = struct.unpack_from("<Q", b, 4)[0]
        ex = struct.unpack_from("<Q", b, 0xc)[0]
        print("%#x line=%d %s: %s" % (
            a, lineno,
            m.cstring(base + target(fn)).rsplit("/", 1)[-1],
            m.cstring(base + target(ex))))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--elf", default=DEFAULT_ELF)
    ap.add_argument("--kernel", default=DEFAULT_KERNEL)
    ap.add_argument("--cu")
    ap.add_argument("--offset", type=lambda x: int(x, 0))
    ap.add_argument("--desc")
    ap.add_argument("--depth", type=int, default=4)
    a = ap.parse_args()

    if a.desc:
        desc(a.kernel, a.desc)
        return

    sys.path.insert(0, "tools")
    from elftools.elf.elffile import ELFFile

    with open(a.elf, "rb") as f:
        dw = ELFFile(f).get_dwarf_info()
        if a.offset is not None:
            dump_offset(dw, a.offset, a.depth)
        elif a.cu:
            find_cu(dw, a.cu, a.depth)
        else:
            ap.error("one of --cu, --offset or --desc is required")


if __name__ == "__main__":
    main()
