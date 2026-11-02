# Computer Lab —— 纯 CPU 软件仿真实验室

在一台"夜间被 GPU 训练任务独占"的机器上,只用 CPU 和终端,从零构建计算机
世界的每一层。**零 GPU、零 apt、零第三方 Python 依赖**,工具链自包含在
`tools/` 下,所有代码只活在本目录里。

用大白话说:**这个仓库用纯 Python 造了两台"软件电脑"**。它们不是真的
计算机,而是把计算机的每个零件(CPU、内存、屏幕、键盘、时钟)都用代码
模拟出来,所以在你的终端里就能运行程序、玩游戏,还能把"电脑内部"整个
打开——每一条指令、每一个寄存器、每一字节内存都看得见。

```
与非门思维 → CHIP-8 虚拟机 → RV32I+M CPU → 自研汇编器 → zig cc 交叉编译
→ framebuffer 显卡 → CLINT 定时器 + trap → 抢占式内核(睡眠/idle/邮箱 IPC)
```

## 快速开始:三步玩起来

### 第 0 步:准备环境(只要两样东西)

- 一台能开终端的电脑:Windows 用户先装 WSL(管理员 PowerShell 运行
  `wsl --install`,装完进 Ubuntu);Linux / macOS 自带终端就行
- Python 3(WSL/Ubuntu 一般自带;没有就 `sudo apt install python3`)

不用装显卡驱动、不用 pip 装任何包、不用 root 权限——所有依赖都躺在仓库里。

### 第 1 步:下载仓库

```bash
git clone https://github.com/dazi9/computer-lab.git   # 没装 git?网页上 Code → Download ZIP 解压也一样
cd computer-lab                                       # 进入仓库目录
```

### 第 2 步:自检(可选,30 秒)

跑一下两个"考试",全过就说明环境和代码都没问题:

```bash
python3 chip8/tests/test_cpu.py      # 考 CHIP-8 虚拟机:35 条指令逐条验证 → 看到 15/15
python3 riscv/tests/test_rv.py       # 考 RISC-V CPU:21/21
```

### 第 3 步:跑第一个程序

```bash
bash chip8/play.sh                   # 一颗小球在终端里弹跳。这块 64x32 的"屏幕"
                                     # 完全是字符画出来的,没用任何显卡。ESC 退出
```

想自己上手玩,就加载挡板游戏:`bash chip8/play.sh roms/paddle.ch8`,
终端键 `1` 左移、`4` 右移。

### 想把 C 编译给 RISC-V 才需要 zig(可选,跳过不影响玩 CHIP-8)

```bash
python3 tools/fetch_zig.py           # 下载 zig 编译器到 tools/zig(断点续传,断了重跑接着下)
bash riscv/c/build.sh kern           # 用它编译内核
```

国内网络可设 `ZIG_MIRROR` 指向镜像;已有 zig 时可用 `ZIG=/path/to/zig` 覆盖。
Windows 用户请在 WSL 里执行;`play.sh` / `watch.sh` / `scope.sh` 需要
真实终端,不要在管道或重定向里跑。

## 常见问题(新手版)

- **画面乱码 / 小球重影?** 终端窗口太小。普通模式至少 64 列 x 18 行,
  显微镜 chip8 要 92x30、riscv 要 110x35;把字号调小或窗口拉大就好。
- **提示 `c/kern.bin` 之类找不到?** 编译产物 `*.bin` 不入库(不算源码),
  先 `bash riscv/c/build.sh <hello|bounce|kern>` 编一下就有了。
- **想看看"计算机里面"长什么样?** `bash chip8/scope.sh` 或
  `bash riscv/scope.sh` 打开显微镜:空格暂停/继续、`n` 单步一条指令、
  `j/k` 移动光标、`b` 设断点,键位详见两个子 README。
- **能直接双击 play.sh 吗?** 不能,要在终端里用 `bash chip8/play.sh` 运行。

## 项目一览

### `chip8/` —— CHIP-8 虚拟机(热身项目)

CHIP-8 是 1977 年的一套"虚拟机"约定:故意设计得极简,让同一份游戏能在
不同机型上跑。这里用纯 Python 把它完整实现出来——4KB 内存、16 个寄存器、
35 条指令、64x32 单色屏。

```bash
bash chip8/play.sh                       # 自带 demo:弹跳小球,打开就能看
bash chip8/play.sh roms/paddle.ch8       # 能玩的小游戏:挡板,'1' 左移、'4' 右移
bash chip8/scope.sh                      # 显微镜:暂停/单步/断点,看清每条指令、每个字节
python3 chip8/tests/test_cpu.py          # 单元测试:35 条指令逐条验证(15/15 通过)
python3 chip8/tests/smoke.py             # 无界面冒烟测试(给 CI 用)
```

### `riscv/` —— RISC-V 全家桶(主线)

