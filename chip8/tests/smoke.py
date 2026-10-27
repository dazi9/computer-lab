"""无头冒烟测试:BOUNCE 球必须真的在动;PADDLE 必须对按键有响应。

运行:python3 tests/smoke.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from chip8.asm import BOUNCE_SRC, PADDLE_SRC, assemble  # noqa: E402
from chip8.cpu import Chip8  # noqa: E402
from chip8.emu import run_frames  # noqa: E402


def main():
    cpu = Chip8()
    cpu.load(assemble(BOUNCE_SRC))
    snaps = run_frames(cpu, 120, ips=8)
    assert any('#' in s for s in snaps), '屏幕从头到尾全空'
    moves = sum(1 for a, b in zip(snaps, snaps[1:]) if a != b)
    assert moves >= 10, '球几乎没动(只有 %d 帧画面变化)' % moves
    print('SMOKE PASS: BOUNCE 120 帧无头运行,%d 帧画面变化,共 %d 条指令'
          % (moves, cpu.cycles))

    # 输入路径:按住"左移"键跑 60 帧,挡板必须向左移动
    cpu2 = Chip8()
    cpu2.load(assemble(PADDLE_SRC))
    cpu2.keys[0x1] = True            # 终端键 '1' = CHIP-8 键 0x1
    run_frames(cpu2, 60, ips=8)
    assert cpu2.v[0] < 30, '按住左移键挡板没动: x=%d' % cpu2.v[0]
    print('SMOKE PASS: PADDLE 对按键有响应(按住左移 60 帧后 x=%d)' % cpu2.v[0])


if __name__ == '__main__':
    main()
