#!/usr/bin/env python3
"""Convert the __DWARF sections of a thin Mach-O dSYM into a synthetic ELF.

pyelftools can then parse the DWARF with its normal ELF code path.  Apple
dSYMs are thin 64-bit Mach-O files whose __DWARF segment holds standard
DWARF sections.  Mach-O limits section names to 16 bytes, so names such as
__debug_str_offs map onto .debug_str_offsets.
"""
import argparse
import os
import struct
import sys

MH_MAGIC_64 = 0xFEEDFACF
LC_SEGMENT_64 = 0x19

# Mach-O section name (16-byte field) -> ELF/DWARF section name.
SECTION_MAP = {
    "__debug_info": ".debug_info",
    "__debug_abbrev": ".debug_abbrev",
    "__debug_str": ".debug_str",
    "__debug_str_offs": ".debug_str_offsets",
    "__debug_addr": ".debug_addr",
    "__debug_line": ".debug_line",
    "__debug_line_str": ".debug_line_str",
    "__debug_rnglists": ".debug_rnglists",
    "__debug_loclists": ".debug_loclists",
    "__debug_aranges": ".debug_aranges",
    "__debug_frame": ".debug_frame",
    "__debug_names": ".debug_names",
}


def parse_sections(path):
    with open(path, "rb") as f:
        data = f.read()
    if len(data) < 32:
        raise ValueError("file too small")
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic != MH_MAGIC_64:
        raise ValueError("not a thin 64-bit little-endian Mach-O (magic %#x)" % magic)
    ncmds, sizeofcmds = struct.unpack_from("<II", data, 16)
    off = 32
    sections = {}
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        if cmd == LC_SEGMENT_64:
            segname = data[off + 8:off + 24].split(b"\0", 1)[0].decode("ascii", "replace")
            nsects = struct.unpack_from("<I", data, off + 64)[0]
            soff = off + 72
            for _ in range(nsects):
                sectname = data[soff:soff + 16].split(b"\0", 1)[0].decode("ascii", "replace")
                sseg = data[soff + 16:soff + 32].split(b"\0", 1)[0].decode("ascii", "replace")
                addr, size = struct.unpack_from("<QQ", data, soff + 32)
                fileoff = struct.unpack_from("<I", data, soff + 48)[0]
                if sseg == "__DWARF" or sectname.startswith("__debug"):
                    blob = data[fileoff:fileoff + size]
                    if len(blob) != size:
                        raise ValueError("truncated section %s" % sectname)
                    sections[sectname] = blob
                soff += 80
        off += cmdsize
    return sections


def build_elf(sections):
    names = ["", ".shstrtab"]
    blobs = [b"", None]
    for macho_name, elf_name in SECTION_MAP.items():
        if macho_name in sections:
            names.append(elf_name)
            blobs.append(sections[macho_name])
    shstr = b"\0"
    name_off = {}
    for n in names:
        if n == "":
            name_off[n] = 0
            continue
        name_off[n] = len(shstr)
        shstr += n.encode() + b"\0"
    blobs[1] = shstr

    ehdr_size = 64
    body = bytearray()
    offsets = []
    cur = ehdr_size
    for b in blobs:
        cur = (cur + 7) & ~7
        pad = cur - (ehdr_size + len(body))
        body += b"\0" * pad
        offsets.append(cur)
        body += b
        cur += len(b)
    shoff = (ehdr_size + len(body) + 7) & ~7
    shnum = len(blobs)
    shstrndx = 1
    ehdr = struct.pack(
        "<16sHHIQQQIHHHHHH",
        b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\0" * 8,
        1, 183, 1, 0, 0, shoff, 0, 64, 0, 0, 64, shnum, shstrndx,
    )
    out = bytearray(ehdr)
    out += body
    out += b"\0" * (shoff - len(out))
    # null section header
    out += b"\0" * 64
    for i in range(1, shnum):
        name = names[i]
        out += struct.pack(
            "<IIQQQQIIQQ",
            name_off[name], 1, 0, 0, offsets[i], len(blobs[i]),
            0, 0, 8, 0,
        )
    return bytes(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dsym")
    ap.add_argument("out")
    args = ap.parse_args()
    sections = parse_sections(args.dsym)
    if "__debug_info" not in sections:
        sys.exit("no __debug_info section found")
    elf = build_elf(sections)
    with open(args.out, "wb") as f:
        f.write(elf)
    print("wrote %s (%d bytes) from %d DWARF sections" % (args.out, len(elf), len(sections)))
    for name in sorted(sections):
        mapped = SECTION_MAP.get(name, "?")
        print("  %-20s %-22s %8d bytes" % (name, mapped, len(sections[name])))


if __name__ == "__main__":
    main()
