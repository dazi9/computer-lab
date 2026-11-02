"""scope 显微镜纯函数测试:反汇编 / 位分解 / diff / 布局 / 面板。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rv.asm import assemble                                     # noqa: E402
from rv.cpu import RAM_BASE, RV32                               # noqa: E402
from rv.emu import strip_ansi                                   # noqa: E402
from rv.scope import (SCOPE_H, SCOPE_W, bit_fields, cause_name,    # noqa: E402
                      diff_changed, disasm, fit_scope, panels, snapshot)


def word(src):
    """汇编单条指令 → 32 位指令字(反汇编与汇编器互为镜像)。"""
    return int.from_bytes(assemble(src)[:4], 'little')


TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


@test
def disasm_covers_every_format():
    cases = [
        ('lui a0, 0x12345', 'lui a0,0x12345'),
        ('auipc a1, 0x1', 'auipc a1,0x1'),
        ('addi t0, sp, 8', 'addi t0,sp,8'),
        ('slti a0, a0, -1', 'slti a0,a0,-1'),
        ('srai a2, a2, 3', 'srai a2,a2,3'),
        ('add s0, s1, s2', 'add s0,s1,s2'),
        ('sub t0, t1, t2', 'sub t0,t1,t2'),
        ('mul a0, a1, a2', 'mul a0,a1,a2'),
        ('remu a3, a4, a5', 'remu a3,a4,a5'),
        ('lw a0, 4(sp)', 'lw a0,4(sp)'),
        ('lbu a5, -1(a0)', 'lbu a5,-1(a0)'),
        ('sw a0, 0(sp)', 'sw a0,0(sp)'),
        ('beq a0, a1, 16', None),               # 目标 = pc+imm,单独断言
        ('jal ra, 32', None),
        ('csrrw t0, 0x300, a0', 'csrrw t0,mstatus,a0'),
        ('csrrsi a0, 0x341, 5', 'csrrsi a0,mepc,5'),
        ('wfi', 'wfi'), ('ecall', 'ecall'), ('mret', 'mret'),
    ]
    for src, want in cases:
        got = disasm(word(src), RAM_BASE)
        if want is None:
            assert src.split()[0] in got, (src, got)
        else:
            assert got == want, '%r → %r ≠ %r' % (src, got, want)
    assert disasm(word('beq a0, a1, 16'), RAM_BASE).endswith('0x%X' % (RAM_BASE + 16))
    assert disasm(word('csrrw t0, 0x300, a0'), RAM_BASE) == 'csrrw t0,mstatus,a0'
    assert disasm(word('j 8'), RAM_BASE).startswith('j 0x')
    assert disasm(word('ret'), RAM_BASE) == 'ret'
    assert disasm(0xFFFFFFFF, RAM_BASE).startswith('.word')   # 未知不装懂


@test
def bit_fields_group_by_format():
    b, labels = bit_fields(word('add s0, s1, s2'))            # R 型
    assert len(b) == len(labels) == 37                        # 32 位 + 5 空隙
    assert b.replace(' ', '') == format(word('add s0, s1, s2'), '032b')
    assert 'f7' in labels and 'rs2' in labels and 'op' in labels
    b, labels = bit_fields(word('addi t0, sp, 8'))            # I 型
    assert 'imm' in labels and 'rs1' in labels
    b, labels = bit_fields(word('lw a0, 4(sp)'))              # load 也是 I 型
    assert b.replace(' ', '') == format(word('lw a0, 4(sp)'), '032b')
    b, labels = bit_fields(word('sw a0, 0(sp)'))              # S 型
    assert 'imm7' in labels and 'imm5' in labels
    b, labels = bit_fields(word('beq a0, a1, 8'))             # B 型
    assert 'imm7' in labels and 'imm5' in labels
    b, labels = bit_fields(word('lui a0, 0x1'))               # U 型
    assert 'imm20' in labels and 'rd' in labels
    b, labels = bit_fields(word('jal ra, 8'))                 # J 型
    assert 'imm11' in labels and 'imm8' in labels
    b, labels = bit_fields(word('csrrw t0, 0x300, a0'))       # SYSTEM:csr 字段
    assert 'csr' in labels
    b, labels = bit_fields(0xFFFFFFFF)
    assert '.word' in labels and ' ' not in b.strip()


@test
def diff_changed_reports_indices():
    assert diff_changed([1, 2, 3], [1, 9, 3]) == {1}
    assert diff_changed(None, [1, 2]) == set()
    assert diff_changed([1], [1, 2]) == set()


@test
def cause_name_translates_mcause():
    assert cause_name((1 << 31) | 7) == '定时中断'
    assert cause_name((1 << 31) | 8) == 'ecall'
    assert cause_name(2) == '非法指令'
    assert cause_name(0) == '异常'


@test
def fit_scope_thresholds():
    assert not fit_scope(SCOPE_W - 1, 100)
    assert not fit_scope(SCOPE_W, SCOPE_H - 1)
    assert fit_scope(SCOPE_W, SCOPE_H)
    assert fit_scope(200, 60)


@test
def snapshot_reads_cpu_state():
    cpu = RV32(ram_size=1 << 16)
    cpu.load(assemble('addi a0, zero, 42\necall'))
    cpu.x[2] = RAM_BASE + 0x1000                              # sp 指向 RAM
    view = dict(paused=True, cur=RAM_BASE, bps=set(), spf=4000, dump='sp', msg='')
    snap = snapshot(cpu, view)
    assert snap['pc'] == RAM_BASE
    assert snap['op'] == word('addi a0, zero, 42')
    assert snap['words'][0] == (RAM_BASE, snap['op'])
    assert snap['dump'][0] == cpu.x[2] and snap['dump'][1] == 'RAM'
    assert snap['mode'] == 3 and not snap['halted']


@test
def panels_compose_all_panes():
    cpu = RV32(ram_size=1 << 16)
    cpu.load(assemble('addi a0, zero, 42\necall'))
    cpu.x[2] = RAM_BASE + 0x1000                              # sp 指向 RAM
    view = dict(paused=True, cur=RAM_BASE, bps={RAM_BASE + 4}, spf=4000,
                dump='sp', msg='')
    snap = snapshot(cpu, view)
    blank = [' ' * 64] * 16
    lines, foot = panels(snap, None, view, blank)
    plain = strip_ansi('\n'.join(lines))
    assert '→ %08X' % RAM_BASE in plain and 'addi a0,zero,42' in plain
    assert ('● %08X' % (RAM_BASE + 4)) in plain               # 断点标记
    assert 'x10' in plain and 'zero' in plain                 # 寄存器列(x 系 + ABI 名)
    assert 'mstatus' in plain and 'mtvec' in plain            # CSR 列
    assert '特权 M' in plain
    assert ('内存 @%08X' % cpu.x[2]) in plain                 # hexdump 列
    assert '已暂停' in ''.join(foot)


@test
def panels_highlight_changed_atoms():
    cpu = RV32(ram_size=1 << 16)
    cpu.load(assemble('addi a0, zero, 42'))
    view = dict(paused=True, cur=RAM_BASE, bps=set(), spf=4000, dump='sp', msg='')
    snap1 = snapshot(cpu, view)
    cpu.step()                                                # a0 ← 42,pc +4
    snap2 = snapshot(cpu, view)
    blank = [' ' * 64] * 16
    colored = '\n'.join(panels(snap2, snap1, view, blank)[0])
    assert '\x1b[33m' in colored                              # 变化的原子染黄
    assert '0000002A' in strip_ansi(colored)                  # a0 的新值可见
    same = '\n'.join(panels(snap2, snap2, view, blank)[0])
    assert '\x1b[33m' not in same                             # 没变化就不标


def main():
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print('PASS', fn.__name__)
        except AssertionError as e:
            failed += 1
            print('FAIL', fn.__name__, '-', e)
    print('%d/%d 组测试通过' % (len(TESTS) - failed, len(TESTS)))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
