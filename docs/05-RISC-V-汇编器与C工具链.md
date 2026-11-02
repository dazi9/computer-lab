# 05 · RISC-V:汇编器与 C 工具链

> 这一章你会学到:CHIP-8 汇编器的"放大版"长什么样(伪指令/重定位);
> C 语言为什么需要运行时脚手架(start.S 与栈指针);链接脚本在管什么;
> 以及真编译器 zig cc 空降时踩过的三个真实的坑。
> 配套源码:`riscv/rv/asm.py` + `riscv/c/`(start.S / link.ld / build.sh)

## 先跑起来

```bash
cd ~/computer-lab/riscv
bash c/build.sh hello                     # zig cc 交叉编译 C → RV32I 镜像
python3 -m rv.emu c/hello.bin             # C 程序跑在自己 CPU 上!
bash c/build.sh sum && python3 -m rv.emu c/sum.bin   # 函数调用/栈/数组全用上
```

`Hello from C, running on my own RV32I core!` ——这句话走过五层:
C 源码 → zig cc → RISC-V 机器码 → `rv/cpu.py` 逐条解释 → UART 打字。

## 一、自研汇编器:CHIP-8 版的放大重写

`rv/asm.py` 的骨架与 `chip8/asm.py` 完全同款(两遍扫描),长大在四处:

**1. 伪指令**:一条"假指令"展开成多条真指令:

```python
def expand_pseudo(mnem, args, lineno):
    if mnem in ('li', 'la'):            # 恒展开为 lui+addi
        return ['lui %s, %%hi(%s)' % (args[0], args[1]),
                'addi %s, %s, %%lo(%s)' % (args[0], args[0], args[1])]
```

为什么恒定展开?第一遍扫描要给每条目**定尺寸**——`li` 装小常数只要
一条、装大常数要两条,若按值伸缩,前向引用会把尺寸算乱。恒定两条,
尺寸永远可预测。**这是用 4 字节换确定性**,工程上血赚。

**2. `%hi/%lo` 重定位**:`li a0, 0x12345F00` 拆成高 20 位 + 低 12 位。
直接砍一半(`0x12345` / `0xF00`)会错——因为 addi 的低 12 位是
**有符号**的。诀窍是 +0x800 舍入:

```
0x12345F00 → hi = (0x12345F00 + 0x800) >> 12 = 0x12346
             lo = 0x12345F00 - 0x12346000    = -0x100
验证:0x12346000 + (-0x100) = 0x12345F00 ✓
```

**3. 数据段**:`.string/.byte/.word/.space`——字符串常量、查找表、
缓冲区都能进程序(还记得 `.space 16` 的测试缓冲区吗)。

**4. 操作数方言**:内存写法 `off(rs1)`、字符立即数 `'A'`、
ABI 寄存器名——对齐 GNU as 语法,将来接真工具链零成本。

## 二、请来真编译器:zig cc

自研汇编器能写汇编,但没人手写 C。`zig cc` 是一条命令的交叉编译器:

```bash
bash c/build.sh hello
# 内部实际执行:
# zig cc -target riscv32-freestanding -mcpu=generic_rv32+m -Os
#        -ffreestanding -nostdlib -fno-stack-protector
#        -Wl,-T,link.ld -o hello.elf start.S hello.c
```

三个旗标各有一段故事:

- **`-mcpu=generic_rv32+m`**:明确裁剪指令集。zig 默认 CPU 带 C 压缩
  扩展(16 位指令),我们的 CPU 只认 4 字节——不砍掉,开机第一条
  指令就是天书。`+m` 则补上乘除,让 C 的 `*` `/` `%` 可用
- **`-Os`**:关掉 zig Debug 模式默认注入的 UBSan 运行时(裸机没有
  它的库,链接直接报 undefined symbol)
- **`-nostdlib -ffreestanding`**:没有 libc、没有操作系统——
  printf 内存分配统统不存在,一切自己造

## 三、start.S:C 程序的"产房"

C 编译器默认 `sp`(x2)复位后有值。我们的 CPU 复位后它是 0——
C 函数一进栈就往 0 附近写,**机器直接疯掉**。所以每个 C 程序的
真正入口是一小段汇编(`c/start.S`):

```asm
_start:
    li      sp, 0x80400000      # 先立栈:RAM 顶端,向下生长
    call    cmain               # 再进 C 世界
    ecall                       # cmain 返回值经 a0 变成退出码
```

约定由此确立:**C 只写 `int cmain(void)`,栈和出口由 start.S 代管**。
这就是"运行时(runtime)"的最小形态——glibc 的 `_start` 做的也是
这件事,只是它还管更多。

## 四、link.ld:给代码分配门牌号

CPU 复位后 PC 固定从 0x80000000 取第一条指令。谁保证 `_start`
恰好排在最前面?链接脚本 `c/link.ld`:

```
. = 0x80000000;
.text : { KEEP(*(.text.start)) *(.text .text.*) }
```

`KEEP(*(.text.start))` 把 start.S 的入口钉死在 0x80000000。
这里还埋着一个真实事故:**lld 链接器曾把孤儿节 `.eh_frame`(C++
异常展开用的表,裸机根本用不上)随机排到 .text 前面**,导致平铺
二进制开头是一堆元数据——CPU 开机执行的"第一条指令"是垃圾。
修复:`/DISCARD/ : { *(.eh_frame*) }` 显式丢弃。**链接器脚本是
裸机开发的第二张地图,读不懂它就读不懂内存布局。**

## 五、两种"翻译器"的对照

| | 自研 `rv/asm.py` | zig cc |
|---|---|---|
| 输入 | 手写汇编 | C 源码 |
| 体量 | ~250 行 Python | 数十万行的编译器 |
| 优化 | 无(人写什么样就什么样) | -Os 全套调度 |
| 存在意义 | **教学**:看清"文本→字节"每一步 | **生产力**:让 C 免于手写汇编 |

两者输出的都是同一台 CPU 的指令——这正证明了 ISA 的意义:
**接口不变,生产者随便换**。

## 本章小结

- 两遍扫描 + 恒定展开 = 可预测的汇编器;+0x800 舍入 = %hi/%lo 的正确拆法
- C 程序四件套:start.S(立栈)/ link.ld(门牌)/ build.sh(流水线)/ cmain(入口)
- zig cc 三个旗标的教训:RVC 要显式裁剪、-Os 关 UBSan、裸机没有 libc
- 孤儿节会被链接器随机安置,不 /DISCARD/ 就别怪开机吃垃圾

## 练习

- ★ 修改 `c/hello.c` 的文案,重新 build + run,再 `od -c c/hello.bin`
  找到你改的字符串在二进制里的位置
- ★★ 写 `c/prime.c`:打印 50 以内的质数(需要 `%`,M 扩展已支持),
  用退出码自检质数个数(15 个)
- ★★★ 把 `c/link.ld` 里 `KEEP(*(.text.start))` 改成普通 `*(.text.start)`,
  重新构建并验证程序是否仍然正确(提示:zig 的输出顺序不保证,
  思考 KEEP 在防什么)

——下一章:给 CPU 配外设。framebuffer、UART、键盘——"外设即寄存器"。
