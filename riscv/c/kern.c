/* kern.c —— v5 微操作系统:M/U 两级特权 + ecall 系统调用表
 *
 * 内核(trap_entry/调度器/邮箱)在 M 模式;任务经 enter_first 的 mret 降入
 * U 模式。U 模式下:CSR/wfi/mret 全部 → trap(mcause=2),ecall → trap
 * (mcause=8)进系统调用表:
 *   0 halt  1 putc  2 putdec  3 sleep  4 send  5 recv  6 gettime
 * 阻塞式 send/recv 在内核态完成:邮箱满/空就把任务标记 SLEEPING
 * (mepc 不推进,醒来重试同一条 ecall),对方投递/取走时置回 RUN。
 * SYS_HALT:内核把 ctx 的 mepc 指到 halt_stub 且 mstatus.MPP=M,mret 后在
 * M 模式执行 ecall → 全机停机。
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

/* ---- 用户态系统调用封装(任务只能走这条路) ---- */
#define SYS_HALT 0
#define SYS_PUTC 1
#define SYS_PUTDEC 2
#define SYS_SLEEP 3
#define SYS_SEND 4
#define SYS_RECV 5
#define SYS_GETTIME 6

static long syscall2(long n, long a)
{
    register long a0 asm("a0") = a;
    register long a7 asm("a7") = n;
    __asm__ volatile ("ecall" : "+r"(a0) : "r"(a7) : "memory");
    return a0;
}

static void sys_putc(char c)
{
    syscall2(SYS_PUTC, c);
}

static void sys_putdec(unsigned v)
{
    syscall2(SYS_PUTDEC, v);
}

static void sys_sleep(unsigned ticks)
{
    syscall2(SYS_SLEEP, ticks);
}

static void sys_send(unsigned v)
{
    syscall2(SYS_SEND, v);
}

static unsigned sys_recv(void)
{
    return (unsigned)syscall2(SYS_RECV, 0);
}

/* ---- 环形缓冲邮箱(仅内核态可碰) ---- */
#define MAIL_CAP 8
static unsigned mail_buf[MAIL_CAP];
static volatile unsigned mail_head, mail_tail, mail_count;

extern void halt_stub(void);

/* ---- 系统调用表(mcause=8 时由 trap_handler_c 调用;内核态,天然原子) ----
 * 返回 NULL = 正常调度流程;返回 ctx = 立刻调度该 ctx(用于 SYS_HALT)。 */
static struct ctx *handle_syscall(struct ctx *c, int id)
{
    unsigned n = c->r[16];                     /* a7 = x17 → r[16] */
    unsigned a0 = c->r[9];                     /* a0 = x10 → r[9] */
    int peer = 1 - id;

    if (n == 1) {                              /* putc */
        uart_putc((char)a0);
        c->r[9] = 0;
        c->mepc += 4;
    } else if (n == 2) {                       /* putdec */
        unsigned v = a0;
        char buf[11];
        int i = 0;
        if (v == 0)
            uart_putc('0');
        while (v) {
            buf[i++] = (char)('0' + v % 10);
            v /= 10;
        }
        while (i)
            uart_putc(buf[--i]);
        c->r[9] = 0;
        c->mepc += 4;
    } else if (n == 3) {                       /* sleep(ticks) */
        wake_at[id] = now() + a0;
        state[id] = SLEEPING;
        c->mepc += 4;                          /* 醒来后从 ecall 下一条继续 */
    } else if (n == 4) {                       /* send:满则睡到对方取走 */
        if (mail_count < MAIL_CAP) {
            mail_buf[mail_tail] = a0;
            mail_tail = (mail_tail + 1) % MAIL_CAP;
            mail_count++;
            c->r[9] = 0;
            c->mepc += 4;
            if (state[peer] == SLEEPING && wake_at[peer] == NEVER)
                state[peer] = RUN;             /* 唤醒等信的人 */
        } else {
            state[id] = SLEEPING;
            wake_at[id] = NEVER;               /* 醒来重试同一条 ecall */
        }
    } else if (n == 5) {                       /* recv:空则睡到对方投递 */
        if (mail_count) {
            c->r[9] = mail_buf[mail_head];
            mail_head = (mail_head + 1) % MAIL_CAP;
            mail_count--;
            c->mepc += 4;
            if (state[peer] == SLEEPING && wake_at[peer] == NEVER)
                state[peer] = RUN;
        } else {
            state[id] = SLEEPING;
            wake_at[id] = NEVER;
        }
    } else if (n == 6) {                       /* gettime */
        c->r[9] = (unsigned)now();
        c->mepc += 4;
    } else if (n == 0) {                       /* halt:M 模式 ecall 停全机 */
        uart_putc('\n');
        c->mepc = (unsigned) &halt_stub;
        c->mstatus = (c->mstatus & ~0x188) | 0x1800 | 0x80;   /* MPP=M, MPIE=1 */
        state[id] = RUN;
        g_cur = id;
        return c;                              /* 立刻调度它 → mret → M 模式 ecall */
    } else {
        c->r[9] = 0xFFFFFFFF;                  /* 未知调用 */
        c->mepc += 4;
    }
    return 0;
}

