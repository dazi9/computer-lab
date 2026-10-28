#!/usr/bin/env bash
# 在你自己的真实终端里玩(别在管道/重定向里跑),在仓库根目录执行:
#   bash chip8/play.sh                          # 弹跳小球
#   bash chip8/play.sh roms/ibm-logo.ch8
cd "$(dirname "$0")" || exit 1
exec python3 -m chip8.emu "${1:-roms/bounce.ch8}" "${@:2}"
