#!/usr/bin/env bash
# 原子级显微镜:反汇编/寄存器/CSR/位分解/单步/断点(在真实终端里跑),在仓库根目录执行:
#   bash riscv/scope.sh                        # 默认内核(需先 bash c/build.sh kern)
#   bash riscv/scope.sh programs/hello.asm     # 汇编源直接喂
# 空格 暂停/继续,n 单步,j/k 移动光标,b 断点,g 跟随sp/pc/mepc,+/- 调速,ESC 退出
cd "$(dirname "$0")" || exit 1
exec python3 -m rv.emu "${1:-c/kern.bin}" --scope "${@:2}"
