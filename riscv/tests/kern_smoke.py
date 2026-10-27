"""内核冒烟:调度/邮箱/键盘链路的端到端断言。

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
    halted = False
    seen_fb = False
    keys = 'wasd'
    ki = 0
    chunk = 0
    target = 2_000_000
    while cpu.cycles < target and not cpu.halted:
        for _ in range(min(50_000, target - cpu.cycles)):
            cpu.step()
        chunk += 1
        if any(cpu.fb):
            seen_fb = True              # 图形任务画出过小球
        if ki < len(keys) and chunk == 4 + ki * 4:
            cpu.input.append(keys[ki])  # 模拟敲键盘:注入输入设备
            ki += 1
    halted = cpu.halted
    out = ''.join(cpu.uart_out)
    assert out.startswith('|'), '缺内核就绪标记: %r' % out[:20]
    assert '+++' in out, '生产者突发(环形缓冲吸收)没出现: %r' % out[:60]
    assert '<' in out, '消费者回显缺失: %r' % out[:40]
    assert seen_fb, 'framebuffer 上没看到小球'
    assert all(k in out for k in keys), \
        '键盘输入没有经 MMIO 回显到串口'
    import re
    msgs = [int(m) for m in re.findall(r'<(\d+)>', out)]
    assert len(msgs) >= 5, '消息太少: %r' % out[:60]
    assert msgs == list(range(len(msgs))), \
        '邮箱丢了/重了/乱序消息: %r' % msgs[:20]
    switches = sum(1 for a, b in zip(out, out[1:]) if a != b)
    print('KERN SMOKE PASS: %d 字符,%d 次切换(halted=%s)输出开头 %r'
          % (len(out), switches, halted, out[:24]))


if __name__ == '__main__':
    main()
