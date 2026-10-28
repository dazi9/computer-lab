"""解析 ELF32 节表:看 0x80000000 到底放了什么(诊断孤儿节排序问题)。"""
import os
import struct


def dump(path):
    f = open(path, 'rb').read()
    shoff, = struct.unpack_from('<I', f, 0x20)
    shentsize, shnum, shstrndx = struct.unpack_from('<HHH', f, 0x2E)
    secs = []
    for i in range(shnum):
        base = shoff + i * shentsize
        name_off, styp, flags, addr, off, size = struct.unpack_from('<6I', f, base)
        secs.append((name_off, styp, flags, addr, off, size))
    str_off = secs[shstrndx][4]

    def name(n):
        end = f.index(b'\0', str_off + n)
        return f[str_off + n:end].decode()

    print('==', path)
    for s in secs:
        n, t, fl, addr, off, size = s
        if size and n:
            print('  %-16s addr=%08X off=%06X size=%5d flags=%X'
                  % (name(n), addr, off, size, fl))


if __name__ == '__main__':
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    default = os.path.join(os.path.dirname(here), 'riscv', 'c', 'kern.elf')
    for p in (sys.argv[1:] or [default]):
        dump(p)
