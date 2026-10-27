"""列出 zig 已知的 riscv32 CPU 模型与特性名,帮 build.sh 选对 -mcpu 写法。"""
import json
import subprocess

ZIG = '/home/dazi9/computer-lab/tools/zig/zig'
out = subprocess.run([ZIG, 'targets'], capture_output=True, text=True).stdout
print('zig targets 输出前 500 字符(0.17 起为 Zig 语法而非 JSON):')
print(out[:500])
