"""CHIP-8 核心的单元测试:每条指令一族一个用例,直接驱动 CPU 断言效果。

运行:python3 tests/test_cpu.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from chip8.cpu import Chip8  # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def cpu_with(*ops, **kw):
    c = Chip8(**kw)
    c.load(b''.join(o.to_bytes(2, 'big') for o in ops))
    return c


@test
def ld_and_add_imm():
    c = cpu_with(0x6012, 0x7134, 0x7102)
    c.step()
    c.step()
    c.step()
    assert c.v[0] == 0x12 and c.v[1] == 0x36, (hex(c.v[0]), hex(c.v[1]))
    assert c.v[0xF] == 0, '7XNN 不应动 VF'


@test
def add_carry():
    c = cpu_with(0x60FF, 0x6101, 0x8014)
    c.step(); c.step(); c.step()
    assert c.v[0] == 0x00 and c.v[0xF] == 1, (hex(c.v[0]), c.v[0xF])


@test
def sub_and_subn():
    c = cpu_with(0x6005, 0x6106, 0x8015)
    c.step(); c.step(); c.step()
    assert c.v[0] == 0xFF and c.v[0xF] == 0, '5-6 应借位'
    c = cpu_with(0x6006, 0x6105, 0x8015)
    c.step(); c.step(); c.step()
    assert c.v[0] == 0x01 and c.v[0xF] == 1
    c = cpu_with(0x6005, 0x6106, 0x8017)          # SUBN: Vy - Vx
    c.step(); c.step(); c.step()
    assert c.v[0] == 0x01 and c.v[0xF] == 1


@test
def shifts():
    c = cpu_with(0x6103, 0x8106)                  # 现代行为:移位 Vx 自己
    c.step(); c.step()
    assert c.v[1] == 0x01 and c.v[0xF] == 1
    c = cpu_with(0x60C0, 0x800E)
    c.step(); c.step()
    assert c.v[0] == 0x80 and c.v[0xF] == 1
    c = cpu_with(0x6010, 0x8106, shift_legacy=True)   # 老机型:取 Vy 作源
    c.step(); c.step()
    assert c.v[1] == 0x08 and c.v[0xF] == 0


@test
def logic_ops():
    c = cpu_with(0x60F0, 0x613C, 0x8011)
    c.step(); c.step(); c.step()
    assert c.v[0] == 0xFC                          # OR
    c = cpu_with(0x60F0, 0x613C, 0x8012)
    c.step(); c.step(); c.step()
    assert c.v[0] == 0x30                          # AND
    c = cpu_with(0x60F0, 0x613C, 0x8013)
    c.step(); c.step(); c.step()
    assert c.v[0] == 0xCC                          # XOR
    c = cpu_with(0x6099, 0x8100)                   # LD Vx, Vy
    c.step(); c.step()
    assert c.v[0] == 0x99


@test
def skip_family():
    c = cpu_with(0x6005, 0x3005, 0x60FF)           # 3XNN 相等 → 跳过下一条
    c.step(); c.step()
    assert c.v[0] == 5 and c.pc == 0x206, (c.v[0], hex(c.pc))
    c = cpu_with(0x6005, 0x4005, 0x60FF)           # 4XNN 不等才跳
    c.step(); c.step(); c.step()
    assert c.v[0] == 0xFF
    c = cpu_with(0x6005, 0x6105, 0x5010, 0x60FF)   # 5XY0 相等 → 跳
    c.step(); c.step(); c.step()
    assert c.v[0] == 5 and c.pc == 0x208
    c = cpu_with(0x6005, 0x6106, 0x9010, 0x60FF)   # 9XY0 不等 → 跳
    c.step(); c.step(); c.step()
    assert c.v[0] == 5 and c.pc == 0x208


@test
def jp_call_ret():
    c = Chip8()
    c.load(bytes([0x22, 0x10, 0x60, 0xFF]))        # CALL 0x210; 返回后 LD V0,FF
    c.mem[0x210:0x212] = bytes([0x00, 0xEE])
    c.step()
    assert c.pc == 0x210 and c.stack == [0x202]
    c.step()                                       # RET
    assert c.pc == 0x202 and c.stack == []
    c.step()                                       # LD V0, FF
    assert c.v[0] == 0xFF


@test
def jp_bnnn_and_i():
    c = cpu_with(0x6003, 0xB204)
    c.step(); c.step()
    assert c.pc == 0x207                           # 0x204 + V0(3)
    c = cpu_with(0xAABC)
    c.step()
    assert c.i == 0xABC


@test
def rnd_mask():
    c = cpu_with(0xC00F)
    c.step()
    assert 0 <= c.v[0] <= 0x0F, hex(c.v[0])


@test
def draw_erase_collide_wrap():
    c = Chip8()
    c.load(bytes([0xA4, 0x00, 0xD0, 0x12]))        # I=0x400,DRW V0,V0,2
    c.mem[0x400:0x402] = bytes([0xF0, 0x0F])
    c.step(); c.step()
    assert c.v[0xF] == 0
    lit = [0, 1, 2, 3, 64 + 4, 64 + 7]
    assert all(c.display[k] for k in lit) and sum(c.display) == 8
    c.pc = 0x202                                   # 原地再画一遍 → 全部异或掉
    c.step()
    assert sum(c.display) == 0 and c.v[0xF] == 1

    c2 = Chip8()                                   # 重叠碰撞
    c2.load(bytes([0xA4, 0x00, 0xD0, 0x11, 0x60, 0x02, 0xD0, 0x11]))
    c2.mem[0x400] = 0xFF
    for _ in range(4):
        c2.step()
    assert c2.v[0xF] == 1
    assert c2.display[0] == 1 and c2.display[1] == 1   # 只画过一次
    assert c2.display[2] == 0                          # 被异或两次

    c3 = Chip8()                                   # 逐像素回绕:x=63 起笔
    c3.load(bytes([0x60, 0x3F, 0xA4, 0x00, 0xD0, 0x11]))
    c3.mem[0x400] = 0xFF
    c3.step(); c3.step(); c3.step()
    assert c3.display[63] == 1 and c3.display[0] == 1 and c3.display[6] == 1


@test
def keys_skip():
    c = cpu_with(0x6103, 0xE19E, 0x60FF)           # EX9E:按下 → 跳过
    c.keys[3] = True
    c.step(); c.step()
    assert c.v[0] == 0 and c.pc == 0x206
    c = cpu_with(0x6103, 0xE1A1, 0x60FF)           # EXA1:按下 → 不跳
    c.keys[3] = True
    c.step(); c.step(); c.step()
    assert c.v[0] == 0xFF
    c = cpu_with(0x6103, 0xE1A1, 0x60FF)           # EXA1:没按 → 跳过
    c.step(); c.step()
    assert c.pc == 0x206


@test
def fx_timers_bcd_font():
    c = cpu_with(0x600A, 0xF029)
    c.step(); c.step()
    assert c.i == 0x050 + 0xA * 5, hex(c.i)        # FX29 字模地址
    c = cpu_with(0xA500, 0x60FE, 0xF033)           # BCD:254 → 2,5,4
    c.step(); c.step(); c.step()
    assert (c.mem[0x500], c.mem[0x501], c.mem[0x502]) == (2, 5, 4)
    c = cpu_with(0x6005, 0xF015)                   # DT ← V0
    c.step(); c.step()
    assert c.dt == 5
    c.tick(); c.tick()
    assert c.dt == 3
    c = cpu_with(0xF007)                           # V0 ← DT
    c.dt = 9
    c.step()
    assert c.v[0] == 9
    c = cpu_with(0x6003, 0xF018)                   # ST ← V0
    c.step(); c.step()
    assert c.st == 3


@test
def fx_mem_store_load():
    c = Chip8()
    prog = bytes([0x60, 0x01, 0x61, 0x02, 0x62, 0x03, 0xA4, 0x00, 0xF2, 0x55])
    c.load(prog)
    for _ in range(5):
        c.step()
    assert (c.mem[0x400], c.mem[0x401], c.mem[0x402]) == (1, 2, 3)
    assert c.i == 0x403, '现代行为:FX55 后 I 前进'
    c2 = Chip8(mem_legacy=True)
    c2.load(prog)
    for _ in range(5):
        c2.step()
    assert c2.i == 0x400, '老机型:FX55 后 I 不动'
    c3 = Chip8()
    c3.load(bytes([0xA4, 0x00, 0xF2, 0x65]))
    c3.mem[0x400:0x403] = bytes([7, 8, 9])
    c3.step(); c3.step()
    assert (c3.v[0], c3.v[1], c3.v[2]) == (7, 8, 9) and c3.i == 0x403


@test
def fx0a_waits_and_grabs():
    c = cpu_with(0xF00A)
    c.step()
    assert c.pc == 0x200 and c.v[0] == 0           # 无键:原地等待
    c.keys[0xA] = True
    c.step()
    assert c.v[0] == 0xA and c.pc == 0x202


@test
def cls_and_font_installed():
    c = cpu_with(0x00E0)
    c.display[5] = 1
    c.step()
    assert sum(c.display) == 0
    c2 = Chip8()
    assert c2.mem[0x050] == 0xF0 and len(c2.mem[0x050:0x0A0]) == 80


def main():
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print('PASS', fn.__name__)
        except AssertionError as e:
            failed += 1
            print('FAIL', fn.__name__, '->', e)
    print('---')
    print('%d/%d 组测试通过' % (len(TESTS) - failed, len(TESTS)))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
