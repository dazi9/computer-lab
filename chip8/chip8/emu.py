"""CHIP-8 运行器。

无头模式(给非交互环境/CI 用):
    python3 -m chip8.emu roms/bounce.ch8 --headless 60 --dump-every 20
交互模式(在真实终端里跑,ESC 退出):
    python3 -m chip8.emu roms/bounce.ch8
原子级显微镜(反汇编/寄存器/内存/单步/断点,真实终端):
    python3 -m chip8.emu roms/bounce.ch8 --scope
"""
import argparse
import re
import shutil
import sys

from .cpu import Chip8, H, W

# 交互渲染用的行内导入放在 run_interactive 里,避免无头环境加载 termios 失败

# 终端四排键 → CHIP-8 十六进制小键盘
KEYMAP = {
    '1': 0x1, '2': 0x2, '3': 0x3, '4': 0xC,
    'q': 0x4, 'w': 0x5, 'e': 0x6, 'r': 0xD,
    'a': 0x7, 's': 0x8, 'd': 0x9, 'f': 0xE,
    'z': 0xA, 'x': 0x0, 'c': 0xB, 'v': 0xF,
}


def ascii_frame(cpu):
    """64x32 位图 → 32 行 #/. 文本,无头快照用。"""
    return '\n'.join(
        ''.join('#' if p else '.' for p in cpu.display[r * W:(r + 1) * W])
        for r in range(H)
    )


def half_block_frame(cpu):
    """上下两个像素挤进一个终端字符(▀▄█),高宽比更顺眼。"""
    lines = []
    for r in range(0, H, 2):
        row = []
        for c_ in range(W):
            top = cpu.display[r * W + c_]
            bot = cpu.display[(r + 1) * W + c_]
            row.append('█' if top and bot else '▀' if top else '▄' if bot else ' ')
        lines.append(''.join(row))
    return lines


def wide_frame(cpu):
    """2x 模式:每像素占 2 字符宽、1 行高,给够大的窗口。"""
    return [''.join('██' if p else '  ' for p in cpu.display[r * W:(r + 1) * W])
            for r in range(H)]


ANSI_RE = re.compile('\x1b\\[[0-9;]*[A-Za-z]')


def strip_ansi(s):
    """剥掉 SGR 颜色序列,量宽度/截断时才能数对人眼看到的字符。"""
    return ANSI_RE.sub('', s)


def dwidth(s):
    """一行在终端里的显示宽度:CJK 全角按 2,其余按 1(颜色序列不算)。"""
    return sum(2 if ord(c) >= 0x2E80 else 1 for c in strip_ansi(s))


def clip(s, n):
    """按显示宽度截断一行,防止折行毁掉整个画面;颜色序列原样保留。"""
    out, used, i = [], 0, 0
    while i < len(s):
        m = ANSI_RE.match(s, i)
        if m:                                # 转义序列不占宽度,整段照抄
            out.append(m.group())
            i = m.end()
            continue
        ch = s[i]
        used += 2 if ord(ch) >= 0x2E80 else 1
        if used > n:
            break
        out.append(ch)
        i += 1
    return ''.join(out)


def fit(cols, rows, extra):
    """按窗口选缩放:2 = 每像素 2x1 字符,1 = 半块字符(2 像素挤 1 行),0 = 装不下。"""
    if cols >= W * 2 and rows >= H + extra:
        return 2
    if cols >= W and rows >= H // 2 + extra:
        return 1
    return 0


