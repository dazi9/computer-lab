# start.S —— 所有 C 程序的统一入口:先立栈指针,再进 C
# 我们的 CPU 复位后 sp(x2) 为 0,C 函数一碰栈就会写飞,必须先设好
    .section .text.start, "ax", @progbits
    .globl _start
_start:
    li      sp, 0x80400000      # RAM 顶(4MB),栈向下生长
    call    cmain               # a0 = cmain 返回值
    ecall                       # 约定:停机,退出码 = a0
hang:
    j       hang
