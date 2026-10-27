"""RV32I 运行器:直接喂 .asm(现场汇编)或 .bin。

    python3 -m rv.emu programs/hello.asm
    python3 -m rv.emu programs/hello.bin --trace --max-steps 50000

程序通过 MMIO(写 0x10000000)往"串口"打字,ecall 停机。
"""
import argparse
import sys

from .asm import assemble
from .cpu import RAM_BASE, RV32

# 实况渲染用的行内导入放在 run_live 里,避免无头环境加载 termios 失败


def half_block(fb):
    """64x32 framebuffer(每行 8 字节,MSB=最左)→ 16 行半块字符。"""
    def px(r, c):
        return fb[r * 8 + (c >> 3)] & (0x80 >> (c & 7))
    lines = []
    for r in range(0, 32, 2):
        row = []
        for c in range(64):
            top, bot = px(r, c), px(r + 1, c)
            row.append('█' if top and bot else '▀' if top else '▄' if bot else ' ')
        lines.append(''.join(row))
    return '\n'.join(lines)


def run_live(cpu, spf, fps=30):
    """终端实况模式:FB 渲染 + UART 尾巴 + 统计。ESC 退出,+/- 调速。"""
    import select
    import termios
    import time
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    sys.stdout.write('\x1b[?1049h\x1b[?25l')
    try:
        tty.setraw(fd)
        frame_time = 1.0 / fps
        while not cpu.halted:
            t0 = time.monotonic()
            while select.select([sys.stdin], [], [], 0)[0]:
                ch = sys.stdin.read(1)
                if ch in ('\x1b', '\x03'):                 # ESC 或方向键序列
                    if select.select([sys.stdin], [], [], 0.01)[0]:
                        follow = sys.stdin.read(1)
                        if follow == '[':                  # ESC [ X = 方向键
                            arrow = sys.stdin.read(1)
                            m = {'A': 'w', 'B': 's', 'C': 'd', 'D': 'a'}
                            if arrow in m:
                                cpu.input.append(m[arrow])
                            continue
                    return                                     # 真 ESC:退出
                if ch == '\x03':
                    return
                if ch == '+':
                    spf[0] = min(spf[0] * 2, 200000)
                elif ch == '-':
                    spf[0] = max(spf[0] // 2, 500)
                elif 32 <= ord(ch) < 127:                  # 可打印字符 → 输入设备
                    cpu.input.append(ch)
            for _ in range(spf[0]):
                if cpu.halted:
                    break
                cpu.step()
            tail = ''.join(cpu.uart_out)[-120:]
            tail = ''.join(ch if 32 <= ord(ch) < 127 else '·' for ch in tail)
            stat = ('CYC %d | MTIME %d | %d 步/帧 | +/- 调速  ESC 退出'
                    % (cpu.cycles, cpu.mtime, spf[0]))
            sys.stdout.write('\x1b[H' + half_block(cpu.fb) + '\n' + tail
                             + '\n' + stat + '\x1b[J')
            sys.stdout.flush()
            rest = frame_time - (time.monotonic() - t0)
            if rest > 0:
                time.sleep(rest)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        sys.stdout.write('\x1b[?25h\x1b[?1049l')
        sys.stdout.flush()


def main(argv=None):
    ap = argparse.ArgumentParser(description='RV32I 模拟器(纯 CPU,MMIO 终端)')
    ap.add_argument('program', help='.asm 或 .bin')
    ap.add_argument('--max-steps', type=int, default=1_000_000)
    ap.add_argument('--trace', action='store_true', help='逐步打印 PC 与指令字')
    ap.add_argument('--fb-every', type=int, default=0, metavar='N',
                    help='每 N 条指令打印一次 framebuffer ASCII(0=关)')
    ap.add_argument('--live', action='store_true',
                    help='终端实况:实时渲染 framebuffer + UART 流(需真实终端)')
    ap.add_argument('--spf', type=int, default=4000, metavar='N',
                    help='实况模式每帧步数(默认 4000,+/- 运行中调速)')
    a = ap.parse_args(argv)

    cpu = RV32()
    if a.program.endswith('.asm'):
        with open(a.program, encoding='utf-8') as fh:
            cpu.load(assemble(fh.read()))
    else:
        with open(a.program, 'rb') as fh:
            cpu.load(fh.read())

    try:
        if a.live and sys.stdin.isatty():
            spf = [a.spf]
            run_live(cpu, spf)
            out = ''.join(cpu.uart_out)
            if out:
                print(out[-2000:])
            if cpu.halted:
                print('[停机: 执行 %d 条指令, 退出码 %d]'
                      % (cpu.cycles, cpu.exit_code))
            else:
                print('[实况结束: 共 %d 条指令]' % cpu.cycles)
            return
        if a.live:
            print('(--live 需要真实终端,这里退回无头模式)')
        if a.trace:
            while not cpu.halted and cpu.cycles < a.max_steps:
                off = cpu.pc - RAM_BASE
                print('%08X: %08X' % (cpu.pc,
                                      int.from_bytes(cpu.mem[off:off + 4], 'little')))
                cpu.step()
            if not cpu.halted:
                raise RuntimeError('超过 max-steps=%d' % a.max_steps)
        elif a.fb_every:
            while not cpu.halted and cpu.cycles < a.max_steps:
                cpu.step()
                if cpu.cycles % a.fb_every == 0:
                    print('===== FB | 累计 %d 条指令 =====' % cpu.cycles)
                    print(cpu.fb_ascii())
            if not cpu.halted:
                raise RuntimeError('超过 max-steps=%d' % a.max_steps)
        else:
            try:
                cpu.run(a.max_steps)
            except RuntimeError as e:
                if 'max_steps' not in str(e):
                    raise             # 真错误照常上报
                a.resident = True     # 内核类常驻程序:到步数上限属预期
    except RuntimeError as e:
        sys.stdout.flush()
        print('!! %s' % e, file=sys.stderr)
        sys.exit(1)

    out = ''.join(cpu.uart_out)
    if out:
        sys.stdout.write(out)
        if not out.endswith('\n'):
            sys.stdout.write('\n')
    if cpu.halted:
        print('[停机: 执行 %d 条指令, 退出码 %d]' % (cpu.cycles, cpu.exit_code))
    else:
        print('[常驻运行: %d 条指令后达到 max-steps 上限]' % cpu.cycles)


if __name__ == '__main__':
    main()
