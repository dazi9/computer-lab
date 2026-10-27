/* sum.c —— 展示"真编译器"产物:函数调用、循环、栈上局部变量、数组寻址
 * 打印 sum(1..100) 的十六进制(移位取半字节,回避 RV32I 没有的除法)
 * 退出码做自检:算对 5050 → 0,算错 → 1
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

static void uart_puthex(unsigned v)
{
    static const char digits[] = "0123456789ABCDEF";
    for (int i = 28; i >= 0; i -= 4)
        uart_putc(digits[(v >> i) & 0xF]);
}

int cmain(void)
{
    int sum = 0;
    for (int i = 1; i <= 100; i++)
        sum += i;
    uart_puts("sum(1..100) = 0x");
    uart_puthex((unsigned)sum);
    uart_puts("\n");
    return sum == 5050 ? 0 : 1;
}
