"""RV32I+M 原子级显微镜(--scope):把 CPU 拆开给你看的调试器。

    python3 -m rv.emu c/kern.bin --scope

面板:反汇编窗口(8 条,基于 cpu.decode() 的字段,ABI 寄存器名)
+ 32 位指令位分解(按 R/I/S/B/U/J 格式逐字段上色)+ x0-x31 双列
+ CSR/特权级面板(mstatus/mepc/mcause/mode)+ 64x32 framebuffer
+ 内存 hexdump(跟随 sp/pc/mepc)。变化过的寄存器、CSR 与内存字节
染黄色,PC 行染青色,断点行标红——"每个原子动了都看得见"。

热键:空格 暂停/继续,n 单步一条,j/k 移动反汇编光标,b 在光标处
切换断点,g 切换 hexdump 跟随(sp→pc→mepc),+/- 调速,ESC 退出。

渲染复用 emu.paint 的绝对定位约定:raw 模式全程无换行符。
disasm/bit_fields/diff_changed/panels 都是纯函数,panels 只吃
snapshot 的普通数据——测试不需要 CPU 实例。
"""
import os
import shutil
import sys

from .asm import BRANCH3, IMM_ALU, LOADS, M_ALU, REG_ALU, STORES
from .cpu import FB_BASE, FB_SIZE, MASK32, RAM_BASE, decode
from .emu import dwidth, half_block, paint

DIM, RESET = '\x1b[2m', '\x1b[0m'
CYA, YEL, RED = '\x1b[36m', '\x1b[33m', '\x1b[31m'


def pad(s, w):
    """按可见宽度补空格(ljust 会被颜色序列骗到)。"""
    return s + ' ' * max(0, w - dwidth(s))

# num → ABI 名,与 asm.py 的寄存器表同源(x 系名字之外取 ABI 助记)
ABI = ['zero', 'ra', 'sp', 'gp', 'tp', 't0', 't1', 't2',
       's0', 's1', 'a0', 'a1', 'a2', 'a3', 'a4', 'a5',
       'a6', 'a7', 's2', 's3', 's4', 's5', 's6', 's7',
       's8', 's9', 's10', 's11', 't3', 't4', 't5', 't6']

BR = {v: k for k, v in BRANCH3.items()}
LD = {v: k for k, v in LOADS.items()}
STO = {v: k for k, v in STORES.items()}
IA = {v: k for k, v in IMM_ALU.items()}
RA = {(f3, f7): k for k, (f3, f7) in REG_ALU.items()}
MA = {v: k for k, v in M_ALU.items()}
CSR_OPS_R = {1: 'csrrw', 2: 'csrrs', 3: 'csrrc', 5: 'csrrwi', 6: 'csrrsi', 7: 'csrrci'}
CSR_NAMES = {0x300: 'mstatus', 0x301: 'misa', 0x304: 'mie', 0x305: 'mtvec',
             0x340: 'mscratch', 0x341: 'mepc', 0x342: 'mcause', 0x344: 'mip'}

DISASM_ROWS = 8                              # 反汇编窗口行数
HEX_ROWS = 4                                 # hexdump 行数(每行 8 字节)
W_DIS, W_REG, W_CSR, W_HEX = 40, 36, 30, 44  # 左/中/右列与 hexdump 列宽
GAP = '  '
REG_ROWS = 16                                # x0-x31 双列 16 行(决定顶块高度)
TOP_W = W_DIS + len(GAP) + W_REG + len(GAP) + W_CSR
SCOPE_W = max(TOP_W, 64 + len(GAP) + W_HEX)
SCOPE_H = REG_ROWS + 1 + 16 + 2              # 顶块 + 空行 + fb(半块 16 行)+ foot


