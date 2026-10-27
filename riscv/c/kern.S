# kern.S —— trap 入口/出口 + 首次进入任务
# 约定:mscratch(0x340)永远持有"当前运行任务"的 ctx 指针
# ctx 布局(字节偏移):x1..x31 → 0..120,mepc=124,mcause=128,mstatus=132,共 136 字节
    .section .text.trap, "ax", @progbits
    .globl trap_entry
    .globl enter_first

trap_entry:
    csrrw sp, 0x340, sp          # sp ↔ mscratch:sp 现在指向当前任务 ctx
    sw x1, 0(sp)
    sw x2, 4(sp)
    sw x3, 8(sp)
    sw x4, 12(sp)
    sw x5, 16(sp)
    sw x6, 20(sp)
    sw x7, 24(sp)
    sw x8, 28(sp)
    sw x9, 32(sp)
    sw x10, 36(sp)
    sw x11, 40(sp)
    sw x12, 44(sp)
    sw x13, 48(sp)
    sw x14, 52(sp)
    sw x15, 56(sp)
    sw x16, 60(sp)
    sw x17, 64(sp)
    sw x18, 68(sp)
    sw x19, 72(sp)
    sw x20, 76(sp)
    sw x21, 80(sp)
    sw x22, 84(sp)
    sw x23, 88(sp)
    sw x24, 92(sp)
    sw x25, 96(sp)
    sw x26, 100(sp)
    sw x27, 104(sp)
    sw x28, 108(sp)
    sw x29, 112(sp)
    sw x30, 116(sp)
    sw x31, 120(sp)
    csrrs t0, 0x340, x0          # 真实任务 sp 被换到了 mscratch
    sw t0, 4(sp)                 # 补写 x2 槽位(上面存的是换入的 ctx 指针)
    csrrs t0, 0x341, x0          # mepc
    sw t0, 124(sp)
    csrrs t0, 0x342, x0          # mcause
    sw t0, 128(sp)
    csrrs t0, 0x300, x0          # mstatus
    sw t0, 132(sp)
    addi a0, sp, 0               # a0 = 被打断任务的 ctx
    call trap_handler_c          # C:重排定时器、选下一任务,返回新 ctx

restore_ctx:
    csrw 0x340, a0               # mscratch ← 新 ctx(趁 a0 还没被覆盖)
    addi sp, a0, 0
    lw t0, 124(sp)
    csrw 0x341, t0               # mepc
    lw t0, 132(sp)
    csrw 0x300, t0               # mstatus
    lw x1, 0(sp)
    lw x3, 8(sp)
    lw x4, 12(sp)
    lw x5, 16(sp)
    lw x6, 20(sp)
    lw x7, 24(sp)
    lw x8, 28(sp)
    lw x9, 32(sp)
    lw x10, 36(sp)
    lw x11, 40(sp)
    lw x12, 44(sp)
    lw x13, 48(sp)
    lw x14, 52(sp)
    lw x15, 56(sp)
    lw x16, 60(sp)
    lw x17, 64(sp)
    lw x18, 68(sp)
    lw x19, 72(sp)
    lw x20, 76(sp)
    lw x21, 80(sp)
    lw x22, 84(sp)
    lw x23, 88(sp)
    lw x24, 92(sp)
    lw x25, 96(sp)
    lw x26, 100(sp)
    lw x27, 104(sp)
    lw x28, 108(sp)
    lw x29, 112(sp)
    lw x30, 116(sp)
    lw x31, 120(sp)
    lw x2, 4(sp)                 # sp 必须最后恢复,否则上面的偏移全错
    mret                         # MIE ← MPIE,回到任务现场

enter_first:
    csrw 0x340, a0               # mscratch ← ctx0(a0 由 C 传入)
    j restore_ctx

    .globl halt_stub
halt_stub:                       # SYS_HALT:内核把 mepc 指到这,M 模式执行 ecall 停机
    ecall
