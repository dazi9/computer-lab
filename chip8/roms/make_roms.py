"""把内置汇编源汇编成 roms/*.ch8。运行:python3 roms/make_roms.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from chip8.asm import BOUNCE_SRC, PADDLE_SRC, assemble  # noqa: E402

here = os.path.dirname(os.path.abspath(__file__))
for name, src in (('bounce.ch8', BOUNCE_SRC), ('paddle.ch8', PADDLE_SRC)):
    rom = assemble(src)
    path = os.path.join(here, name)
    with open(path, 'wb') as f:
        f.write(rom)
    print('写出 %s(%d 字节)' % (path, len(rom)))
