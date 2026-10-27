"""内核冒烟:两个任务的时间片必须在 UART 流里交替成段。

运行:python3 tests/kern_smoke.py(需先 bash c/build.sh kern)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rv.cpu import RV32  # noqa: E402


def main():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cpu = RV32()
    with open(os.path.join(root, 'c', 'kern.bin'), 'rb') as f:
        cpu.load(f.read())
    halted = True
    try:
        cpu.run(2_000_000)
    except RuntimeError as e:
        if 'max_steps' not in str(e):
            raise
        halted = False                  # 内核常驻,跑满步数属预期
    out = ''.join(cpu.uart_out)
    assert out.startswith('|'), '缺内核就绪标记: %r' % out[:20]
    assert 'A' in out and 'B' in out, '只有单任务在跑: %r' % out[:40]
    runs = []
    for ch in out:
        if not runs or runs[-1] != ch:
            runs.append(ch)
    assert len(runs) >= 6, '没有形成交替时间片: %r' % ''.join(runs)
    print('KERN SMOKE PASS: %d 字符,%d 次任务切换(halted=%s)输出开头 %r'
          % (len(out), len(runs) - 1, halted, out[:24]))


if __name__ == '__main__':
    main()
