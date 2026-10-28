"""列出 zig 已知的 riscv32 CPU 模型与特性名,帮 build.sh 选对 -mcpu 写法。"""
import os
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ZIG = os.environ.get('ZIG') or os.path.join(ROOT, 'tools', 'zig', 'zig')
if not os.path.exists(ZIG) and os.path.exists(ZIG + '.exe'):
    ZIG += '.exe'
if not os.path.exists(ZIG):
    raise SystemExit('找不到 zig: %s\n先运行 python3 tools/fetch_zig.py,'
                     '或设置 ZIG=/path/to/zig' % ZIG)

out = subprocess.run([ZIG, 'targets'], capture_output=True, text=True).stdout
print('zig targets 输出前 500 字符(0.17 起为 Zig 语法而非 JSON):')
print(out[:500])
