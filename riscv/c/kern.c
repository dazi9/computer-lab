/* kern.c —— 时间片多任务内核 v2:睡眠队列 + 空闲任务(wfi)
 *
 * task_a:十进制时钟,每打一个数 kern_sleep(5 片)——调度器跳过睡眠任务
 * task_b:图形任务(XOR 弹跳小球),每 8 帧睡 2 片
 * 全部任务睡着时:调度器把 mtimecmp 设到最近闹钟,切进 idle 任务 wfi 打盹,
 * 下一个闹钟 trap 进来唤醒到点的任务——wfi 从"能跑"变成"有用"
 *
 * kern_sleep 关中断更新状态(csrci/csrsi),防定时 trap 在状态写一半时切走
 */
volatile unsigned char * const UART = (volatile unsigned char *)0x10000000u;

#define SLICE 10000u
#define NTASKS 2
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

/* 每个 slot 1KB:ctx 放在 +768,头部留给 trap_handler_c 的 C 栈帧 */
static unsigned char slots[NTASKS][1024] __attribute__((aligned(16)));
static unsigned char stk_a[1024] __attribute__((aligned(16)));
static unsigned char stk_b[1024] __attribute__((aligned(16)));
static unsigned char stk_idle[512] __attribute__((aligned(16)));
static struct ctx idle_ctx;

static struct ctx * const ctxp[NTASKS] = {
    (struct ctx *)(slots[0] + 768),
    (struct ctx *)(slots[1] + 768),
};

#define RUN 0
#define SLEEPING 1
static int state[NTASKS];
static unsigned long long wake_at[NTASKS];
static volatile int g_cur = 0;

static unsigned long long now(void)
{
    return ((unsigned long long)MTIME_HI << 32) | MTIME_LO;
}

static void set_mtimecmp(unsigned long long t)
{
    MTIMECMP_LO = (unsigned)t;
    MTIMECMP_HI = (unsigned)(t >> 32);
}

static void rearm(void)
{
    set_mtimecmp(now() + SLICE);
}

void kern_sleep(unsigned ticks)
{
    int id = g_cur;
    __asm__ volatile ("csrci 0x300, 8");       /* MIE←0:状态更新要原子 */
    wake_at[id] = now() + ticks;
    state[id] = SLEEPING;
    __asm__ volatile ("csrsi 0x300, 8");       /* MIE←1,等下一个 trap 切走 */
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
        kern_sleep(5 * SLICE);                 /* 睡 5 片,把 CPU 让给图形任务 */
    }
}

static void task_b(void)
{
    volatile unsigned char * const FB = (volatile unsigned char *)0x10001000u;
    static const unsigned char sprite[6] = {0x3C, 0x7E, 0xFF, 0xFF, 0x7E, 0x3C};
    int x = 8, y = 4, dx = 1, dy = 1;
    unsigned frame = 0;
    for (;;) {
        int r;
        for (r = 0; r < 6; r++) {              /* XOR 画 */
            volatile unsigned char *p = FB + (unsigned)(y + r) * 8
                                       + (unsigned)x / 8;
            unsigned shift = (unsigned)x % 8;
            *p ^= (unsigned char)(sprite[r] >> shift);
            if (shift)
                p[1] ^= (unsigned char)(sprite[r] << (8 - shift));
        }
        for (volatile int d = 0; d < 800; d++)
            ;
        for (r = 0; r < 6; r++) {              /* XOR 擦 */
            volatile unsigned char *p = FB + (unsigned)(y + r) * 8
                                       + (unsigned)x / 8;
            unsigned shift = (unsigned)x % 8;
            *p ^= (unsigned char)(sprite[r] >> shift);
            if (shift)
                p[1] ^= (unsigned char)(sprite[r] << (8 - shift));
        }
        if (x == 0) dx = 1;
        if (x == 56) dx = -1;
        if (y == 0) dy = 1;
        if (y == 26) dy = -1;
        x += dx;
        y += dy;
        uart_putc('B');
        if (++frame % 8 == 0)
            kern_sleep(2 * SLICE);             /* 偶尔也眯一会儿,触发 idle 路径 */
    }
}

static void idle_task(void)
{
    for (;;)
        __asm__ volatile ("wfi");              /* 全体睡着:打盹到最近闹钟 */
}

static void init_ctx(struct ctx *c, void (*fn)(void), unsigned char *top)
{
    int i;
    for (i = 0; i < 31; i++)
        c->r[i] = 0;
    c->r[1] = (unsigned)top;                   /* r[1] = x2 = sp */
    c->mepc = (unsigned)fn;
    c->mstatus = 0x80;                         /* MPIE:mret 后开中断 */
}

unsigned *trap_handler_c(unsigned *old)
{
    int i, nxt;
    unsigned long long t, w;
    int all_asleep = 1;
    (void)old;
    t = now();
    for (i = 0; i < NTASKS; i++) {             /* 唤醒到点的 */
        if (state[i] == SLEEPING && t >= wake_at[i])
            state[i] = RUN;
        if (state[i] == RUN)
            all_asleep = 0;
    }
    if (all_asleep) {                          /* 全睡着:idle 到最近闹钟 */
        w = ~0ULL;
        for (i = 0; i < NTASKS; i++)
            if (wake_at[i] < w)
                w = wake_at[i];
        set_mtimecmp(w);
        g_cur = NTASKS;                        /* idle 的编号 */
        return (unsigned *)(void *)&idle_ctx;
    }
    nxt = g_cur;                               /* round-robin 找可运行任务 */
    for (i = 0; i <= NTASKS; i++) {
        nxt = (nxt + 1) % NTASKS;
        if (state[nxt] == RUN)
            break;
    }
    g_cur = nxt;
    rearm();
    return (unsigned *)(void *)ctxp[nxt];
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
    init_ctx(&idle_ctx, idle_task, stk_idle + sizeof stk_idle);
    rearm();
    uart_putc('|');                            /* 内核就绪标记 */
    enter_first((unsigned *)ctxp[0]);          /* a0 = ctx0,一去不回 */
    return 0;
}