RISC-V 是真实存在的开放指令集架构(现代 CPU 说的"语言")。这里从零写了
一个能跑真程序的 RISC-V CPU,再配上自研汇编器、C 交叉编译(zig cc)、
"显卡"(framebuffer)、定时器,最后长出一个**带 M/U 两级特权与系统调用表的
微操作系统**(抢占调度/睡眠队列/idle/邮箱 IPC/键盘交互)。git 里程碑化管
理,详见 `riscv/README.md`。

```bash
cd riscv
python3 -m rv.emu programs/hello.asm     # 第一个程序:自研汇编器 + 自研 CPU,输出 Hello, RISC-V!
bash c/build.sh hello                    # 用 zig 把 C 编译成自研 CPU 能吃的机器码
python3 -m rv.emu c/hello.bin            # 刚编译出来的 C 程序,跑在自己写的 CPU 上
bash c/build.sh bounce && python3 -m rv.emu c/bounce.bin --fb-every 60000   # C 写的弹跳小球(往"显卡"上画)
bash c/build.sh kern                     # 编译"迷你操作系统":两个任务轮流执行
python3 -m rv.emu c/kern.bin --max-steps 2000000        # 看内核在串口上打出的任务切换时序
bash watch.sh                            # 实况画面围观内核,方向键/WASD 操纵小球
bash scope.sh                            # 显微镜:单步看每个寄存器/每条指令/系统调用
python3 tests/test_rv.py                 # 单元测试:21/21
python3 tests/kern_smoke.py              # 内核冒烟:调度/邮箱/键盘链路全程断言
```

### `tools/` —— 自包含工具链与调试器(只活在本目录,不装进系统)

| 文件 | 用途 |
|---|---|
| `fetch_zig.py` | 下载 zig 0.17.0 到 `tools/zig`(urllib,零 apt;自动识别平台) |
| `elf_sections.py` | 解析 ELF32 节表(定位过 .eh_frame 孤儿节问题) |
| `zig_cpus.py` | 列 zig 支持的 CPU/特性(注意:0.17 的 `-mcpu=X+f` 需验证) |

## 进阶:两个模拟器的"硬件"约定(新手可先跳过)

### 硬件地图(MMIO 约定)

| 设备 | CHIP-8 | RISC-V |
|---|---|---|
| 显示 | 64x32 内存位图 + ANSI 渲染 | `0x10001000` framebuffer(256B)+ 终端 UART |
| 输入 | 终端键盘 → 16 键 | `0x10000004/08` 状态/数据寄存器 |
| 串口 | — | 写 `0x10000000` 一字节一出 |
| 定时器 | 60Hz 递减计数器 | CLINT `mtime`(0x0200BFF8,1 指令 1 tick) |
| 停机 | 无限循环 | `ecall`(退出码在 a0) |

### 调试方法论(项目里真实用过三次,层层递进)

1. **输出模式断言**:`[0][1][2]` 连读 → 睡眠没生效;`BB` 相邻 → 调度粒度异常
2. **存储监视点**:子类化 CPU 拦截 `write()`,对可疑地址(如任务 sp 槽位)
   记录每次写入的 PC → 直接抓到肇事指令
3. **反汇编定位**:用 CPU 自己的 `decode()` 翻译二进制,确认 pc=0x240 就是
   trap_entry 第一条 `csrrw sp,mscratch,sp`

### 踩过的深坑(全记录在两个 README 里)

- 译码分发电位用错(寄存器下标 ≠ 指令族)——单元测试几分钟逼出
- Python `dict.get(k, parse_int(k))` 默认值急切求值
- CSR 字典整数键/字符串键混用 → 中断永不触发
- mstatus 位洗牌方向写反 + mret 漏 `MPIE←1` → 只有第一次中断
- CLINT 复位值必须为 0(64 位 RMW 写半字会保留高位)
- lld 把孤儿节 `.eh_frame` 随机排到 `.text` 前 → 裸机必须 `/DISCARD/`
- trap 保存循环里 `csrrw sp,mscratch,sp` 交换后 x2 已是 ctx 指针,
  真实 sp 要从 mscratch 补写回——否则任务栈形同虚设

## 版本管理

git 仓库按真实开发时间线组织(15 个提交,01:16 → 07:00)。说明:
- 内核演进为**真实中间版本**:kern.c v1(A/B 忙等)→ v2(睡眠队列)→
  v3(单槽邮箱)→ v4(环形缓冲)→ v5(微操作系统),kern.S 含带
  sp 交换 bug 的初版与修复版,`git log -p riscv/c/kern.c` 可看完整进化史
- 其余文件在归属阶段以终态快照入库(rv 下文件含后续增强,已注明)
- `tools/zig/`(约 300MB 工具链)不入库,`fetch_zig.py` 一键重建

## 约束合规

零 GPU/CUDA(全程纯 CPU 指令解释);零驱动安装、零重启、零杀进程;
Python 依赖只用标准库(venv 预留未动);apt 一次没用过;token 全程节约
(单机单进程串行推进,未动用并行 agent)。

## 许可

MIT,见 [LICENSE](LICENSE)。
