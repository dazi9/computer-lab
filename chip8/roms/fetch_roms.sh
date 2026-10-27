#!/usr/bin/env bash
# 尝试从网上抓公开测试 ROM;全部失败也没关系,本地有自制 bounce.ch8
set -u
ROMS="$(cd "$(dirname "$0")" && pwd)"
fetch() {
  curl -fsSL --connect-timeout 8 --max-time 30 -o "$2" "$1" \
    && echo "OK   $2" || { rm -f "$2"; echo "MISS $1"; }
}
# Timendus 的 CHIP-8 指令级测试套件(交互跑,屏幕会显示 PASS/FAIL)
fetch https://raw.githubusercontent.com/Timendus/chip8-test-suite/main/binaries/chip8-test-suite.ch8 "$ROMS/test-suite.ch8"
# 经典 IBM Logo 开机画面
fetch https://raw.githubusercontent.com/dmatlack/chip8/master/roms/ibm-logo.ch8 "$ROMS/ibm-logo.ch8"
