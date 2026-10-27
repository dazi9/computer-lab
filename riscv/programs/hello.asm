# hello.asm —— 第一个跑在自己 CPU 上的程序
# MMIO:每往 0x10000000 写一个字节,等于往"串口"发一个字符
        la   t0, msg         # t0 ← 字符串地址(展开成 lui+addi 两连发)
        li   t1, 0x10000000  # UART 地址
loop:   lb   t2, 0(t0)       # 取一个字节
        beq  t2, x0, halt    # \0 就收工
        sb   t2, 0(t1)       # 发出去
        addi t0, t0, 1
        j    loop
halt:   li   a0, 0
        ecall                # 停机
msg:    .string "Hello, RISC-V!\n"
