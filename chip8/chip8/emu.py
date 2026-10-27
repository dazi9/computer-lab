"""CHIP-8 运行器。

无头模式(给非交互环境/CI 用):
    python3 -m chip8.emu roms/bounce.ch8 --headless 60 --dump-every 20
交互模式(在真实终端里跑,ESC 退出):
    python3 -m chip8.emu roms/bounce.ch8
"""
import argparse
import select
import sys
import termios
import time
import tty

from .cpu import Chip8, H, W

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
    return '\n'.join(lines)


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
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    hint = 'CHIP-8 | ESC 退出 | 键位: 1234/qwer/asdf/zxcv → 123C/456D/789E/A0BF'
    sys.stdout.write('\x1b[?1049h\x1b[?25l')
    keys_down = {}
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
            sys.stdout.write('\x1b[H' + half_block_frame(cpu) + '\n' + hint + '\x1b[J')
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