def disasm(word, pc=0):
    """指令字 → 助记符(GNU as 风格,ABI 寄存器名);只标注 CPU 真能执行的。"""
    f = decode(word)
    op, rd, f3, f7 = f['opcode'], f['rd'], f['f3'], f['f7']
    rs1, rs2 = f['rs1'], f['rs2']
    imm = f.get('imm', 0)
    rd_n, rs1_n, rs2_n = ABI[rd], ABI[rs1], ABI[rs2]
    if op == 0x37:
        return 'lui %s,0x%X' % (rd_n, (imm >> 12) & 0xFFFFF)
    if op == 0x17:
        return 'auipc %s,0x%X' % (rd_n, (imm >> 12) & 0xFFFFF)
    if op == 0x6F:
        tgt = (pc + imm) & MASK32
        return 'j 0x%X' % tgt if rd == 0 else 'jal %s,0x%X' % (rd_n, tgt)
    if op == 0x67:
        if word == 0x00008067:               # jalr ra,0(ra) = ret
            return 'ret'
        return 'jalr %s,%d(%s)' % (rd_n, imm, rs1_n)
    if op == 0x63:
        m = BR.get(f3)
        return ('%s %s,%s,0x%X' % (m, rs1_n, rs2_n, (pc + imm) & MASK32)
                if m else '.word 0x%08X' % word)
    if op == 0x03:
        m = LD.get(f3)
        return ('%s %s,%d(%s)' % (m, rd_n, imm, rs1_n)
                if m else '.word 0x%08X' % word)
    if op == 0x23:
        m = STO.get(f3)
        return ('%s %s,%d(%s)' % (m, rs2_n, imm, rs1_n)
                if m else '.word 0x%08X' % word)
    if op == 0x13:
        if f3 == 1:
            return 'slli %s,%s,%d' % (rd_n, rs1_n, rs2)
        if f3 == 5:
            return '%s %s,%s,%d' % ('srai' if f7 == 0x20 else 'srli',
                                    rd_n, rs1_n, rs2)
        m = IA.get(f3)
        return ('%s %s,%s,%d' % (m, rd_n, rs1_n, imm)
                if m else '.word 0x%08X' % word)
    if op == 0x33:
        if f7 == 0x01:
            m = MA.get(f3)
        else:
            m = RA.get((f3, f7))
        return ('%s %s,%s,%s' % (m, rd_n, rs1_n, rs2_n)
                if m else '.word 0x%08X' % word)
    if op == 0x0F:
        return 'fence'
    if op == 0x73:
        if f3 == 0:
            m = {0x00000073: 'ecall', 0x00100073: 'ebreak',
                 0x30200073: 'mret', 0x10500073: 'wfi'}.get(word)
            return m or '.word 0x%08X' % word
        num = (word >> 20) & 0xFFF
        m = CSR_OPS_R.get(f3)
        if m is None:
            return '.word 0x%08X' % word
        name = CSR_NAMES.get(num, '0x%03X' % num)
        if f3 >= 5:                          # 立即数形式:rs1 字段是 zimm
            return '%s %s,%s,%d' % (m, rd_n, name, rs1)
        return '%s %s,%s,%s' % (m, rd_n, name, rs1_n)
    return '.word 0x%08X' % word


def bit_fields(word):
    """32 位按当前格式分组 → (逐位行, 字段标签行)。字段宽度加起来恒 32。"""
    op = word & 0x7F
    if op == 0x33:
        groups = (('f7', 7), ('rs2', 5), ('rs1', 5), ('f3', 3), ('rd', 5), ('op', 7))
    elif op in (0x03, 0x13, 0x67):
        groups = (('imm', 12), ('rs1', 5), ('f3', 3), ('rd', 5), ('op', 7))
    elif op == 0x73:
        groups = (('csr' if (word >> 12) & 7 else 'f12', 12),
                  ('rs1', 5), ('f3', 3), ('rd', 5), ('op', 7))
    elif op in (0x23, 0x63):
        groups = (('imm7', 7), ('rs2', 5), ('rs1', 5), ('f3', 3), ('imm5', 5), ('op', 7))
    elif op in (0x37, 0x17):
        groups = (('imm20', 20), ('rd', 5), ('op', 7))
    elif op == 0x6F:
        groups = (('imm11', 11), ('i1', 1), ('imm8', 8), ('rd', 5), ('op', 7))
    else:
        groups = (('.word', 32),)
    b = format(word, '032b')
    pos, bits, labels = 0, [], []
    for name, w in groups:
        bits.append(b[pos:pos + w])
        labels.append(name.center(w))
        pos += w
    return ' '.join(bits), ' '.join(labels)


def diff_changed(old, new):
    """两份等长序列 → 发生变化的下标集合;旧快照缺失则不标。"""
    if old is None:
        return set()
    return {k for k in range(min(len(old), len(new))) if old[k] != new[k]}


def cause_name(c):
    """mcause → 可读名。"""
    if c & (1 << 31):
        return {7: '定时中断', 3: 'ebreak', 2: '非法指令', 8: 'ecall'}.get(c & 0xF, '中断')
    return {2: '非法指令', 3: 'ebreak', 8: 'ecall'}.get(c, '异常')


