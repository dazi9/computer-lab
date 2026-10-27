/* kern.c —— v3:邮箱消息传递(生产者/消费者)+ 睡眠队列 + idle 任务
 *
 * task_a 生产者:每 5 片投一个时钟 tick 进邮箱('+')
 * task_b 消费者:阻塞收消息,回显 <N>,并让 framebuffer 小球走一步
 *
 * 通信原语 kern_send/kern_recv:单槽邮箱;收不到/发不出就"睡到被对方唤醒"
 * (wake_at = NEVER,不自醒),投递/取走的一方直接把对方置回 RUN 并立刻让出。
 * 消息不丢、不重、有序——由 tests/kern_smoke.py 的严格递增断言把关。
 */
volatile unsigned char * const UART = (volatile unsigned char *)0x10000000u;

#define SLICE 10000u
#define NTASKS 2
#define NEVER 0xFFFFFFFFFFFFFFFFULL
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

/* 每个 slot 1KB:ctx 放 +768,头部留给 trap_handler_c 的 C 栈帧 */
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
    __asm__ volatile ("csrsi 0x300, 8");
    set_mtimecmp(now());                       /* 立刻让出 CPU */
}

static void block_me(void)                     /* 睡到对方唤醒(NEVER 不自醒) */
{
    int id = g_cur;
    __asm__ volatile ("csrci 0x300, 8");
    wake_at[id] = NEVER;
    state[id] = SLEEPING;
    __asm__ volatile ("csrsi 0x300, 8");
    set_mtimecmp(now());
}

static void wake_peer(void)                    /* 把对方置回 RUN 并立刻让出 */
{
    int peer = 1 - g_cur;
    __asm__ volatile ("csrci 0x300, 8");
    state[peer] = RUN;
    __asm__ volatile ("csrsi 0x300, 8");
    set_mtimecmp(now());
}

/* ---- 单槽邮箱 ---- */
static volatile int mail_full = 0;
static volatile unsigned mail_val;

void kern_send(unsigned v)
{
    for (;;) {
        __asm__ volatile ("csrci 0x300, 8");
        if (!mail_full) {
            mail_val = v;
            mail_full = 1;
            __asm__ volatile ("csrsi 0x300, 8");
            wake_peer();
            return;
        }
        __asm__ volatile ("csrsi 0x300, 8");
        block_me();                            /* 满:睡到消费者取走 */
    }
}

unsigned kern_recv(void)
{
    for (;;) {
        __asm__ volatile ("csrci 0x300, 8");
        if (mail_full) {
            unsigned v = mail_val;
            mail_full = 0;
            __asm__ volatile ("csrsi 0x300, 8");
            wake_peer();
            return v;
        }
        __asm__ volatile ("csrsi 0x300, 8");
        block_me();                            /* 空:睡到生产者投递 */
    }
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

/* XOR 画/擦 8x6 精灵 */
static void draw_sprite(volatile unsigned char *FB, int x, int y, int erase)
{
    static const unsigned char sprite[6] = {0x3C, 0x7E, 0xFF, 0xFF, 0x7E, 0x3C};
    int r;
    (void)erase;                               /* XOR 本身就是画/擦一体 */
    for (r = 0; r < 6; r++) {
        volatile unsigned char *p = FB + (unsigned)(y + r) * 8
                                   + (unsigned)x / 8;
        unsigned shift = (unsigned)x % 8;
        *p ^= (unsigned char)(sprite[r] >> shift);
        if (shift)
            p[1] ^= (unsigned char)(sprite[r] << (8 - shift));
    }
}

static void task_a(void)                       /* 生产者:时钟 */
{
    unsigned tick = 0;
    for (;;) {
        uart_putc('+');
        kern_send(tick++);
        kern_sleep(5 * SLICE);
    }
}

static void task_b(void)                       /* 消费者:收消息 → 回显 + 小球 */
{
    volatile unsigned char * const FB = (volatile unsigned char *)0x10001000u;
    int x = 8, y = 4, dx = 1, dy = 1;
    draw_sprite(FB, x, y, 0);                  /* 初始画一颗,常驻可见 */
    for (;;) {
        unsigned v = kern_recv();
        draw_sprite(FB, x, y, 1);              /* 擦旧 */
        if (x == 0) dx = 1;
        if (x == 56) dx = -1;
        if (y == 0) dy = 1;
        if (y == 26) dy = -1;
        x += dx;
        y += dy;
        draw_sprite(FB, x, y, 0);              /* 画新 */
        uart_putc('<');
        uart_putdec(v);
        uart_putc('>');
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
    c->mstatus = 0x80;
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
        g_cur = NTASKS;
        return (unsigned *)(void *)&idle_ctx;
    }
    nxt = g_cur;
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
    uart_putc('|');
    enter_first((unsigned *)ctxp[0]);
    return 0;
}
