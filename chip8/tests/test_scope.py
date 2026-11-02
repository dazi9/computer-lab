"""scope 显微镜纯函数测试:反汇编 / 位分解 / diff / 布局 / 面板。"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chip8.cpu import Chip8                                    # noqa: E402
from chip8.emu import strip_ansi                               # noqa: E402
from chip8.scope import (SCOPE_H, SCOPE_W, diff_changed, disasm,  # noqa: E402
                         fit_scope, nibbles, panels, region, snapshot)

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


@test
def disasm_covers_every_family():
    cases = [
        (0x00E0, 'CLS'), (0x00EE, 'RET'),
        (0x1234, 'JP 0x234'), (0x2123, 'CALL 0x123'),
        (0x3012, 'SE V0,0x12'), (0x4012, 'SNE V0,0x12'),
        (0x5010, 'SE V0,V1'), (0x9AB0, 'SNE VA,VB'),
        (0x6012, 'LD V0,0x12'), (0x7A05, 'ADD VA,0x05'),
        (0x8010, 'LD V0,V1'), (0x8121, 'OR V1,V2'), (0x8232, 'AND V2,V3'),
        (0x8343, 'XOR V3,V4'), (0x8454, 'ADD V4,V5'), (0x8565, 'SUB V5,V6'),
        (0x8676, 'SHR V6'), (0x8787, 'SUBN V7,V8'), (0x88EE, 'SHL V8'),
        (0xA123, 'LD I,0x123'), (0xB123, 'JP V0,0x123'), (0xC012, 'RND V0,0x12'),
        (0xD016, 'DRW V0,V1,6'),
        (0xE09E, 'SKP V0'), (0xE0A1, 'SKNP V0'),
        (0xF007, 'LD V0,DT'), (0xF00A, 'LD V0,K'), (0xF015, 'LD DT,V0'),
        (0xF018, 'LD ST,V0'), (0xF01E, 'ADD I,V0'), (0xF029, 'LD F,V0'),
        (0xF033, 'BCD V0'), (0xF255, 'LD [I],V0-V2'), (0xF365, 'LD V0-V3,[I]'),
        (0x0000, 'DW 0x0000'), (0x8FF9, 'DW 0x8FF9'), (0xF0FF, 'DW 0xF0FF'),
    ]
    for op, want in cases:
        assert disasm(op) == want, '0x%04X → %r ≠ %r' % (op, disasm(op), want)


@test
def nibbles_split_four_groups():
    nb = nibbles(0xD016)
    assert (nb['hi'], nb['x'], nb['y'], nb['n']) == (0xD, 0, 1, 6)
    assert nb['nn'] == 0x16 and nb['nnn'] == 0x016
    assert nb['bits'] == '1101 0000 0001 0110'
    assert len(nb['labels']) == len(nb['bits'])    # 标签与位逐列对齐
    assert 'hi' in nb['labels'] and 'n' in nb['labels']


@test
def diff_changed_reports_indices():
    assert diff_changed([1, 2, 3], [1, 9, 3]) == {1}
    assert diff_changed(None, [1, 2]) == set()     # 首帧无旧快照,不标
    assert diff_changed([1], [1, 2]) == set()      # 越界部分不比


@test
def region_annotations():
    assert region(0x050) == '字模'
    assert region(0x0A0) == 'RAM'
    assert region(0x200) == 'ROM'


@test
def fit_scope_thresholds():
    assert not fit_scope(SCOPE_W - 1, 100)
    assert not fit_scope(SCOPE_W, SCOPE_H - 1)
    assert fit_scope(SCOPE_W, SCOPE_H)
    assert fit_scope(200, 60)


@test
def snapshot_reads_cpu_state():
    cpu = Chip8()
    cpu.load(bytes([0xD0, 0x16]))                  # DRW V0,V1,6
    cpu.v[1] = 4
    cpu.i = 0x236
    view = dict(paused=True, cur=0x200, bps=set(), ips=8, dump='i', msg='')
    snap = snapshot(cpu, view)
    assert snap['op'] == 0xD016
    assert snap['pc'] == 0x200 and snap['i'] == 0x236
    assert snap['dump'][0] == 0x236 and snap['dump'][1] == 0x230   # 16 对齐
    assert snap['code'][0] == 0x1FA                # 光标上留 3 条上下文


@test
def panels_compose_all_panes():
    cpu = Chip8()
    cpu.load(bytes([0xD0, 0x16]))
    view = dict(paused=True, cur=0x200, bps={0x204}, ips=8, dump='i', msg='')
    snap = snapshot(cpu, view)
    blank = [' ' * 64] * 16
    lines, foot = panels(snap, None, view, blank)
    plain = strip_ansi('\n'.join(lines))
    assert '→ 0200' in plain and 'DRW V0,V1,6' in plain
    assert '● 0204' in plain                       # 断点标记
    assert 'V0 00' in plain and 'I 000' in plain   # 寄存器列
    assert '内存 @000(RAM)' in plain               # hexdump 列
    assert '1101 0000 0001 0110' in plain          # 位分解
    assert all('已暂停' in f or 'PC' in f for f in foot)
    assert str(len(view['bps'])) in foot[1]


@test
def panels_highlight_changed_atoms():
    cpu = Chip8()
    cpu.load(bytes([0x60, 0x09]))                  # LD V0,9
    view = dict(paused=True, cur=0x200, bps=set(), ips=8, dump='i', msg='')
    snap1 = snapshot(cpu, view)
    cpu.step()                                     # V0 ← 9,pc → 202
    snap2 = snapshot(cpu, view)
    blank = [' ' * 64] * 16
    colored = '\n'.join(panels(snap2, snap1, view, blank)[0])
    assert '\x1b[33m' in colored                   # 变化过的原子染黄
    assert 'V0 09' in strip_ansi(colored)
    same = '\n'.join(panels(snap2, snap2, view, blank)[0])
    assert '\x1b[33m' not in same                  # 没变化就不标


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
