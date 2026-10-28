# Computer Lab —— 纯 CPU 软件仿真实验室

在一台"夜间被 GPU 训练任务独占"的机器上,只用 CPU 和终端,从零构建计算机
世界的每一层。**零 GPU、零 apt、零第三方 Python 依赖**,工具链自包含在
`tools/` 下,所有代码只活在本目录里。

```
与非门思维 → CHIP-8 虚拟机 → RV32I+M CPU → 自研汇编器 → zig cc 交叉编译
→ framebuffer 显卡 → CLINT 定时器 + trap → 抢占式内核(睡眠/idle/邮箱 IPC)
```

## 快速开始

克隆到任意目录即可——脚本按自身位置定位,不依赖绝对路径:

```bash
git clone https://github.com/dazi9/computer-lab.git
cd computer-lab

python3 chip8/tests/test_cpu.py      # CHIP-8:15/15
python3 riscv/tests/test_rv.py       # RV32I:21/21
bash chip8/play.sh                   # 在真实终端里玩弹跳小球
```

只有交叉编译 C 程序需要 zig(下载约 60MB,解压约 300MB,不入库):

```bash
python3 tools/fetch_zig.py           # 下载 zig 到 tools/zig
bash riscv/c/build.sh kern           # 重新编译内核
```

下载支持断点续传,中断后重跑会接着下;国内网络可设 `ZIG_MIRROR` 指向镜像。
Windows 用户请在 WSL 里克隆后执行;`play.sh` / `watch.sh` 需要真实 TTY,
不要在管道或重定向里跑。已有 zig 时可用 `ZIG=/path/to/zig` 覆盖工具链路径。

## 项目一览

### `chip8/` —— CHIP-8 虚拟机(热身项目)

1977 年的虚拟机:4KB 内存、16 寄存器、35 条指令、64x32 单色屏。纯标准库。

```bash
bash chip8/play.sh                       # 弹跳小球(自动)
bash chip8/play.sh roms/paddle.ch8       # 挡板:'1'/'4' 控制
python3 chip8/tests/test_cpu.py          # 15/15
python3 chip8/tests/smoke.py             # 无头冒烟
```

### `riscv/` —— RISC-V 全家桶(主线)

自研 RV32I+M CPU、自研汇编器、真编译器(zig cc)交叉编译、framebuffer、
**带 M/U 两级特权与系统调用表的微操作系统**(抢占调度/睡眠队列/idle/邮箱 IPC/
键盘交互)。git 里程碑化管理。详见 `riscv/README.md`。

```bash
cd riscv
python3 -m rv.emu programs/hello.asm        # 汇编器 + 自研 CPU:Hello, RISC-V!
python3 -m rv.emu c/hello.bin               # zig cc 编译的 C 跑在自己 CPU 上
python3 -m rv.emu c/bounce.bin --fb-every 60000   # C 图形任务(快照看球)
python3 -m rv.emu c/kern.bin --max-steps 2000000  # 多任务内核(UART 时序流)
bash watch.sh                               # 实况围观内核,方向键/WASD 操纵小球
python3 tests/test_rv.py                    # 21/21
python3 tests/kern_smoke.py                 # 内核冒烟(调度/邮箱/键盘链路断言)
bash c/build.sh hello                       # 重新交叉编译任一 C 程序
```

### `tools/` —— 自包含工具链与调试器

| 文件 | 用途 |
|---|---|
| `fetch_zig.py` | 下载 zig 0.17.0 到 `tools/zig`(urllib,零 apt;自动识别平台) |
| `elf_sections.py` | 解析 ELF32 节表(定位过 .eh_frame 孤儿节问题) |
| `zig_cpus.py` | 列 zig 支持的 CPU/特性(注意:0.17 的 `-mcpu=X+f` 需验证) |

## 硬件地图(两个模拟器的 MMIO 约定)

| 设备 | CHIP-8 | RISC-V |
|---|---|---|
| 显示 | 64x32 内存位图 + ANSI 渲染 | `0x10001000` framebuffer(256B)+ 终端 UART |
| 输入 | 终端键盘 → 16 键 | `0x10000004/08` 状态/数据寄存器 |
| 串口 | — | 写 `0x10000000` 一字节一出 |
| 定时器 | 60Hz 递减计数器 | CLINT `mtime`(0x0200BFF8,1 指令 1 tick) |
| 停机 | 无限循环 | `ecall`(退出码在 a0) |

## 调试方法论(项目里真实用过三次,层层递进)

1. **输出模式断言**:`[0][1][2]` 连读 → 睡眠没生效;`BB` 相邻 → 调度粒度异常
2. **存储监视点**:子类化 CPU 拦截 `write()`,对可疑地址(如任务 sp 槽位)
   记录每次写入的 PC → 直接抓到肇事指令
3. **反汇编定位**:用 CPU 自己的 `decode()` 翻译二进制,确认 pc=0x240 就是
   trap_entry 第一条 `csrrw sp,mscratch,sp`

## 踩过的深坑(全记录在两个 README 里)

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
