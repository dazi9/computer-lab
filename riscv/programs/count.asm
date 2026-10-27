# count.asm —— 循环 + 分支 + 算术:从"串口"打出 0~9
        li   t0, 0x10000000  # UART 地址
        li   t1, 0           # 当前数字
        li   t3, 10          # 上界
loop:   addi t2, t1, 48      # ASCII '0'
        sb   t2, 0(t0)
        addi t1, t1, 1
        blt  t1, t3, loop
        li   a0, 0
        ecall
