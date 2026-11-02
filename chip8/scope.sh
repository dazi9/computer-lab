#!/usr/bin/env bash
# 原子级显微镜:反汇编/寄存器/内存/单步/断点(在真实终端里跑),在仓库根目录执行:
#   bash chip8/scope.sh                        # 默认 bounce
#   bash chip8/scope.sh roms/paddle.ch8
# 空格 暂停/继续,n 单步,j/k 移动光标,b 断点,g 跟随I/PC,+/- 调速,ESC 退出
cd "$(dirname "$0")" || exit 1
exec python3 -m chip8.emu "${1:-roms/bounce.ch8}" --scope "${@:2}"