def _region_dump(cpu, view):
    """hexdump 跟随目标 → (地址, 区域名, 32 字节或 None)。"""
    t = view['dump']
    addr = (cpu.x[2] if t == 'sp' else cpu.pc if t == 'pc'
            else cpu.csr.get(0x341, 0)) & MASK32
    if RAM_BASE <= addr < RAM_BASE + len(cpu.mem) - 32:
        off = addr - RAM_BASE
        return addr, 'RAM', bytes(cpu.mem[off:off + 32])
    if FB_BASE <= addr < FB_BASE + FB_SIZE - 32:
        off = addr - FB_BASE
        return addr, 'FB', bytes(cpu.fb[off:off + 32])
    return addr, '未映射', None


def snapshot(cpu, view):
    """CPU → 普通数据快照(panels 只吃这个,测试不用造 CPU)。"""
    cur = view['cur'] & ~3
    code_start = max(RAM_BASE, cur - (DISASM_ROWS // 2 - 1) * 4)
    words = []
    for k in range(DISASM_ROWS):
        a = code_start + 4 * k
        off = a - RAM_BASE
        w = int.from_bytes(cpu.mem[off:off + 4], 'little') if off + 4 <= len(cpu.mem) else 0
        words.append((a, w))
    off = cpu.pc - RAM_BASE
    op = int.from_bytes(cpu.mem[off:off + 4], 'little') if 0 <= off <= len(cpu.mem) - 4 else 0
    tail = ''.join(cpu.uart_out)[-24:]
    return dict(x=list(cpu.x), pc=cpu.pc, mode=cpu.mode, mtime=cpu.mtime,
                mtimecmp=cpu.mtimecmp, csr=dict(cpu.csr), cycles=cpu.cycles,
                halted=cpu.halted, exit_code=cpu.exit_code, words=words, op=op,
                uart=''.join(ch if 32 <= ord(ch) < 127 else '·' for ch in tail),
                dump=_region_dump(cpu, view))


def _disasm_lines(snap, view):
    out = []
    for addr, word in snap['words']:
        mark = '→' if addr == snap['pc'] else '●' if addr in view['bps'] else ' '
        text = ' %08X %08X %-*s' % (addr, word, W_DIS - 21, disasm(word, addr))
        if addr == snap['pc']:
            out.append(CYA + mark + text + RESET)
        elif addr in view['bps']:
            out.append(RED + mark + text + RESET)
        else:
            out.append(mark + text)
    bits, labels = bit_fields(snap['op'])
    out.append(DIM + bits + RESET)
    out.append(DIM + labels + RESET)
    return out


def _reg_lines(snap, prev):
    ch = diff_changed(prev['x'] if prev else None, snap['x'])

    def cell(k):
        s = 'x%-2d %-4s %08X' % (k, ABI[k], snap['x'][k])
        return (YEL + s + RESET) if k in ch else s

    return [pad(cell(r), 17) + GAP + pad(cell(r + 16), 17) for r in range(16)]


def _csr_lines(snap, prev):
    ch = set()
    if prev:
        ch = {k for k in set(prev['csr']) | set(snap['csr'])
              if prev['csr'].get(k, 0) != snap['csr'].get(k, 0)}
    changed = lambda k: k in ch

    def row(name, num, note=''):
        v = snap['csr'].get(num, 0)
        s = '%-8s %08X' % (name, v)
        if note:
            s += ' ' + note
        return (YEL + s + RESET) if changed(num) else s

    mode = 'M' if snap['mode'] == 3 else 'U'
    cause = snap['csr'].get(0x342, 0)
    cause_s = cause_name(cause) if cause else ''
    mt_s = 'mtime %d' % snap['mtime']
    if prev and prev['mtime'] != snap['mtime']:
        mt_s = YEL + mt_s + RESET
    return ['特权 %s   CYC %d' % (mode, snap['cycles']),
            row('mstatus', 0x300), row('mie', 0x304), row('mtvec', 0x305),
            row('mepc', 0x341),
            row('mcause', 0x342, cause_s),
            mt_s,
            'mtcmp %d' % snap['mtimecmp'],
            DIM + ('UART ' + snap['uart'] if snap['uart'] else '(UART 空)') + RESET]


def _hex_lines(snap, prev):
    addr, name, dump = snap['dump']
    out = ['内存 @%08X(%s)' % (addr, name)]
    if dump is None:
        out.append('(MMIO 区不逐字节展示)')
        return out
    ch = set()
    if prev and prev['dump'][1] == name and prev['dump'][0] == addr:
        ch = diff_changed(prev['dump'][2], dump)
    for r in range(HEX_ROWS):
        row = dump[r * 8:(r + 1) * 8]
        cells, asc = [], []
        for k, b in enumerate(row):
            g = '%02X' % b
            idx = r * 8 + k
            if idx == 0:                         # 首字节:跟随目标本身
                g = CYA + g + RESET
            elif idx in ch:
                g = YEL + g + RESET
            cells.append(g)
            asc.append(chr(b) if 32 <= b < 127 else '·')
        out.append('%08X  %s  %s' % (addr + r * 8, ' '.join(cells), ''.join(asc)))
    return out


def panels(snap, prev, view, screen_lines):
    """快照 → (整幅面板行, foot 行)。纯函数:只吃 snapshot 的普通数据。"""
    cols = [_disasm_lines(snap, view), _reg_lines(snap, prev), _csr_lines(snap, prev)]
    top = []
    for r in range(REG_ROWS):
        top.append(GAP.join(pad(c[r], W) if r < len(c) else ' ' * W
                            for c, W in zip(cols, (W_DIS, W_REG, W_CSR))))
    hexc = _hex_lines(snap, prev)
    row2 = []
    for r in range(16):
        fb_line = screen_lines[r]
        hx = pad(hexc[r], W_HEX) if r < len(hexc) else ' ' * W_HEX
        row2.append(fb_line + GAP + hx)
    lines = top + [''] + row2

    if snap['halted']:
        status = RED + '已停机(退出码 %d)' % snap['exit_code'] + RESET
    elif view['paused']:
        status = '已暂停'
    else:
        status = '运行中'
    if view['msg']:
        status = RED + view['msg'] + RESET
    foot = ['键位: 空格 暂停/继续 | n 单步 | j/k 光标 | b 断点 | g 跟随sp/pc/mepc | +/- 调速 | ESC 退出',
            'PC %08X | 特权 %s | %s | SPF %d | 断点 %d | CYC %d | MTIME %d'
            % (snap['pc'], 'M' if snap['mode'] == 3 else 'U', status,
               view['spf'], len(view['bps']), snap['cycles'], snap['mtime'])]
    return [pad(l, SCOPE_W) for l in lines], foot


def fit_scope(cols, rows):
    return cols >= SCOPE_W and rows >= SCOPE_H


def run_scope(cpu, spf, fps=30):
    """显微镜主循环:默认暂停,空格启动;spf 为单元素列表(照 run_live)。"""
    import select
    import termios
    import time
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    sys.stdout.write('\x1b[?1049h\x1b[?25l')
    st = dict(paused=True, cur=cpu.pc, bps=set(), spf=spf[0],
              dump='sp', msg='空格运行,n 单步')
    prev, rview = None, None
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
                        st['cur'] = cpu.pc
                        st['msg'] = ''
                        st['guard'] = cpu.pc      # 继续时跳过当前 PC 上的断点
                    elif ch == 'n':
                        st['paused'] = True
                        st['cur'] = cpu.pc
                        st['msg'] = ''
                        if cpu.halted:
                            st['msg'] = '已停机,退出码 %d' % cpu.exit_code
                        elif cpu.pc in st['bps']:
                            st['msg'] = '断点命中 0x%08X' % cpu.pc
                        else:
                            try:
                                cpu.step()
                            except RuntimeError as e:
                                st['msg'] = str(e)
                    elif ch == 'j':
                        st['cur'] = (st['cur'] + 4) & MASK32
                    elif ch == 'k':
                        st['cur'] = (st['cur'] - 4) & MASK32
                    elif ch == 'b':
                        if st['cur'] in st['bps']:
                            st['bps'].discard(st['cur'])
                        else:
                            st['bps'].add(st['cur'])
                    elif ch == 'g':
                        st['dump'] = {'sp': 'pc', 'pc': 'mepc', 'mepc': 'sp'}[st['dump']]
                    elif ch == '+':
                        st['spf'] = min(st['spf'] * 2, 200000)
                        spf[0] = st['spf']
                    elif ch == '-':
                        st['spf'] = max(st['spf'] // 2, 500)
                        spf[0] = st['spf']
            if not st['paused'] and not cpu.halted:
                for _ in range(st['spf']):
                    if cpu.pc in st['bps'] and cpu.pc != st.get('guard'):
                        st['paused'] = True
                        st['msg'] = '断点命中 0x%08X' % cpu.pc
                        break
                    st.pop('guard', None)
                    try:
                        cpu.step()
                    except RuntimeError as e:
                        st['paused'] = True
                        st['msg'] = str(e)
                        break
                    if cpu.halted:
                        st['paused'] = True
                        st['msg'] = '已停机,退出码 %d' % cpu.exit_code
                        break
            size = shutil.get_terminal_size()
            if fit_scope(size.columns, size.lines):
                snap = snapshot(cpu, st)
                lines, foot = panels(snap, prev, st, half_block(cpu.fb))
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
