/* hello.c —— 第一个跑在自己 RV32I CPU 上的 C 程序(freestanding,无 libc)
 *
 * MMIO 约定与 rv/cpu.py 对齐:
 *   0x10000000 写一个字节 = UART 发送;ecall = 停机,a0 为退出码
 * 入口约定:start.S 先设好栈指针再 call cmain,C 侧只管写 cmain。
 */
volatile unsigned char * const UART = (volatile unsigned char *)0x10000000u;

static void uart_putc(char c)
{
    *UART = (unsigned char)c;
}

static void uart_puts(const char *s)
{
    while (*s)
        uart_putc(*s++);
}

int cmain(void)
{
    uart_puts("Hello from C, running on my own RV32I core!\n");
    return 0;
}
