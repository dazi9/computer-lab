/* bounce.c —— 用 C 重写的弹跳小球:在 framebuffer MMIO 上 XOR 绘制/擦除
 *
 * FB 约定:0x10001000 起,64x32 位图,每行 8 字节,MSB = 行内最左像素
 * 无定时器设备,用忙等循环当帧间延时;headless 用 --fb-every 快照验证
 */
volatile unsigned char * const UART = (volatile unsigned char *)0x10000000u;
volatile unsigned char * const FB = (volatile unsigned char *)0x10001000u;

static void uart_puts(const char *s)
{
    while (*s)
        *UART = (unsigned char)*s++;
}

static void draw_ball(int x, int y)
{
    static const unsigned char sprite[6] = {0x3C, 0x7E, 0xFF, 0xFF, 0x7E, 0x3C};
    for (int r = 0; r < 6; r++) {
        volatile unsigned char *p = FB + (unsigned)(y + r) * 8 + (unsigned)x / 8;
        unsigned shift = (unsigned)x % 8;
        *p ^= (unsigned char)(sprite[r] >> shift);          /* XOR:画/擦同一函数 */
        if (shift)
            p[1] ^= (unsigned char)(sprite[r] << (8 - shift));
    }
}

int cmain(void)
{
    int x = 8, y = 4, dx = 1, dy = 1;
    for (int frame = 0; frame < 60; frame++) {
        draw_ball(x, y);
        for (volatile int d = 0; d < 800; d++)              /* 简易帧延时 */
            ;
        draw_ball(x, y);                                    /* XOR 擦除旧位置 */
        if (x == 0) dx = 1;
        if (x == 56) dx = -1;
        if (y == 0) dy = 1;
        if (y == 26) dy = -1;
        x += dx;
        y += dy;
    }
    uart_puts("bounce done\n");
    return 0;
}
