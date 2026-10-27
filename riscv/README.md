# RISC-V 全家桶 —— 阶段 1:RV32I 核心(纯 CPU 软件仿真)

自己的 RV32I CPU + 自己的汇编器 + 第一个跑在自己 CPU 上的程序。
零第三方依赖(纯 Python 标准库)、零 GPU、零 apt,所有文件在本目录。

## 进度

- [x] **阶段 1**:RV32I 核心 —— 40 条基础指令 + ecall/ebreak/fence + MMIO UART/输入
- [x] **阶段 2(提前完成)**:RV32I 汇编器 —— 伪指令 li/la/mv/not/neg/nop/j/call/ret,数据段 .string/.byte/.word/.space
- [x] **阶段 3**:C 跑在自己 CPU 上 —— zig 0.17.0(装在 ~/computer-lab/tools/zig),
      `zig cc -target riscv32-freestanding -mcpu=generic_rv32` 交叉编译,start.S 统一入口,
      hello.c 与 sum.c(含栈/数组/函数调用,自检退出码)全部通过
- [x] **阶段 3b**:framebuffer MMIO(0x10001000,64x32 位图,256 字节,MSB=行内最左)
      + C 版弹跳小球 bounce.c(XOR 画/擦、跨字节精灵、忙等帧延时),--fb-every 快照验证
- [x] **阶段 4**:裸机内核 —— Zicsr(csrrw/s/c + 立即数形式、mret)、CLINT 式
      mtime/mtimecmp(0x0200BFF8/0x02004000,mtime 每指令 +1)、machine-mode trap
      (mstatus 位洗牌 + mepc/mcause)+ 非法指令进 trap(mcause=2);
      内核 kern.S(31 寄存器现场保存 + mscratch 交换)+ kern.c(round-robin
      调度器),两个 C 任务在 UART 上交替输出 —— 199 次时间片切换实测通过
- [x] **M 扩展**:mul/mulh/mulhsu/mulhu/div/divu/rem/remu(RISC-V 除零/溢出特殊值
      全按规范实现),C 里 `*` `/` `%` 解锁;build.sh 用 `-mcpu=generic_rv32+m`
- [x] **link.ld /DISCARD/ 修复**:lld 会把孤儿节 .eh_frame_hdr/.eh_frame 随机排到
      .text 前面,平铺二进制开头变成 unwind 数据 → CPU 开机吃垃圾;裸机必须显式丢弃
- [x] **内核 sp 保存修复(经典 osdev bug)**:`csrrw sp,mscratch,sp` 交换后,x2 已是
      ctx 指针,保存循环存进去的是指针而非任务 sp;修复 = 保存循环后从 mscratch
      把真实 sp 补写回 x2 槽位。修复前任务栈形同虚设('A'/'B' 版本纯属侥幸)
- [x] **内核任务升级**:task_a = 十进制时钟(`[0][1][2]…`,C 除法/取模),与
      task_b('B')交替,627 次切换零乱码;deci.c 隔离实验定位法 = 二分问题侧
- [x] **wfi 指令**(0x10500073):确定性休眠——快进 mtime 到下一个闹钟,下一步中断
      检查自然触发;单元测试断言 3 次 trap 只用 <60 步(忙等版要 ~130 步)
- [x] **内核图形任务**:task_b 在 framebuffer 上 XOR 弹跳小球,与十进制时钟任务
      分时共享 CPU,冒烟测试采样断言"小球出现过";asm.py 支持 wfi 助记符
- [x] **内核 v2:睡眠队列 + idle 任务**:`kern_sleep(ticks)` 关中断原子更新任务状态、
      拨 mtimecmp 到"现在"强制立刻让出;调度器跳过 SLEEPING 任务、唤醒到点的;
      全体睡着时切进 idle 任务 wfi 到最近闹钟。实测输出 `|[0]BBBBBBBB[1]BBBBBBBB[`
      (时钟任务睡 5 片,图形任务在窗口里连跑 8 帧),280 次切换
- [x] **内核 v3:邮箱消息传递**:kern_send/kern_recv 单槽邮箱,阻塞侧睡到
      `wake_at = NEVER`(仅对方可唤醒),投递/取走方直接把 peer 置回 RUN 并立刻
      让出;生产者(时钟,`+`)→ 消费者(回显 `<N>` + framebuffer 小球走一步)。
      冒烟断言"消息严格递增、不丢不重"通过 → 输出 `|+<0>+<1>+<2>+<3>…`
- [x] **内核 v4:环形缓冲邮箱(8 槽)+ IPC 唤醒语义修复**:v3 的 wake_peer 会把
      睡定时器的对方误唤醒;kern.S 任务突发 3 连发(缓冲吸收,输出 `+++<0><1><2>`)
      → 生产者突发的节奏 + 消息严格递增断言 + FB 小球全部通过
