"""RV32I 核心与汇编器的单元测试:手算规范编码做基准 + 行为断言 + 端到端。

运行:python3 tests/test_rv.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from rv.asm import assemble  # noqa: E402
from rv.cpu import MASK32, RAM_BASE, RV32, decode  # noqa: E402

TESTS = []


def test(fn):
    TESTS.append(fn)
    return fn


def run_src(src, max_steps=10000, **kw):
    c = RV32(**kw)
    c.load(assemble(src))
    c.run(max_steps)
    return c


def word_at(code, i=0):
    return int.from_bytes(code[i * 4:i * 4 + 4], 'little')


@test
def canonical_encodings():
    """手算的规范编码,锁住六种格式的位布局。"""
    cases = [
        ('start: addi x1, x0, 5\nend: nop', 0x00500093),
        ('start: lui x5, 0x12345\nend: nop', 0x123452B7),
        ('start: jal x0, end\nnop\nend: nop', 0x0080006F),
        ('start: beq x1, x2, end\nnop\nend: nop', 0x00208463),
        ('start: sw x2, 4(x1)\nend: nop', 0x0020A223),
        ('start: lw x3, 0(x2)\nend: nop', 0x00012183),
        ('start: srai x1, x1, 3\nend: nop', 0x4030D093),
    ]
    for src, want in cases:
        got = word_at(assemble(src))
        assert got == want, '%s -> %08X, 应为 %08X' % (src.splitlines()[0], got, want)


@test
def decode_roundtrip():
    f = decode(0x00500093)
    assert (f['opcode'], f['rd'], f['f3'], f['rs1'], f['imm']) == (0x13, 1, 0, 0, 5)
    f = decode(0x00208463)
    assert (f['opcode'], f['f3'], f['rs1'], f['rs2'], f['imm']) == (0x63, 0, 1, 2, 8)
    f = decode(0x0080006F)
    assert f['opcode'] == 0x6F and f['imm'] == 8
    # 向后跳:编码再译码必须还原出负偏移
    code = assemble('loop: nop\njal x0, loop')
    assert decode(word_at(code, 1))['imm'] == -4
    code = assemble('loop: nop\nback: beq x0, x0, loop')
    assert decode(word_at(code, 1))['imm'] == -4


@test
def x0_immutable_and_exit_code():
    c = run_src('addi x0, x0, 5\nli a0, 42\necall')
    assert c.x[0] == 0 and c.exit_code == 42


@test
def arith_wrap_and_ops():
    c = run_src('''
        li   t0, -1          # 0xFFFFFFFF
        addi t1, t0, 2       # 回绕 → 1
        li   t2, 3
        li   t3, 5
        sub  t4, t2, t3      # -2 → 0xFFFFFFFE
        and  t5, t0, t3      # 5
        or   t6, x0, t0      # 0xFFFFFFFF
        xor  s0, t2, t3      # 6
        ecall''')
    assert c.x[6] == 1
    assert c.x[29] == 0xFFFFFFFE
    assert c.x[30] == 5 and c.x[31] == MASK32 and c.x[8] == 6


@test
def shifts_signed():
    c = run_src('''
        li   t0, -8          # 0xFFFFFFF8
        srai t1, t0, 1       # 算术右移 → 0xFFFFFFFC
        srli t2, t0, 1       # 逻辑右移 → 0x7FFFFFFC
        slli t3, t0, 1       # → 0xFFFFFFF0
        li   t4, 1
        slli t5, t4, 31      # 0x80000000
        sra  t6, t5, t4      # 算术右移 1 → 0xC0000000
        ecall''')
    assert c.x[6] == 0xFFFFFFFC and c.x[7] == 0x7FFFFFFC
    assert c.x[28] == 0xFFFFFFF0 and c.x[30] == 0x80000000
    assert c.x[31] == 0xC0000000, hex(c.x[31])


@test
def compares():
    c = run_src('''
        li   t0, -1
        li   t1, 1
        slt  t2, t0, t1      # 有符号: -1 < 1 → 1
        sltu t3, t0, t1      # 无符号: 0xFFFFFFFF < 1 → 0
        slti t4, t1, 0       # 1 < 0 → 0
        sltiu t5, x0, -1     # 0 < 0xFFFFFFFF → 1
        ecall''')
    assert (c.x[7], c.x[28], c.x[29], c.x[30]) == (1, 0, 0, 1)


@test
def lui_auipc():
    c = run_src('lui t0, 0xDEADB\nauipc s0, 1\necall')
    assert c.x[5] == 0xDEADB000
    assert c.x[8] == RAM_BASE + 4 + 4096, hex(c.x[8])   # auipc 在第二条


@test
def memory_access():
    c = run_src('''
        la   t0, buf
        li   t1, 0xFFFF
        sb   t1, 0(t0)
        lb   t2, 0(t0)       # 符号扩展 → 0xFFFFFFFF
        lbu  t3, 0(t0)       # → 255
        li   t4, 0x11223344
        sw   t4, 4(t0)
        lb   t5, 4(t0)       # 小端最低字节 0x44
        lhu  t6, 6(t0)       # 高半字 0x1122
        lw   s1, 4(t0)
        sh   t1, 8(t0)
        lh   s2, 8(t0)       # 半字 0xFFFF → 符号扩展
        ecall
buf:    .space 16''')
    assert c.x[7] == MASK32 and c.x[28] == 255
    assert c.x[30] == 0x44 and c.x[31] == 0x1122
    assert c.x[9] == 0x11223344 and c.x[18] == MASK32


@test
def branch_family():
    tmpl = '''
        li   t0, {a}
        li   t1, {b}
        {op} t0, t1, yes
        li   a0, 0
        ecall
yes:    li   a0, 1
        ecall'''
    cases = [('beq', 3, 3, 1), ('beq', 3, 4, 0), ('bne', 3, 4, 1),
             ('blt', -1, 1, 1), ('blt', 1, -1, 0), ('bge', 1, -1, 1),
             ('bge', -1, -1, 1), ('bltu', -1, 1, 0), ('bltu', 1, -1, 1),
             ('bgeu', 1, -1, 0), ('bgeu', -1, -1, 1)]
    for op, a, b, want in cases:
        c = run_src(tmpl.format(op=op, a=a, b=b))
        assert c.exit_code == want, '%s %d, %d → 退出码 %d, 应为 %d' % (op, a, b, c.exit_code, want)


@test
def jumps_link():
    c = run_src('''
        jal  ra, over        # 链接寄存器 = 下一条指令地址
dead:   li   a0, 99
        ecall
over:   ecall''')
    assert c.exit_code == 0 and c.x[1] == RAM_BASE + 4
    c2 = run_src('''
        la   t0, dest        # la 展开成 2 条,占 0~7
        jalr ra, t0, 0
dead:   li   a0, 99
        ecall
dest:   ecall''')
    assert c2.exit_code == 0 and c2.x[1] == RAM_BASE + 12


@test
def mmio_uart_and_input():
    c = run_src('''
        li   t0, 0x10000000
        li   t1, 'H'
        sb   t1, 0(t0)
        ecall''')
    assert ''.join(c.uart_out) == 'H'
    c2 = RV32()
    c2.input.append('K')
    c2.load(assemble('''
        li   t0, 0x10000004
        lw   t1, 0(t0)       # 1 = 有输入可读
        li   t0, 0x10000008
        lw   t2, 0(t0)       # 弹出 'K'
        ecall'''))
    c2.run()
    assert c2.x[6] == 1 and c2.x[7] == 0x4B


@test
def loop_sum_1_to_10():
    c = run_src('''
        li   t0, 0
        li   t1, 1
        li   t2, 11          # 上界(不含)
loop:   add  t0, t0, t1
        addi t1, t1, 1
        blt  t1, t2, loop
        mv   a0, t0
        ecall''')
    assert c.exit_code == 55, c.exit_code


@test
def e2e_demo_programs():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for name, want in (('hello.asm', 'Hello, RISC-V!\n'), ('count.asm', '0123456789')):
        with open(os.path.join(root, 'programs', name), encoding='utf-8') as fh:
            src = fh.read()
        c = RV32()
        c.load(assemble(src))
        c.run()
        out = ''.join(c.uart_out)
        assert out == want and c.exit_code == 0, (repr(out), c.exit_code)


@test
def framebuffer_mmio():
    c = run_src('''
        li   t0, 0x10001000
        li   t1, 0x80
        sb   t1, 0(t0)        # 第 0 行第 0 像素
        li   t1, 0x01
        sb   t1, 7(t0)        # 第 0 行第 63 像素
        li   t1, 0xFF
        sb   t1, 8(t0)        # 第 1 行整行点亮
        lw   t2, 8(t0)        # 字读 FB
        ecall''')
    assert c.fb[0] == 0x80 and c.fb[7] == 0x01 and c.fb[8] == 0xFF
    assert c.x[7] == 0xFF
    lines = c.fb_ascii().splitlines()
    assert lines[0][0] == '#' and lines[0][63] == '#' and lines[0][1] == '.'
    assert lines[1][:8] == '########' and lines[1][8] == '.', lines[1]


@test
def csr_instructions():
    c = run_src('''
        csrrwi t0, 0x340, 20       # mscratch = 20,旧值 0 → t0
        csrrs  t1, 0x340, x0       # 读 → 20
        csrrsi t2, 0x340, 3        # 20|3=23,旧值 20 → t2
        csrrc  t3, 0x340, t1       # 23 & ~20 = 3,旧值 23 → t3
        ecall''')
    assert (c.x[5], c.x[6], c.x[7], c.x[28]) == (0, 20, 20, 23)
    assert c.csr[0x340] == 3, hex(c.csr[0x340])


@test
def timer_trap_rearm():
    c = run_src('''
        la   t0, handler
        csrw 0x305, t0             # mtvec
        li   t1, 0x80
        csrw 0x304, t1             # mie.MTIE
        li   t0, 0x0200BFF8        # mtime
        li   t2, 0x02004000        # mtimecmp
        lw   t3, 0(t0)
        addi t3, t3, 30
        sw   t3, 0(t2)             # lo:30 条指令后第一炮
        sw   x0, 4(t2)             # hi = 0,写满 64 位
        csrrsi t1, 0x300, 0x8      # 最后才开中断
        li   t6, 3                 # 目标:3 次中断
loop:   beq  t4, t6, done
        j    loop
done:   li   a0, 1
        ecall
handler:
        addi t4, t4, 1             # 计数(测试专用,不做现场保存)
        lw   t5, 0(t0)
        addi t5, t5, 30
        sw   t5, 0(t2)             # 重排定时器(hi 已是 0)
        mret''', max_steps=50000)
    assert c.exit_code == 1 and c.x[29] == 3, (c.exit_code, c.x[29])


@test
def illegal_trap_and_mret():
    c = run_src('''
        la   t0, handler
        csrw 0x305, t0
        .word 0xFFFFFFFF           # 非法指令 → trap
        li   a0, 1
        ecall
handler:
        li   a1, 7
        csrrs t0, 0x341, x0        # mepc = 非法指令地址
        addi t0, t0, 4
        csrw 0x341, t0             # 跳过它再 mret
        mret''')
    assert c.exit_code == 1 and c.x[11] == 7


@test
def m_extension():
    c = run_src('''
        li   t0, -7
        li   t1, 3
        mul  t2, t0, t1        # -21 → 0xFFFFFFEB
        mulh a2, t0, t1        # 高 32 位:-21 >> 32 = -1
        mulhu t3, t0, t1       # 无符号:0xFFFFFFF9*3 高 32 = 2
        div  t4, t0, t1        # -7/3 = -2(向零截断,不是 floor 的 -3)
        rem  t5, t0, t1        # -7%3 = -1
        li   t6, 0
        div  s0, t0, t6        # 除零 → -1
        rem  s1, t0, t6        # 除零 → rs1
        li   a3, 1
        li   a4, 2
        divu a5, a3, a4        # 1/2 = 0
        remu a6, a3, a4        # 1%2 = 1
        ecall''')
    assert c.x[7] == 0xFFFFFFEB and c.x[12] == 0xFFFFFFFF
    assert c.x[28] == 2 and c.x[29] == 0xFFFFFFFE
    assert c.x[30] == 0xFFFFFFFF and c.x[8] == 0xFFFFFFFF
    assert c.x[9] == 0xFFFFFFF9, hex(c.x[9])
    assert c.x[15] == 0 and c.x[16] == 1


@test
def wfi_sleeps_until_alarm():
    c = run_src('''
        la   t0, handler
        csrw 0x305, t0             # mtvec
        li   t1, 0x80
        csrw 0x304, t1             # mie.MTIE
        li   t0, 0x0200BFF8        # mtime
        li   t2, 0x02004000        # mtimecmp
        lw   t3, 0(t0)
        addi t3, t3, 30
        sw   t3, 0(t2)             # lo
        sw   x0, 4(t2)             # hi
        csrrsi t1, 0x300, 0x8      # 开中断
        li   t6, 3
loop:   beq  t4, t6, done
        wfi                        # 不忙等:快进到闹钟
        j    loop
done:   li   a0, 1
        ecall
handler:
        addi t4, t4, 1
        lw   t5, 0(t0)
        addi t5, t5, 30
        sw   t5, 0(t2)
        mret''', max_steps=50000)
    assert c.exit_code == 1 and c.x[29] == 3, (c.exit_code, c.x[29])
    assert c.cycles < 60, 'wfi 没有快进: %d 步' % c.cycles   # 忙等版要 ~130 步


@test
def user_mode_ecall_is_syscall_trap():
    """mret 降入 U 模式后,ecall 应变成 mcause=8 的 trap(不再是停机)。"""
    src = '''
        la   t0, handler
        csrw 0x305, t0             # mtvec
        li   t0, 0x80              # MPIE=1, MPP=U(00)
        csrw 0x300, t0
        la   t0, ustart
        csrw 0x341, t0
        mret                       # 降级到 U 模式
ustart:
        li   a7, 5
        li   a0, 123
        ecall                      # U:trap mcause=8
        li   a1, 99                # handler 推进 mepc 后到这里
        ecall                      # 第二次
spin:   j    spin
handler:
        csrrs t2, 0x342, x0        # mcause
        la   t3, 0x80100000
        lw   t5, 0(t3)
        addi t5, t5, 1
        sw   t5, 0(t3)             # 计数
        sw   t2, 4(t3)             # 记录最近的 mcause
        csrrs t4, 0x341, x0        # mepc:跳过 ecall
        addi t4, t4, 4
        csrw 0x341, t4
        mret                       # 回 U 模式
'''
    c = RV32()
    c.load(assemble(src))
    try:
        c.run(20000)
        raise AssertionError('spin 循环应该跑满 max_steps')
    except RuntimeError as e:
        assert 'max_steps' in str(e)
    base = 0x80100000 - RAM_BASE
    count = int.from_bytes(c.mem[base:base + 4], 'little')
    last = int.from_bytes(c.mem[base + 4:base + 8], 'little')
    assert count == 2 and last == 8, (count, last)
    assert c.x[11] == 99 and c.x[10] == 123        # mepc 推进正确、a0 未被破坏
    assert c.mode == 0, c.mode                     # 始终在 U 模式


@test
def user_mode_csr_and_wfi_are_illegal():
    """U 模式碰 CSR / wfi → trap mcause=2,handler 跳过后继续。"""
    src = '''
        la   t0, handler
        csrw 0x305, t0
        li   t0, 0x80
        csrw 0x300, t0
        la   t0, ustart
        csrw 0x341, t0
        mret
ustart:
        csrrs t0, 0x340, x0        # CSR → 非法(2)
        wfi                        # wfi → 非法(2)
        ecall                      # → 系统调用(8)
        li   a1, 7
spin:   j    spin
handler:
        csrrs t2, 0x342, x0
        la   t3, 0x80100010
        lw   t5, 0(t3)
        addi t5, t5, 1
        sw   t5, 0(t3)
        slli t6, t5, 2
        add  t6, t3, t6            # 别忘了加基址
        sw   t2, 0(t6)             # slot[t5] = mcause
        csrrs t4, 0x341, x0
        addi t4, t4, 4
        csrw 0x341, t4
        mret
'''
    c = RV32()
    c.load(assemble(src))
    try:
        c.run(20000)
        raise AssertionError('spin 循环应该跑满 max_steps')
    except RuntimeError as e:
        assert 'max_steps' in str(e)
    base = 0x80100010 - RAM_BASE
    count = int.from_bytes(c.mem[base:base + 4], 'little')
    causes = [int.from_bytes(c.mem[base + 4 + i * 4:base + 8 + i * 4], 'little')
              for i in range(count)]
    assert causes == [2, 2, 8], causes             # CSR 非法、wfi 非法、ecall 系统调用
    assert c.x[11] == 7 and c.mode == 0


def main():
    failed = 0
    for fn in TESTS:
        try:
            fn()
            print('PASS', fn.__name__)
        except AssertionError as e:
            failed += 1
            print('FAIL', fn.__name__, '->', e)
    print('---')
    print('%d/%d 组测试通过' % (len(TESTS) - failed, len(TESTS)))
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
