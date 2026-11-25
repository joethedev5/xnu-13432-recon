#!/usr/bin/env python3
"""Minimal thin Mach-O reader with arm64e kernel chained-pointer decoding."""
import struct

MH_MAGIC_64 = 0xFEEDFACF
LC_SEGMENT_64 = 0x19
DYLD_CHAINED_PTR_ARM64E_KERNEL = 7


class Segment:
    __slots__ = ("name", "vmaddr", "vmsize", "fileoff", "filesize")

    def __init__(self, name, vmaddr, vmsize, fileoff, filesize):
        self.name = name
        self.vmaddr = vmaddr
        self.vmsize = vmsize
        self.fileoff = fileoff
        self.filesize = filesize


class MachO:
    def __init__(self, path):
        self.data = open(path, "rb").read()
        magic = struct.unpack_from("<I", self.data, 0)[0]
        if magic != MH_MAGIC_64:
            raise ValueError("not a thin 64-bit little-endian Mach-O")
        ncmds = struct.unpack_from("<I", self.data, 16)[0]
        off = 32
        self.segments = []
        for _ in range(ncmds):
            cmd, cmdsize = struct.unpack_from("<II", self.data, off)
            if cmd == LC_SEGMENT_64:
                name = self.data[off + 8:off + 24].split(b"\0", 1)[0].decode("ascii", "replace")
                vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", self.data, off + 24)
                self.segments.append(Segment(name, vmaddr, vmsize, fileoff, filesize))
            off += cmdsize
        self.base = self.segments[0].vmaddr if self.segments else 0

    def read(self, addr, size):
        for s in self.segments:
            if s.vmaddr <= addr and addr + size <= s.vmaddr + s.filesize:
                o = s.fileoff + (addr - s.vmaddr)
                return self.data[o:o + size]
        raise ValueError("address %#x size %d not file-backed" % (addr, size))

    def u64(self, addr):
        return struct.unpack("<Q", self.read(addr, 8))[0]

    def u32(self, addr):
        return struct.unpack("<I", self.read(addr, 4))[0]

    def cstring(self, addr, limit=4096):
        out = bytearray()
        while len(out) < limit:
            b = self.read(addr + len(out), 1)[0]
            if b == 0:
                break
            out.append(b)
        return out.decode("utf-8", "replace")

    def decode_ptr(self, addr):
        """Decode one DYLD_CHAINED_PTR_ARM64E_KERNEL pointer (imports_count==0)."""
        v = self.u64(addr)
        auth = (v >> 63) & 1
        bind = (v >> 62) & 1
        nxt = (v >> 51) & 0x7FF
        if bind:
            return {"raw": v, "auth": auth, "bind": True, "target": None,
                    "addr": None, "next": nxt}
        if auth:
            target = v & 0xFFFFFFFF
            return {"raw": v, "auth": True, "bind": False, "target": target,
                    "addr": (self.base + target) & ((1 << 64) - 1), "next": nxt}
        target = v & ((1 << 43) - 1)
        high8 = (v >> 43) & 0xFF
        return {"raw": v, "auth": False, "bind": False,
                "target": target | (high8 << 56),
                "addr": (self.base + (target | (high8 << 56))) & ((1 << 64) - 1),
                "next": nxt}
