"""CHIP-8 运行器。

无头模式(给非交互环境/CI 用):
    python3 -m chip8.emu roms/bounce.ch8 --headless 60 --dump-every 20
交互模式(在真实终端里跑,ESC 退出):
    python3 -m chip8.emu roms/bounce.ch8
"""
import argparse
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


def dwidth(s):
    """一行在终端里的显示宽度:CJK 全角按 2,其余按 1。"""
    return sum(2 if ord(c) >= 0x2E80 else 1 for c in s)


def clip(s, n):
    """按显示宽度截断一行,防止折行毁掉整个画面。"""
    out, used = [], 0
    for ch in s:
        used += 2 if ord(ch) >= 0x2E80 else 1
        if used > n:
            break
        out.append(ch)
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
    try:
        tty.setraw(fd)
        frame_time = 1.0 / fps
        while True:
            t0 = time.monotonic()
            while select.select([sys.stdin], [], [], 0)[0]:
                ch = sys.stdin.read(1)
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
    else:
        run_interactive(cpu, a.ips, a.fps)


if __name__ == '__main__':
    main()
