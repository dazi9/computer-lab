#!/usr/bin/env bash
# 用法: bash build.sh <hello|sum|kern|deci|bounce>
# 用 zig cc 把 start.S + <name>.c 交叉编译成 RV32I 裸机镜像
set -e
cd "$(dirname "$0")"
ROOT="$(cd ../.. && pwd)"
ZIG="${ZIG:-$ROOT/tools/zig/zig}"
NAME="${1:?用法: build.sh <hello|sum|kern|deci|bounce>}"
[ -x "$ZIG" ] || {
    echo "找不到 zig: $ZIG" >&2
    echo "先安装工具链: python3 tools/fetch_zig.py" >&2
    echo "或指定已有 zig: ZIG=/path/to/zig bash build.sh $NAME" >&2
    exit 1
}
SRCS="start.S $NAME.c"
[ -f "$NAME.S" ] && SRCS="$SRCS $NAME.S"      # 内核类程序带配套 trap 汇编
"$ZIG" cc -target riscv32-freestanding -mcpu=generic_rv32+m -Os \
    -ffreestanding -nostdlib -fno-stack-protector \
    -Wl,-T,link.ld -o "$NAME.elf" $SRCS
"$ZIG" objcopy -O binary "$NAME.elf" "$NAME.bin"
echo "OK c/$NAME.bin($(stat -c%s "$NAME.bin") 字节)"