- [x] **终端实况模式**:`--live` + `watch.sh`——半块字符实时渲染 framebuffer
      小球 + UART 消息流滚动 + CYC/MTIME 统计,ESC 退出、+/- 运行中调速;
      非 tty 环境自动退回无头(CI/管道可用)
- [x] **键盘全栈打通**:实况模式把终端按键(含方向键→WASD 映射)喂进输入设备
      MMIO,内核任务轮询 `0x10000004/08` 读取,回显到串口并用 WASD 操纵小球方向;
      冒烟测试注入 wasd 并断言四个键全部经 MMIO 回显——终端→模拟器→MMIO→
      内核任务→framebuffer 的完整交互链路闭环
- [x] **微操作系统(v5):M/U 两级特权 + ecall 系统调用表**:CPU 增加 mode 跟踪与
      mstatus.MPP 进出栈;U 模式下 CSR/wfi/mret → trap(mcause=2),ecall → 系统调用
      trap(mcause=8)。系统调用表:halt/putc/putdec/sleep/send/recv/gettime;阻塞式
      send/recv 在内核态完成(mepc 不推进,醒来重试);SYS_HALT 经 halt_stub 在 M 模式
      停全机。任务全部降入 U 模式,内核独占 CSR。21/21 测试含 U 模式 CSR/wfi 非法、
      U ecall 变系统调用两个新用例
- [x] **调度语义修正**:syscall 不是抢占点(只有定时器中断或任务自阻塞才切换)——
      否则每个 ecall 都轮转任务,字符级乱插队;以及重构回归:定时器路径漏调
      wake_due_tasks 导致 idle 永不唤醒(冒烟 + ELF 符号定位抓出)
- [ ] 收尾候选:中断嵌套、优先级调度、PMP 内存隔离、FORTH on metal、CHIP-8 套娃
- [ ] 待办:CPU 尚无 M 扩展(乘除法)——C 程序里出现 `*`/`/` 时需要补 M 或避免使用

## MMIO 约定(与 QEMU virt 板对齐,方便将来接真工具链)

    0x10000000 + 0    写:UART 发送一个字节(收集在 cpu.uart_out)
    0x10000000 + 4    读:1 = 有输入可读,0 = 无
    0x10000000 + 8    读:弹出一个输入字符,空则 0xFFFFFFFF
    0x10001000~+FF    framebuffer:64x32 位图,每行 8 字节,MSB = 行内最左像素
    ecall             停机,退出码 = a0(x10)

RAM 从 0x80000000 开始,程序入口即 0x80000000,小端。

## 命令

    cd ~/computer-lab/riscv
    python3 -m rv.emu programs/hello.asm       # Hello, RISC-V!
    python3 -m rv.emu c/kern.bin --max-steps 2000000   # 多任务内核 UART 时序流
    bash watch.sh                              # 实况围观内核(真实终端,ESC 退出)
    python3 -m rv.emu programs/hello.asm --trace   # 逐步看 PC 和指令字
    python3 -m rv.asm programs/hello.asm -o programs/hello.bin
    python3 tests/test_rv.py                   # 单元测试

## 布局

    rv/cpu.py       核心:decode() 是指令字段的唯一真相,step() 按 opcode 分发
    rv/asm.py       两遍扫描汇编器;li/la 恒展开为 lui+addi(尺寸可预测)
    rv/emu.py       运行器 CLI(.asm/.bin 通吃)
    programs/       hello / count 汇编源
    tests/          编码基准(手算规范编码)+ 行为断言 + 端到端

## C 工具链(阶段 3)

    cd ~/computer-lab/riscv
    bash c/build.sh hello && python3 -m rv.emu c/hello.bin
    bash c/build.sh sum   && python3 -m rv.emu c/sum.bin

- zig 0.17.0 装在 `~/computer-lab/tools/zig`(fetch_zig.py 自动下载,零 apt)
- 关键旗标:`-target riscv32-freestanding -mcpu=generic_rv32`(纯 RV32I,**必须砍掉
  默认的 C 压缩扩展**,否则 16 位指令会被当 4 字节读) + `-Os`(关掉 Debug 的 UBSan)
- C 侧约定:`_start` 在 start.S(先 `li sp, 0x80400000` 立栈,再 `call cmain`,
  返回值经 a0 变成 ecall 退出码);C 只写 `int cmain(void)`
- link.ld 把 .text.start 固定在 0x80000000,flat binary 经 objcopy 生成

## 实现要点

- 六种指令格式 R/I/S/B/U/J 的立即数位序是重灾区:B 型把 imm[4:1|11] 拆进
  [11:8|7],J 型把 imm[10:1|11|19:12] 拆进 [30:21|20|19:12] —— 所以测试里
  放了手算的规范编码做基准,并做了"编码 → 译码"往返断言
- li/la 恒定展开成 lui+addi 两条(%hi/%lo 做 +0x800 舍入),尺寸可预测,
  两遍扫描才不会被前向引用的常量尺寸坑到
- 允许非对齐访存(按字节读写实现,天然支持);PC 必须对齐,否则报错
