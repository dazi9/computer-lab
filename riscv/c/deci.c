/* deci.c —— 隔离实验:无内核,单任务连续 uart_putdec,验证 M 扩展下的十进制转换 */
volatile unsigned char * const UART = (volatile unsigned char *)0x10000000u;

static void uart_putc(char c)
{
    *UART = (unsigned char)c;
}

static void uart_putdec(unsigned v)
{
    char buf[11];
    int i = 0;
    if (v == 0) {
        uart_putc('0');
        return;
    }
    while (v) {
        buf[i++] = (char)('0' + v % 10);
        v /= 10;
    }
    while (i)
        uart_putc(buf[--i]);
}

int cmain(void)
{
    for (unsigned i = 0; i < 25; i++) {
        uart_putc('[');
        uart_putdec(i);
        uart_putc(']');
        for (volatile int d = 0; d < 1500; d++)
            ;
    }
    uart_putc('#');
    return 0;
}
