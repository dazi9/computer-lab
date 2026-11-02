# CHIP-8 —— 纯 CPU 软件仿真

用大白话说:CHIP-8 是 1977 年设计的一套"迷你假想电脑"的约定,当年故意
做得极简,好让同一份游戏能跑在不同机型上。这里用纯 Python 把它完整造了
出来——4KB 内存、16 个 8 位寄存器、35 条指令、64x32 单色屏,屏幕是用
终端字符画的。**零第三方依赖**(纯 Python 标准库)、**零 GPU**、**零 apt**,
所有文件在本目录内。

## 第一次玩(两步,在仓库根目录、真实终端里执行)

    bash chip8/play.sh                        # ① 什么键都不用按:小球自己弹跳,ESC 退出
    bash chip8/play.sh roms/paddle.ch8        # ② 能玩的挡板游戏:终端键 '1' 左移、'4' 右移

游戏键位:`1234 / qwer / asdf / zxcv` → CHIP-8 小键盘的 `123C / 456D / 789E / A0BF`。
窗口自适应:每帧探测终端尺寸,≥64x18 按 1x(半块字符)居中,≥128x34 自动切
2x(每像素 2 字符宽),拖动窗口即时重排;太小只显示提示,不花屏。

## 显微镜:看看"电脑里面"长什么样(--scope,真实终端)

    bash chip8/scope.sh                        # 默认 bounce
    bash chip8/scope.sh roms/paddle.ch8

把虚拟机拆开看的调试器:反汇编窗口(→ 标当前 PC,● 标断点)+ V0-VF/PC/I/
DT/ST 寄存器列 + 16 位 nibble 逐位分解(hi/x/y/n)+ 64x32 屏 + 内存 hexdump
(跟随 I)。**变化过的寄存器与内存字节染黄,I 指向的字节染青**——球每动
一像素,是哪条 DRW 写的、写了哪个字节,全都看得见。

键位:空格 暂停/继续(默认暂停,可从头单步)、n 单步一条、j/k 移动反汇编
光标、b 在光标处切换断点、g 切换 hexdump 跟随(I↔PC)、+/- 调速、ESC 退出;
游戏键 1234/qwer/asdf/zxcv 照常可用。最小窗口 92x30。

## 改了代码之后:跑测试(无界面,随处可跑)

    cd chip8
    python3 tests/test_cpu.py                       # 35 条指令逐条验证,应看到 15/15
    python3 tests/test_display.py                   # 显示层:缩放/居中/截断
    python3 tests/test_scope.py                     # 显微镜:反汇编/位分解/面板
    python3 tests/smoke.py                          # 120 帧冒烟:球必须真的在动
    python3 -m chip8.emu roms/bounce.ch8 --headless 60 --dump-every 30   # 无界面跑 60 帧并打印画面

## 文件布局

    chip8/cpu.py     虚拟机核心:取指-译码-执行,35 条指令 + 60Hz 定时器
    chip8/emu.py     运行器:无头批处理模式 + 终端交互模式(ANSI 渲染)
    chip8/scope.py   原子级显微镜:反汇编/寄存器/内存 hexdump/单步/断点
    chip8/asm.py     极简汇编器(两遍扫描,标签/DB/注释),附弹跳小球源码
    tests/           15 组指令级单元测试 + 显示层/显微镜测试 + 无头冒烟
    roms/            ROM 与脚本(make_roms.py 自产 bounce/paddle;fetch_roms.sh
                     可抓公开测试 ROM,全部失败也不影响本地自制 ROM)

## 实现说明(进阶)

- 显示走终端 ANSI(半块字符 `▀▄█`,64x32 像素压成 16 行文本),零图形栈;
  每行绝对定位排版,不依赖换行符(raw 模式下 OPOST 关着,单靠换行会画成楼梯)
- 声音是终端蜂鸣 `\a`(ST > 0 时每帧响一声),零音频栈
- 终端没有 keyup 事件,按键 150ms 后自动松开(玩 most games 够用)
- 兼容性开关:`Chip8(shift_legacy=True)` 老机型移位取 Vy 作源;
  `Chip8(mem_legacy=True)` 老机型 FX55/FX65 后 I 不自增

## 下一站 → 已完工:RISC-V 全家桶(../riscv/)

CHIP-8 只是热身。同一套"取指-译码-执行"思路已经在这个仓库的 `riscv/`
里长成了完整的 RISC-V 计算机:自研 CPU + 自研汇编器 + C 交叉编译 +
framebuffer 显卡,最后还长出了带两级特权的微操作系统,详见 `../riscv/README.md`。
