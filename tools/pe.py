import struct, sys

class PE:
    def __init__(self, path):
        self.data = open(path,'rb').read()
        d = self.data
        pe = struct.unpack_from('<I', d, 0x3c)[0]
        assert d[pe:pe+4] == b'PE\0\0'
        machine, nsec, _, _, _, optsz, _ = struct.unpack_from('<HHIIIHH', d, pe+4)
        opt = pe+24
        magic = struct.unpack_from('<H', d, opt)[0]
        assert magic == 0x20b, 'expect PE32+'
        self.image_base = struct.unpack_from('<Q', d, opt+24)[0]
        self.sections = []
        so = opt + optsz
        for i in range(nsec):
            o = so + i*40
            name = d[o:o+8].rstrip(b'\0').decode('ascii','replace')
            vsize, vaddr, rsize, raddr = struct.unpack_from('<IIII', d, o+8)
            self.sections.append((name, vaddr, vsize, raddr, rsize))

    def rva_to_off(self, rva):
        for name, va, vs, ra, rs in self.sections:
            if va <= rva < va + max(vs, rs):
                off = rva - va + ra
                if off < ra + rs:
                    return off
        return None

    def va_to_off(self, va):
        if va < self.image_base: return None
        return self.rva_to_off(va - self.image_base)

    def off_to_va(self, off):
        for name, va, vs, ra, rs in self.sections:
            if ra <= off < ra + rs:
                return self.image_base + va + (off - ra)
        return None
