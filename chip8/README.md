# CHIP-8 —— 纯 CPU 软件仿真

一台 1977 年的虚拟机:4KB 内存、16 个 8 位寄存器、35 条指令、64x32 单色屏。
**零第三方依赖**(纯 Python 标准库)、**零 GPU**、**零 apt**,所有文件在本目录内。

## 布局

    chip8/cpu.py     虚拟机核心:取指-译码-执行,35 条指令 + 60Hz 定时器
    chip8/emu.py     运行器:无头批处理模式 + 终端交互模式(ANSI 渲染)
    chip8/asm.py     极简汇编器(两遍扫描,标签/DB/注释),附弹跳小球源码
    tests/           15 组指令级单元测试 + 无头冒烟测试
    roms/            ROM 与脚本(make_roms.py 自产 bounce/paddle;fetch_roms.sh
                     可抓公开测试 ROM——本机 WSL 访问 GitHub 超时,暂未下载成功)

## 玩(在你自己的 WSL 终端里,不要走管道)

    wsl -- bash ~/computer-lab/chip8/play.sh                        # 弹跳小球(自动演示)
    wsl -- bash ~/computer-lab/chip8/play.sh roms/paddle.ch8        # 挡板:终端键 '1' 左移、'4' 右移

键位:`1234 / qwer / asdf / zxcv` → CHIP-8 的 `123C / 456D / 789E / A0BF`,ESC 退出。

## 验证(无头,随处可跑)

    cd ~/computer-lab/chip8
    python3 tests/test_cpu.py                       # 15 组单元测试
    python3 tests/smoke.py                          # 120 帧冒烟:球必须真的在动
    python3 -m chip8.emu roms/bounce.ch8 --headless 60 --dump-every 30

## 实现说明

- 显示走终端 ANSI(半块字符 `▀▄█`,64x32 像素压成 16 行文本),零图形栈
- 声音是终端蜂鸣 `\a`(ST > 0 时每帧响一声),零音频栈
- 终端没有 keyup 事件,按键 150ms 后自动松开(玩 most games 够用)
- 兼容性开关:`Chip8(shift_legacy=True)` 老机型移位取 Vy 作源;
  `Chip8(mem_legacy=True)` 老机型 FX55/FX65 后 I 不自增

## 下一站:RISC-V 全家桶(热身完成后开工)

1. **RV32I 核心**:同一套"取指-译码-执行"骨架,约 47 条指令 + MMIO 终端
2. **自写 RISC-V 汇编器**:本 asm.py 的放大版
3. **C 跑在自己 CPU 上**:zig cc 交叉编译 `-target riscv32-freestanding`
4. **裸机内核**:trap、进程表、时间片多任务
