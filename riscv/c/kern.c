/* kern.c —— 时间片多任务内核(machine mode,单地址空间,无 MMU)
 *
 * 流程:start.S 立内核栈 → cmain 设 mtvec、建两个任务上下文、点定时器 →
 * enter_first 进任务 0;之后 CLINT 定时中断进 trap_entry,trap.S 存现场、
 * 调 trap_handler_c(round-robin 选下一个任务 + 重排 mtimecmp)、mret 切换。
 * UART 上应看到 A 与 B 交替成段——那就是时间片。
 */
volatile unsigned char * const UART = (volatile unsigned char *)0x10000000u;

#define SLICE 10000u
#define MTIMECMP_LO (*(volatile unsigned *)0x02004000u)
#define MTIMECMP_HI (*(volatile unsigned *)0x02004004u)
#define MTIME_LO    (*(volatile unsigned *)0x0200BFF8u)
#define MTIME_HI    (*(volatile unsigned *)0x0200BFFCu)

static void uart_putc(char c)
{
    *UART = (unsigned char)c;
}

/* 与 kern.S 的偏移一一对应:r[0]=x1 ... r[30]=x31,mepc=124,mstatus=132 */
struct ctx {
    unsigned r[31];
    unsigned mepc;
    unsigned mcause;
    unsigned mstatus;
};

/* 每个 slot 1KB:ctx 放在 +768,头 632 字节留给 trap_handler_c 的 C 栈帧 */
static unsigned char slots[2][1024] __attribute__((aligned(16)));
static unsigned char stk_a[1024] __attribute__((aligned(16)));
static unsigned char stk_b[1024] __attribute__((aligned(16)));

static struct ctx * const ctxp[2] = {
    (struct ctx *)(slots[0] + 768),
    (struct ctx *)(slots[1] + 768),
};

static unsigned long long now(void)
{
    return ((unsigned long long)MTIME_HI << 32) | MTIME_LO;
}

static void rearm(void)
{
    unsigned long long t = now() + SLICE;
    MTIMECMP_LO = (unsigned)t;
    MTIMECMP_HI = (unsigned)(t >> 32);
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

static void task_a(void)
{
    unsigned tick = 0;
    for (;;) {
        uart_putc('[');
        uart_putdec(tick++);
        uart_putc(']');
        for (volatile int d = 0; d < 1500; d++)
            ;
    }
}

static void task_b(void)
{
    for (;;) {
        uart_putc('B');
        for (volatile int d = 0; d < 1500; d++)
            ;
    }
}

static void init_ctx(struct ctx *c, void (*fn)(void), unsigned char *top)
{
    int i;
    for (i = 0; i < 31; i++)
        c->r[i] = 0;
    c->r[1] = (unsigned)top;                   /* r[1] = x2 = sp */
    c->mepc = (unsigned)fn;
    c->mstatus = 0x80;                         /* MPIE:mret 后自动开中断 */
}

unsigned *trap_handler_c(unsigned *old)
{
    static int pick = 0;
    (void)old;
    rearm();
    pick ^= 1;                                 /* round-robin:两个任务轮流 */
    return (unsigned *)(void *)ctxp[pick];
}

extern void trap_entry(void);
extern void enter_first(unsigned *ctx0);

int cmain(void)
{
    unsigned t = (unsigned)trap_entry;
    __asm__ volatile ("csrw 0x305, %0" :: "r"(t));       /* mtvec */
    t = 0x80;
    __asm__ volatile ("csrw 0x304, %0" :: "r"(t));       /* mie.MTIE */
    init_ctx(ctxp[0], task_a, stk_a + sizeof stk_a);
    init_ctx(ctxp[1], task_b, stk_b + sizeof stk_b);
    rearm();
    uart_putc('|');                            /* 内核就绪标记 */
    enter_first((unsigned *)ctxp[0]);
    return 0;
}