/* ---- XOR 画/擦 8x6 精灵(任务直写 framebuffer,尚无 PMP 隔离) ---- */
static int bx = 8, by = 4, bdx = 1, bdy = 1;

static void draw_sprite(volatile unsigned char *FB)
{
    static const unsigned char sprite[6] = {0x3C, 0x7E, 0xFF, 0xFF, 0x7E, 0x3C};
    int r;
    for (r = 0; r < 6; r++) {
        volatile unsigned char *p = FB + (unsigned)(by + r) * 8
                                   + (unsigned)bx / 8;
        unsigned shift = (unsigned)bx % 8;
        *p ^= (unsigned char)(sprite[r] >> shift);
        if (shift)
            p[1] ^= (unsigned char)(sprite[r] << (8 - shift));
    }
}

static void poll_keys(void)                    /* 键盘:轮询输入设备(U 可直读) */
{
    volatile unsigned * const IN_READY = (volatile unsigned *)0x10000004u;
    volatile unsigned * const IN_DATA = (volatile unsigned *)0x10000008u;
    while (*IN_READY) {
        unsigned k = *IN_DATA & 0xFF;
        if (k == 'a') bdx = -1;
        else if (k == 'd') bdx = 1;
        else if (k == 'w') bdy = -1;
        else if (k == 's') bdy = 1;
        sys_putc((char)k);                     /* 回显:证明键盘真的进来了 */
    }
}

static void task_a(void)                       /* 生产者(U 模式):3 连发后睡 6 片 */
{
    unsigned tick = 0;
    for (;;) {
        int burst;
        for (burst = 0; burst < 3; burst++) {
            sys_putc('+');
            sys_send(tick++);
        }
        sys_sleep(6 * SLICE);
    }
}

static void task_b(void)                       /* 消费者(U 模式):收消息 → 回显 + 小球 */
{
    volatile unsigned char * const FB = (volatile unsigned char *)0x10001000u;
    draw_sprite(FB);                           /* 初始画一颗,常驻可见 */
    for (;;) {
        unsigned v = sys_recv();
        poll_keys();
        draw_sprite(FB);                       /* XOR:擦旧 */
        if (bx == 0) bdx = 1;
        if (bx == 56) bdx = -1;
        if (by == 0) bdy = 1;
        if (by == 26) bdy = -1;
        bx += bdx;
        by += bdy;
        if (bx < 0) bx = 0;                    /* 手动转向可能越界,夹回来 */
        if (bx > 56) bx = 56;
        if (by < 0) by = 0;
        if (by > 26) by = 26;
        draw_sprite(FB);                       /* 画新 */
        sys_putc('<');
        sys_putdec(v);
        sys_putc('>');
    }
}

static void idle_task(void)                    /* M 模式:wfi 打盹到最近闹钟 */
{
    for (;;)
        __asm__ volatile ("wfi");
}

static void init_ctx(struct ctx *c, void (*fn)(void), unsigned char *top)
{
    int i;
    for (i = 0; i < 31; i++)
        c->r[i] = 0;
    c->r[1] = (unsigned)top;                   /* r[1] = x2 = sp */
    c->mepc = (unsigned)fn;
    c->mstatus = 0x80;                         /* MPIE=1,MPP=U(00)→mret 降入 U */
}

static int task_id_of(unsigned *old)
{
    return (old == (unsigned *)(void *)ctxp[1]) ? 1 : 0;
}

static void wake_due_tasks(void)               /* 把睡够时间的任务置回 RUN */
{
    int i;
    unsigned long long t = now();
    for (i = 0; i < NTASKS; i++)
        if (state[i] == SLEEPING && t >= wake_at[i])
            state[i] = RUN;
}

unsigned *trap_handler_c(unsigned *old)
{
    struct ctx *c = (struct ctx *)old;
    int id = task_id_of(old);
    int i, nxt;
    unsigned long long t, w;
    int all_asleep = 1;

    if (c->mcause == 8) {                      /* U 模式 ecall:系统调用 */
        struct ctx *haltctx = handle_syscall(c, id);
        wake_due_tasks();
        if (haltctx)
            return (unsigned *)(void *)haltctx;
        if (state[id] == RUN)
            return old;                        /* 系统调用不是抢占点,同任务继续 */
    } else if (c->mcause == 2) {               /* U 模式非法指令:跳过并标记 */
        c->mepc += 4;
        uart_putc('!');
        wake_due_tasks();
        if (state[id] == RUN)
            return old;
    } else if ((c->mcause & 0x80000000) == 0) {/* 其他同步异常:跳过并标记 */
        c->mepc += 4;
        uart_putc('?');
        wake_due_tasks();
        if (state[id] == RUN)
            return old;
    }

    /* 到这里 = 定时器抢占 或 当前任务已阻塞:唤醒到点的 + 完整调度 */
    wake_due_tasks();                          /* 定时器路径也要唤醒(重构教训!) */
    for (i = 0; i < NTASKS; i++)
        if (state[i] == RUN)
            all_asleep = 0;
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
    idle_ctx.mstatus |= 0x1800;                /* idle 留在 M 模式(U 的 wfi 非法) */
    rearm();
    uart_putc('|');                            /* 内核就绪标记 */
    enter_first((unsigned *)ctxp[0]);          /* a0 = ctx0,一去不回 */
    return 0;
}
