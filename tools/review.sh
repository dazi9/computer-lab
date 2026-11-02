#!/usr/bin/env bash
# 项目全面体检:git 状态 / 规模 / 全量测试 / demo 抽查 / 云端同步
set -e
cd /home/dazi9/computer-lab

echo "== git 状态 =="
echo "提交数: $(git log --oneline | wc -l)"
echo "工作树: $(git status --short | wc -l) 个未提交变更(应为 0)"
echo "本地 HEAD: $(git rev-parse --short HEAD)"
echo "远程 main: $(git ls-remote origin refs/heads/main | cut -c1-12)"

echo "== 代码规模 =="
find . -path ./tools/zig -prune -o -path ./.git -prune -o -path ./.ssh -prune -o \
     -type f \( -name '*.py' -o -name '*.c' -o -name '*.S' -o -name '*.asm' \) -print0 \
     | xargs -0 wc -l | tail -1
for d in chip8/chip8 riscv/rv riscv/c; do
  printf '%-14s %3d 行\n' "$d" "$(cat $d/*.py $d/*.c $d/*.S 2>/dev/null | wc -l)"
done

echo "== 全量测试 =="
( cd chip8 && python3 tests/test_cpu.py 2>&1 | tail -1 )
( cd chip8 && python3 tests/smoke.py 2>&1 | head -1 )
( cd riscv && python3 tests/test_rv.py 2>&1 | tail -1 )
( cd riscv && python3 tests/kern_smoke.py 2>&1 | head -1 )

echo "== demo 抽查 =="
( cd riscv && python3 -m rv.emu programs/hello.asm 2>&1 | head -1 )

echo "== 完成 =="
