#!/usr/bin/env bash
# 在你自己的真实终端里围观内核/程序实况(别在管道里跑),在仓库根目录执行:
#   bash riscv/watch.sh                     # 默认内核
#   bash riscv/watch.sh c/bounce.bin        # 图形程序
# ESC 退出,+/- 运行中调速,方向键/WASD 操纵小球(内核支持时)
cd "$(dirname "$0")" || exit 1
exec python3 -m rv.emu "${1:-c/kern.bin}" --live "${@:2}"