def paint(cols, rows, screen, foot, view, foot_style='\x1b[2m'):
    """把 screen(屏幕行)+ foot(说明行)居中重画,返回 (转义串, 本帧视图)。

    每行绝对定位 + 清到行尾,全程不依赖换行符:raw 模式下 OPOST 关着,
    单独的换行只下移不回车,靠它排版会在行宽非整屏时画成楼梯。
    视图(窗口尺寸/行数)与上帧不同才整屏清一次,其余帧原地覆盖不闪。"""
    items = screen + list(foot)
    width = max(map(dwidth, items)) if items else 1
    top = max((rows - len(items)) // 2, 0)
    left = max((cols - width) // 2, 0)
    buf = []
    if view != (cols, rows, len(screen)):
        buf.append('\x1b[2J')
    for i, line in enumerate(screen):
        buf.append('\x1b[%d;%dH\x1b[K%s' % (top + 1 + i, left + 1, line))
    for i, line in enumerate(foot):
        buf.append('\x1b[%d;%dH\x1b[K%s%s\x1b[0m'
                   % (top + 1 + len(screen) + i, left + 1, foot_style,
                      clip(line, cols - left)))
    return ''.join(buf), (cols, rows, len(screen))


def run_frames(cpu, frames, ips=8):
    """无头执行:每帧跑 ips 条指令 + 定时器走一格,返回每帧 ASCII 快照。"""
    snaps = []
    for _ in range(frames):
        for _ in range(ips):
            cpu.step()
        cpu.tick()
        snaps.append(ascii_frame(cpu))
    return snaps


def run_interactive(cpu, ips=8, fps=60, key_ms=150):
    """终端交互主循环。终端没有 keyup 事件,按键 150ms 后自动松开。"""
    import os
    import select
    import termios
    import time
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    foot = ['CHIP-8 | ESC 退出',
            '键位: 1234/qwer/asdf/zxcv → 123C/456D/789E/A0BF']
    sys.stdout.write('\x1b[?1049h\x1b[?25l')
    keys_down = {}
    view = None
    pending = ''
    try:
        tty.setraw(fd)
        frame_time = 1.0 / fps
        while True:
            t0 = time.monotonic()
            # os.read 整块吃掉 OS 缓冲再逐字符分发:select 看的是文件描述符,
            # sys.stdin.read(1) 走 Python 缓冲层,突发按键(如粘贴)会卡在
            # 缓冲里不再"可读",select 从此再也看不见它们
            while select.select([fd], [], [], 0)[0]:
                pending += os.read(fd, 4096).decode('utf-8', 'replace')
            while pending:
                ch, pending = pending[0], pending[1:]
                if ch in ('\x1b', '\x03'):        # ESC / Ctrl-C
                    return
                k = KEYMAP.get(ch.lower())
                if k is not None:
                    cpu.keys[k] = True
                    keys_down[k] = time.monotonic() + key_ms / 1000.0
            now = time.monotonic()
            for k, deadline in list(keys_down.items()):
                if now >= deadline:
                    cpu.keys[k] = False
                    del keys_down[k]
            for _ in range(ips):
                cpu.step()
            cpu.tick()
            if cpu.st:
                sys.stdout.write('\a')
            size = shutil.get_terminal_size()   # 每帧问一次,窗口拖动即刻生效
            s = fit(size.columns, size.lines, len(foot))
            if s == 2:
                text, view = paint(size.columns, size.lines, wide_frame(cpu),
                                   foot, view)
            elif s == 1:
                text, view = paint(size.columns, size.lines, half_block_frame(cpu),
                                   foot, view)
            else:
                text, view = paint(size.columns, size.lines, [], [
                    '窗口太小(%dx%d):至少 64x18,2x 缩放要 128x34'
                    % (size.columns, size.lines)], view, '\x1b[1;31m')
            sys.stdout.write(text)
            sys.stdout.flush()
            rest = frame_time - (time.monotonic() - t0)
            if rest > 0:
                time.sleep(rest)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write('\x1b[?25h\x1b[?1049l')
        sys.stdout.flush()


def main(argv=None):
    ap = argparse.ArgumentParser(description='CHIP-8 模拟器(纯 CPU,终端显示)')
    ap.add_argument('rom', help='ROM 文件路径')
    ap.add_argument('--ips', type=int, default=8, help='每帧执行指令数,默认 8(约 480Hz)')
    ap.add_argument('--fps', type=int, default=60)
    ap.add_argument('--headless', type=int, metavar='N', help='无头跑 N 帧后退出并打印快照')
    ap.add_argument('--dump-every', type=int, default=20, help='无头模式每几帧打印一次快照')
    ap.add_argument('--scope', action='store_true',
                    help='原子级显微镜:反汇编/寄存器/内存/单步/断点(需真实终端)')
    a = ap.parse_args(argv)

    cpu = Chip8()
    with open(a.rom, 'rb') as f:
        cpu.load(f.read())

    if a.headless is not None:
        snaps = run_frames(cpu, a.headless, a.ips)
        for idx, snap in enumerate(snaps):
            if idx % a.dump_every == 0:
                print('===== 第 %d 帧 | 累计 %d 条指令 =====' % (idx, (idx + 1) * a.ips))
                print(snap)
    elif a.scope and sys.stdin.isatty():
        from .scope import run_scope
        run_scope(cpu, a.ips, a.fps)
    elif a.scope:
        print('(--scope 需要真实终端,这里退回无头模式)')
        for idx, snap in enumerate(run_frames(cpu, 120, a.ips)):
            if idx % 30 == 0:
                print('===== 第 %d 帧 =====' % idx)
                print(snap)
    else:
        run_interactive(cpu, a.ips, a.fps)


if __name__ == '__main__':
    main()
