"""CHIP-8 原子级显微镜(--scope):把虚拟机拆开给你看的调试器。

    python3 -m chip8.emu roms/bounce.ch8 --scope

面板:反汇编窗口(8 条,跟随光标)+ V0-VF/PC/I/DT/ST 寄存器列
+ 16 位 nibble 分解(hi/x/y/n 逐位)+ 64x32 屏 + 内存 hexdump
(跟随 I 或 PC)。变化过的寄存器、定时器与内存字节染成黄色,
I 指向的字节染青色,断点行标红——"每个原子动了都看得见"。

热键:空格 暂停/继续,n 单步一条,j/k 移动反汇编光标,b 在光标处
切换断点,g 切换 hexdump 跟随(I↔PC),+/- 调速,ESC 退出。
游戏键 1234/qwer/asdf/zxcv 照常可用(运行中还能玩)。

渲染复用 emu.paint 的绝对定位约定:raw 模式全程无换行符,每行
ESC[行;列H 定位 + 清到行尾。disasm/nibbles/diff_changed/panels
都是纯函数,panels 只吃普通数据——测试不需要 CPU 实例。
"""
import os
import shutil
import sys

from .cpu import W
from .emu import dwidth, half_block_frame, paint

DIM, RESET = '\x1b[2m', '\x1b[0m'
CYA, YEL, RED = '\x1b[36m', '\x1b[33m', '\x1b[31m'


def pad(s, w):
    """按可见宽度补空格(ljust 会被颜色序列骗到)。"""
    return s + ' ' * max(0, w - dwidth(s))

DISASM_ROWS = 8                              # 反汇编窗口行数
HEX_ROWS = 4                                 # hexdump 行数(每行 8 字节)
W_DIS, W_REG, W_HEX = 26, 22, 40             # 顶块三列宽度
GAP = '  '
SCOPE_W = W_DIS + len(GAP) + W_REG + len(GAP) + W_HEX
REG_ROWS = 11                                # 寄存器列行数(决定顶块高度)
SCOPE_H = REG_ROWS + 1 + 16 + 2              # 顶块 + 空行 + 屏(半块 16 行)+ foot


def disasm(op):
    """opcode → 助记符,覆盖 cpu._exec 实现的全部指令;未知给 DW。"""
    hi, x, y, n = op >> 12, (op >> 8) & 0xF, (op >> 4) & 0xF, op & 0xF
    nn, nnn = op & 0xFF, op & 0xFFF
    vx, vy = 'V%X' % x, 'V%X' % y
    if op == 0x00E0:
        return 'CLS'
    if op == 0x00EE:
        return 'RET'
    if hi == 0x1:
        return 'JP 0x%03X' % nnn
    if hi == 0x2:
        return 'CALL 0x%03X' % nnn
    if hi == 0x3:
        return 'SE %s,0x%02X' % (vx, nn)
    if hi == 0x4:
        return 'SNE %s,0x%02X' % (vx, nn)
    if hi == 0x5 and n == 0:
        return 'SE %s,%s' % (vx, vy)
    if hi == 0x6:
        return 'LD %s,0x%02X' % (vx, nn)
    if hi == 0x7:
        return 'ADD %s,0x%02X' % (vx, nn)
    if hi == 0x8:
        m = {0: 'LD', 1: 'OR', 2: 'AND', 3: 'XOR', 4: 'ADD',
             5: 'SUB', 6: 'SHR', 7: 'SUBN', 0xE: 'SHL'}.get(n)
        if m is None:
            return 'DW 0x%04X' % op
        if n in (6, 0xE):                    # 移位只写一个操作数
            return '%s %s' % (m, vx)
        return '%s %s,%s' % (m, vx, vy)
    if hi == 0x9 and n == 0:
        return 'SNE %s,%s' % (vx, vy)
    if hi == 0xA:
        return 'LD I,0x%03X' % nnn
    if hi == 0xB:
        return 'JP V0,0x%03X' % nnn
    if hi == 0xC:
        return 'RND %s,0x%02X' % (vx, nn)
    if hi == 0xD:
        return 'DRW %s,%s,%d' % (vx, vy, n)
    if hi == 0xE:
        if nn == 0x9E:
            return 'SKP %s' % vx
        if nn == 0xA1:
            return 'SKNP %s' % vx
        return 'DW 0x%04X' % op
    if hi == 0xF:
        m = {0x07: 'LD %s,DT', 0x0A: 'LD %s,K', 0x15: 'LD DT,%s',
             0x18: 'LD ST,%s', 0x1E: 'ADD I,%s', 0x29: 'LD F,%s',
             0x33: 'BCD %s', 0x55: 'LD [I],V0-%s', 0x65: 'LD V0-%s,[I]'}.get(nn)
        if m is None:
            return 'DW 0x%04X' % op
        return m % vx
    return 'DW 0x%04X' % op


def nibbles(op):
    """16 位按 hi/x/y/n 四组 4bit 分解 → 字段值 + 逐位展示两行。"""
    b = format(op, '016b')
    bits = ' '.join(b[i * 4:(i + 1) * 4] for i in range(4))
    labels = ' '.join(t.center(4) for t in ('hi', 'x', 'y', 'n'))
    return dict(hi=op >> 12, x=(op >> 8) & 0xF, y=(op >> 4) & 0xF, n=op & 0xF,
                nn=op & 0xFF, nnn=op & 0xFFF, bits=bits, labels=labels)


def diff_changed(old, new):
    """两份等长序列 → 发生变化的下标集合;旧快照缺失则不标。"""
    if old is None:
        return set()
    return {k for k in range(min(len(old), len(new))) if old[k] != new[k]}


def region(addr):
    """内存区域注释:字模区 / ROM 区 / 其余 RAM。"""
    if 0x050 <= addr < 0x0A0:
        return '字模'
    if addr >= 0x200:
        return 'ROM'
    return 'RAM'


def snapshot(cpu, view):
    """CPU → 普通数据快照(panels 只吃这个,测试不用造 CPU)。"""
    cur = view['cur'] & 0xFFE
    code_start = (cur - (DISASM_ROWS // 2 - 1) * 2) & 0xFFE
    code = bytes(cpu.mem[code_start:code_start + DISASM_ROWS * 2])
    dump_addr = cpu.i if view['dump'] == 'i' else cpu.pc
    dump_start = dump_addr & 0xFF0
    return dict(v=list(cpu.v), i=cpu.i, pc=cpu.pc, dt=cpu.dt, st=cpu.st,
                stack=list(cpu.stack), cycles=cpu.cycles,
                op=(cpu.mem[cpu.pc] << 8) | cpu.mem[(cpu.pc + 1) & 0xFFF],
                code=(code_start, code),
                dump=(dump_addr, dump_start, bytes(cpu.mem[dump_start:dump_start + 32])))


def _disasm_lines(snap, view):
    start, code = snap['code']
    out = []
    for k in range(DISASM_ROWS):
        addr = (start + 2 * k) & 0xFFF
        op = (code[2 * k] << 8) | code[2 * k + 1] if 2 * k + 1 < len(code) else 0
        mark = '→' if addr == snap['pc'] else '●' if addr in view['bps'] else ' '
        text = ' %04X %04X %-*s' % (addr, op, W_DIS - 13, disasm(op))
        if addr == snap['pc']:
            out.append(CYA + mark + text + RESET)
        elif addr in view['bps']:
            out.append(RED + mark + text + RESET)
        else:
            out.append(mark + text)
    nb = nibbles(snap['op'])
    out.append(DIM + nb['bits'] + RESET)
    out.append(DIM + nb['labels'] + ' %04X' % snap['op'] + RESET)
    return out


def _reg_lines(snap, prev):
    ch_v = diff_changed(prev['v'] if prev else None, snap['v'])
    out = []

    def cell(k):
        s = 'V%X %02X %3d' % (k, snap['v'][k], snap['v'][k])
        return (YEL + s + RESET) if k in ch_v else s

    pc_s, i_s = 'PC %03X' % snap['pc'], 'I %03X' % snap['i']
    dt_s, st_s = 'DT %02X' % snap['dt'], 'ST %02X' % snap['st']
    sp_s = 'SP %d' % len(snap['stack'])
    if prev:
        if prev['pc'] != snap['pc']:
            pc_s = CYA + pc_s + RESET
        if prev['i'] != snap['i']:
            i_s = CYA + i_s + RESET
        if prev['dt'] != snap['dt']:
            dt_s = YEL + dt_s + RESET
        if prev['st'] != snap['st']:
            st_s = YEL + st_s + RESET
    out += [pad(pc_s, 10) + GAP + pad(i_s, 10),
            pad(dt_s, 10) + GAP + pad(st_s, 10),
            pad(sp_s, 10) + GAP + 'CYC %d' % snap['cycles']]
    if snap['stack']:
        out.append('栈 ' + ' '.join('%03X' % a for a in snap['stack'][-3:]))
    else:
        out.append('栈 (空)')
    for r in range(8):                       # V0-VF 两列
        out.append(pad(cell(r), 10) + GAP + pad(cell(r + 8), 10))
    return out


def _hex_lines(snap, prev):
    addr, start, dump = snap['dump']
    ch = set()
    if prev and prev['dump'][1] == start:
        ch = diff_changed(prev['dump'][2], dump)
    out = ['内存 @%03X(%s)' % (start, region(addr))]
    for r in range(HEX_ROWS):
        row = dump[r * 8:(r + 1) * 8]
        cells, asc = [], []
        for k, b in enumerate(row):
            g = '%02X' % b
            idx = r * 8 + k
            if start + idx == addr:
                g = CYA + g + RESET
            elif idx in ch:
                g = YEL + g + RESET
            cells.append(g)
            asc.append(chr(b) if 32 <= b < 127 else '·')
        out.append('%03X  %s  %s' % (start + r * 8, ' '.join(cells), ''.join(asc)))
    return out


def panels(snap, prev, view, screen_lines):
    """快照 → (整幅面板行, foot 行)。纯函数:只吃 snapshot 的普通数据。"""
    cols = [_disasm_lines(snap, view), _reg_lines(snap, prev), _hex_lines(snap, prev)]
    height = max(len(c) for c in cols)
    top = []
    for r in range(height):
        top.append(GAP.join(pad(c[r], W) if r < len(c) else ' ' * W
                            for c, W in zip(cols, (W_DIS, W_REG, W_HEX))))
    indent = ' ' * ((SCOPE_W - W) // 2)
    lines = top + [''] + [indent + s for s in screen_lines]

    status = '已暂停' if view['paused'] else '运行中'
    if view['msg']:
        status = RED + view['msg'] + RESET
    foot = ['键位: 空格 暂停/继续 | n 单步 | j/k 光标 | b 断点 | g 跟随I/PC | +/- 调速 | ESC 退出',
            'PC %03X | I %03X | %s | IPS %d | 断点 %d | CYC %d'
            % (snap['pc'], snap['i'], status, view['ips'], len(view['bps']), snap['cycles'])]
    return [pad(l, SCOPE_W) for l in lines], foot


def fit_scope(cols, rows):
    return cols >= SCOPE_W and rows >= SCOPE_H


def run_scope(cpu, ips=8, fps=60):
    """显微镜主循环:默认暂停,空格启动;结构照 run_interactive。"""
    import select
    import termios
    import time
    import tty

    from .emu import KEYMAP

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    sys.stdout.write('\x1b[?1049h\x1b[?25l')
    st = dict(paused=True, cur=cpu.pc & 0xFFE, bps=set(), ips=ips,
              dump='i', msg='空格运行,n 单步')
    prev, rview, keys_down = None, None, {}
    try:
        tty.setraw(fd)
        frame_time = 1.0 / fps
        while True:
            t0 = time.monotonic()
            # os.read 整块吃掉 OS 缓冲再逐字符分发:select 看的是文件描述符,
            # sys.stdin.read(1) 走 Python 缓冲层,突发按键会卡在缓冲里不再可读
            while select.select([fd], [], [], 0)[0]:
                chunk = os.read(fd, 4096)
                if not chunk:
                    return
                for ch in chunk.decode('utf-8', 'replace'):
                    if ch in ('\x1b', '\x03'):
                        return
                    if ch == ' ':
                        st['paused'] = not st['paused']
                        st['cur'] = cpu.pc & 0xFFE
                        st['msg'] = ''
                        st['guard'] = cpu.pc      # 继续时跳过当前 PC 上的断点
                    elif ch == 'n':
                        st['paused'] = True
                        st['cur'] = cpu.pc & 0xFFE
                        st['msg'] = ''
                        if cpu.pc in st['bps']:
                            st['msg'] = '断点命中 0x%03X' % cpu.pc
                        else:
                            try:
                                cpu.step()
                            except RuntimeError as e:
                                st['msg'] = str(e)
                    elif ch == 'j':
                        st['cur'] = (st['cur'] + 2) & 0xFFE
                    elif ch == 'k':
                        st['cur'] = (st['cur'] - 2) & 0xFFE
                    elif ch == 'b':
                        if st['cur'] in st['bps']:
                            st['bps'].discard(st['cur'])
                        else:
                            st['bps'].add(st['cur'])
                    elif ch == 'g':
                        st['dump'] = 'pc' if st['dump'] == 'i' else 'i'
                    elif ch == '+':
                        st['ips'] = min(st['ips'] * 2, 4096)
                    elif ch == '-':
                        st['ips'] = max(st['ips'] // 2, 1)
                    else:
                        k = KEYMAP.get(ch.lower())
                        if k is not None:         # 游戏键照常喂给虚拟机
                            cpu.keys[k] = True
                            keys_down[k] = time.monotonic() + 150 / 1000.0
            now = time.monotonic()
            for k, deadline in list(keys_down.items()):
                if now >= deadline:
                    cpu.keys[k] = False
                    del keys_down[k]
            if not st['paused']:
                for _ in range(st['ips']):
                    if cpu.pc in st['bps'] and cpu.pc != st.get('guard'):
                        st['paused'] = True
                        st['msg'] = '断点命中 0x%03X' % cpu.pc
                        break
                    st.pop('guard', None)
                    try:
                        cpu.step()
                    except RuntimeError as e:
                        st['paused'] = True
                        st['msg'] = str(e)
                        break
                else:
                    cpu.tick()
            size = shutil.get_terminal_size()
            if fit_scope(size.columns, size.lines):
                snap = snapshot(cpu, st)
                lines, foot = panels(snap, prev, st, half_block_frame(cpu))
                text, rview = paint(size.columns, size.lines, lines, foot, rview)
                prev = snap
            else:
                text, rview = paint(size.columns, size.lines, [], [
                    '窗口太小(%dx%d):显微镜至少要 %dx%d'
                    % (size.columns, size.lines, SCOPE_W, SCOPE_H)], rview, '\x1b[1;31m')
            sys.stdout.write(text)
            sys.stdout.flush()
            rest = frame_time - (time.monotonic() - t0)
            if rest > 0:
                time.sleep(rest)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write('\x1b[?25h\x1b[?1049l')
        sys.stdout.flush()
