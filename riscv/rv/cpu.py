"""RV32I CPU 核心:32 个通用寄存器、小端内存、MMIO UART/输入。

硬件约定(刻意与 QEMU virt 板对齐,方便将来接真工具链):
- RAM 从 0x80000000 开始,程序入口 = RAM_BASE
- 0x10000000 + 0:写一个字节 → UART 输出(收集在 uart_out)
- 0x10000000 + 4:读 → 1=有输入可读,0=无
- 0x10000000 + 8:读 → 弹出一个输入字符,空则 0xFFFFFFFF
- ecall / ebreak → 停机,退出码取 a0(x10)

decode() 是指令字段的唯一真相:step() 与单元测试共用它,
保证"汇编器编码 ↔ CPU 译码"不会各说各话。
"""
from collections import deque

MASK32 = 0xFFFFFFFF
RAM_BASE = 0x80000000
UART_BASE = 0x10000000
FB_BASE = 0x10001000                       # framebuffer:64x32 位图
FB_SIZE = 256                              # 每行 8 字节 × 32 行,MSB = 行内最左像素


def sext(v, bits):
    """低 bits 位的有符号数 → Python 整数(符号扩展)。"""
    sign = 1 << (bits - 1)
    return (v & (sign - 1)) - (v & sign)


class IllegalInstruction(RuntimeError):
    """非法指令:设了 mtvec 就进 trap(mcause=2),没设就原样抛出。"""


def decode(inst):
    """按 R/I/S/B/U/J 六种格式取出字段和立即数。"""
    f = dict(opcode=inst & 0x7F, rd=(inst >> 7) & 0x1F, f3=(inst >> 12) & 0x7,
             rs1=(inst >> 15) & 0x1F, rs2=(inst >> 20) & 0x1F, f7=(inst >> 25) & 0x7F)
    op = f['opcode']
    if op in (0x03, 0x13, 0x67):                        # I 型
        f['imm'] = sext(inst >> 20, 12)
    elif op == 0x23:                                    # S 型
        f['imm'] = sext(((inst >> 25) << 5) | ((inst >> 7) & 0x1F), 12)
    elif op == 0x63:                                    # B 型
        f['imm'] = sext((((inst >> 31) & 1) << 12) | (((inst >> 7) & 1) << 11)
                        | (((inst >> 25) & 0x3F) << 5) | (((inst >> 8) & 0xF) << 1), 13)
    elif op == 0x6F:                                    # J 型
        f['imm'] = sext((((inst >> 31) & 1) << 20) | (((inst >> 12) & 0xFF) << 12)
                        | (((inst >> 20) & 1) << 11) | (((inst >> 21) & 0x3FF) << 1), 21)
    elif op in (0x37, 0x17):                            # U 型
        f['imm'] = inst & 0xFFFFF000
    return f


class RV32:
    def __init__(self, ram_size=1 << 22):
        self.x = [0] * 32
        self.pc = RAM_BASE
        self.mem = bytearray(ram_size)
        self.fb = bytearray(FB_SIZE)
        self.uart_out = []
        self.input = deque()
        self.halted = False
        self.exit_code = 0
        self.cycles = 0
        # CLINT:mtime 每条指令 +1(可重现的"周期计数");mtimecmp 复位值 0
        # (与 SiFive CLINT 一致):MTIP 复位即挂起,靠 mstatus.MIE 屏蔽,
        # 软件须在开中断前把 mtimecmp 写到未来(先 lo 后 hi 写满 64 位)
        self.mtime = 0
        self.mtimecmp = 0
        self.csr = {}                              # mstatus/mie/mtvec/mepc/mcause/mscratch
        self.mode = 3                              # 3 = M(内核), 0 = U(用户任务)

    def load(self, program, addr=RAM_BASE):
        off = addr - RAM_BASE
        self.mem[off:off + len(program)] = program
        self.pc = addr

    def run(self, max_steps=1_000_000):
        while not self.halted and self.cycles < max_steps:
            self.step()
        if not self.halted:
            raise RuntimeError('超过 max_steps=%d,可能在死循环' % max_steps)
        return self

    # ---------- 内存 / MMIO ----------
    def read(self, addr, size):
        addr &= MASK32
        if RAM_BASE <= addr < RAM_BASE + len(self.mem):
            off = addr - RAM_BASE
            if off + size > len(self.mem):
                raise RuntimeError('读越界: 0x%08X' % addr)
            return int.from_bytes(self.mem[off:off + size], 'little')
        if FB_BASE <= addr < FB_BASE + FB_SIZE:
            off = addr - FB_BASE
            val = 0
            for k in range(size):
                if off + k < FB_SIZE:
                    val |= self.fb[off + k] << (8 * k)
            return val
        if addr == 0x0200BFF8:                         # CLINT mtime 低 32 位
            return self.mtime & MASK32
        if addr == 0x0200BFFC:
            return (self.mtime >> 32) & MASK32
        if addr == UART_BASE + 4:
            return 1 if self.input else 0
        if addr == UART_BASE + 8:
            return ord(self.input.popleft()) & 0xFF if self.input else MASK32
        return 0                                        # 未映射读为 0

    def write(self, addr, val, size):
        addr &= MASK32
        if RAM_BASE <= addr < RAM_BASE + len(self.mem):
            off = addr - RAM_BASE
            if off + size > len(self.mem):
                raise RuntimeError('写越界: 0x%08X' % addr)
            self.mem[off:off + size] = (val & ((1 << (8 * size)) - 1)).to_bytes(size, 'little')
        elif FB_BASE <= addr < FB_BASE + FB_SIZE:
            off = addr - FB_BASE
            for k in range(size):
                if off + k < FB_SIZE:
                    self.fb[off + k] = (val >> (8 * k)) & 0xFF
        elif 0x02004000 <= addr < 0x02004008:          # CLINT mtimecmp(64 位域)
            off = addr - 0x02004000
            for k in range(size):
                sh = 8 * (off + k)
                self.mtimecmp = (self.mtimecmp & ~(0xFF << sh)) \
                    | (((val >> (8 * k)) & 0xFF) << sh)
        elif addr == UART_BASE:
            self.uart_out.append(chr(val & 0xFF))
        # 其余未映射写:忽略

    def _csr_read(self, num):
        if num == 0x344:                               # mip:MTIP 动态计算
            return 0x80 if self.mtime >= self.mtimecmp else 0
        if num == 0x301:                               # misa:RV32I
            return (1 << 31) | (1 << 8)
        return self.csr.get(num, 0)

    def _csr_write(self, num, val):
        if num in (0x344, 0x301):                      # 只读
            return
        self.csr[num] = val & MASK32

    def _trap_now(self, cause, target):
        """进入 machine trap:mepc←当前 PC,MPIE←MIE、MIE←0,MPP←当前模式,PC←target。"""
        self.csr[0x341] = self.pc & MASK32               # mepc
        self.csr[0x342] = cause & MASK32                 # mcause
        ms = self.csr.get(0x300, 0)                      # mstatus
        self.csr[0x300] = (ms & ~0x188) | ((ms & 0x8) << 4) | ((self.mode & 3) << 11)
        self.mode = 3                                    # 进内核
        self.pc = target & ~3 & MASK32

    def fb_ascii(self):
        """64x32 framebuffer → 32 行 #/. 文本,无头快照用。"""
        lines = []
        for r in range(32):
            row = self.fb[r * 8:(r + 1) * 8]
            lines.append(''.join('#' if row[x >> 3] & (0x80 >> (x & 7)) else '.'
                                 for x in range(64)))
        return '\n'.join(lines)

    # ---------- 执行 ----------
    def _wreg(self, rd, val):
        if rd:                                          # x0 恒为 0
            self.x[rd] = val & MASK32

    @staticmethod
    def _div(v1, v2):
        """有符号除法,向零截断;除零 → -1,MIN/-1 溢出 → MIN(RISC-V 规定)。"""
        if v2 == 0:
            return 0xFFFFFFFF
        a, b = sext(v1, 32), sext(v2, 32)
        if a == -0x80000000 and b == -1:
            return 0x80000000
        q = abs(a) // abs(b)
        if (a < 0) != (b < 0):
            q = -q
        return q

    @staticmethod
    def _rem(v1, v2):
        """有符号取余;除零 → rs1,MIN/-1 溢出 → 0。"""
        if v2 == 0:
            return v1
        a, b = sext(v1, 32), sext(v2, 32)
        if a == -0x80000000 and b == -1:
            return 0
        r = abs(a) % abs(b)
        return -r if a < 0 else r

    def step(self):
        if self.halted:
            raise RuntimeError('CPU 已停机')
        if (self.mtime >= self.mtimecmp
                and self.csr.get(0x300, 0) & 0x8              # mstatus.MIE
                and self.csr.get(0x304, 0) & 0x80             # mie.MTIE
                and self.csr.get(0x305, 0)):                  # mtvec
            self._trap_now((1 << 31) | 7, self.csr[0x305])    # machine 定时中断
            return
        if not RAM_BASE <= self.pc < RAM_BASE + len(self.mem) - 3:
            raise RuntimeError('PC 越界: 0x%08X' % self.pc)
        off = self.pc - RAM_BASE
        inst = int.from_bytes(self.mem[off:off + 4], 'little')
        f = decode(inst)
        opcode, rd, f3, f7 = f['opcode'], f['rd'], f['f3'], f['f7']
        rs1, rs2 = f['rs1'], f['rs2']
        imm = f.get('imm', 0)
        x = self.x
        v1, v2 = x[rs1], x[rs2]
        next_pc = (self.pc + 4) & MASK32
        self.cycles += 1

        if opcode == 0x37:                              # LUI
            self._wreg(rd, imm)
        elif opcode == 0x17:                            # AUIPC
            self._wreg(rd, self.pc + imm)
        elif opcode == 0x6F:                            # JAL
            self._wreg(rd, next_pc)
            next_pc = (self.pc + imm) & MASK32
        elif opcode == 0x67:                            # JALR
            t = next_pc
            next_pc = (v1 + imm) & MASK32 & ~1
            self._wreg(rd, t)
        elif opcode == 0x63:                            # 分支
            if f3 == 0: taken = v1 == v2                # beq
            elif f3 == 1: taken = v1 != v2              # bne
            elif f3 == 4: taken = sext(v1, 32) < sext(v2, 32)     # blt
            elif f3 == 5: taken = sext(v1, 32) >= sext(v2, 32)    # bge
            elif f3 == 6: taken = v1 < v2               # bltu
            elif f3 == 7: taken = v1 >= v2              # bgeu
            else:
                raise RuntimeError('非法分支 funct3=%d' % f3)
            if taken:
                next_pc = (self.pc + imm) & MASK32
        elif opcode == 0x03:                            # 载入
            addr = (v1 + imm) & MASK32
            if f3 == 0: val = sext(self.read(addr, 1), 8)          # lb
            elif f3 == 1: val = sext(self.read(addr, 2), 16)       # lh
            elif f3 == 2: val = self.read(addr, 4)                 # lw
            elif f3 == 4: val = self.read(addr, 1)                 # lbu
            elif f3 == 5: val = self.read(addr, 2)                 # lhu
            else:
                raise RuntimeError('非法 load funct3=%d' % f3)
            self._wreg(rd, val)
        elif opcode == 0x23:                            # 存储
            if f3 > 2:
                raise RuntimeError('非法 store funct3=%d' % f3)
            self.write((v1 + imm) & MASK32, v2, (1, 2, 4)[f3])
        elif opcode == 0x13:                            # 立即数 ALU
            if f3 == 0: val = v1 + imm                  # addi
            elif f3 == 2: val = 1 if sext(v1, 32) < imm else 0      # slti
            elif f3 == 3: val = 1 if v1 < (imm & MASK32) else 0     # sltiu
            elif f3 == 4: val = v1 ^ (imm & MASK32)     # xori
            elif f3 == 6: val = v1 | (imm & MASK32)     # ori
            elif f3 == 7: val = v1 & (imm & MASK32)     # andi
            elif f3 == 1:                               # slli(shamt 在 rs2 字段)
                if f7:
                    raise RuntimeError('非法 slli funct7=%d' % f7)
                val = v1 << rs2
            else:                                       # srli / srai
                if f7 == 0:
                    val = v1 >> rs2
                elif f7 == 0x20:
                    val = sext(v1, 32) >> rs2
                else:
                    raise RuntimeError('非法移位 funct7=%d' % f7)
            self._wreg(rd, val)
        elif opcode == 0x33:                            # 寄存器 ALU(+M 扩展)
            sh = v2 & 31
            if f7 == 0x01:                              # M 扩展:乘除
                if f3 == 0: val = v1 * v2               # mul(取低 32 位)
                elif f3 == 1: val = (sext(v1, 32) * sext(v2, 32)) >> 32   # mulh
                elif f3 == 2: val = (sext(v1, 32) * v2) >> 32             # mulhsu
                elif f3 == 3: val = (v1 * v2) >> 32     # mulhu
                elif f3 == 4: val = self._div(v1, v2)   # div
                elif f3 == 5: val = 0xFFFFFFFF if v2 == 0 else v1 // v2   # divu
                elif f3 == 6: val = self._rem(v1, v2)   # rem
                else: val = v1 % v2 if v2 else v1       # remu
            elif f7 in (0, 0x20):
                if f3 == 0: val = (v1 - v2) if f7 == 0x20 else (v1 + v2)
                elif f3 == 1: val = v1 << sh            # sll
                elif f3 == 2: val = 1 if sext(v1, 32) < sext(v2, 32) else 0   # slt
                elif f3 == 3: val = 1 if v1 < v2 else 0 # sltu
                elif f3 == 4: val = v1 ^ v2
                elif f3 == 5: val = (sext(v1, 32) >> sh) if f7 == 0x20 else (v1 >> sh)
                elif f3 == 6: val = v1 | v2
                else: val = v1 & v2
            else:
                raise IllegalInstruction('非法 ALU funct7=%d' % f7)
            self._wreg(rd, val)
        elif opcode == 0x0F:                            # fence:单核即 no-op
            pass
        elif opcode == 0x73:                            # SYSTEM:ecall/ebreak/mret/CSR
            if f3 == 0:
                if inst == 0x30200073:                  # mret:回 MPP 指定的模式
                    if self.mode == 0:
                        mtv = self.csr.get(0x305, 0)
                        if not mtv:
                            raise IllegalInstruction('U 模式 mret')
                        self._trap_now(2, mtv)
                        return
                    ms = self.csr.get(0x300, 0)
                    self.mode = (ms >> 11) & 3          # mode ← MPP
                    self.csr[0x300] = (ms & ~0x188) | ((ms & 0x80) >> 4) | 0x80
                    next_pc = self.csr.get(0x341, 0) & ~3 & MASK32
                elif inst == 0x10500073:                # wfi:确定性休眠(U 非法)
                    if self.mode == 0:
                        mtv = self.csr.get(0x305, 0)
                        if not mtv:
                            raise IllegalInstruction('U 模式 wfi')
                        self._trap_now(2, mtv)
                        return
                    if self.mtimecmp > self.mtime:      # 快进到下一个闹钟,
                        self.mtime = self.mtimecmp      # 下一步的中断检查自然触发
                elif inst == 0x00000073:                # ecall
                    if self.mode == 0:                  # U:系统调用 → 内核 trap
                        mtv = self.csr.get(0x305, 0)
                        if not mtv:
                            raise IllegalInstruction('U 模式 ecall 无 mtvec')
                        self._trap_now(8, mtv)
                        return
                    self.halted = True                  # M:独立程序停机(保留)
                    self.exit_code = x[10]              # a0
                elif inst == 0x00100073:                # ebreak
                    if self.mode == 0:
                        mtv = self.csr.get(0x305, 0)
                        if not mtv:
                            raise IllegalInstruction('U 模式 ebreak')
                        self._trap_now(3, mtv)
                        return
                    self.halted = True
                    self.exit_code = x[10]
                else:
                    raise IllegalInstruction('未知 SYSTEM 指令 0x%08X' % inst)
            else:
                if self.mode == 0:                      # U 模式不许碰任何 CSR
                    mtv = self.csr.get(0x305, 0)
                    if not mtv:
                        raise IllegalInstruction('U 模式 CSR')
                    self._trap_now(2, mtv)
                    return
                csr_num = (inst >> 20) & 0xFFF
                old = self._csr_read(csr_num)
                if f3 == 1: new = v1                    # csrrw
                elif f3 == 2: new = old | v1            # csrrs
                elif f3 == 3: new = old & ~v1           # csrrc
                elif f3 == 5: new = rs1                 # csrrwi(zimm 在 rs1 字段)
                elif f3 == 6: new = old | rs1           # csrrsi
                else: new = old & ~rs1                  # csrrci
                self._csr_write(csr_num, new)
                self._wreg(rd, old)
        else:
            mtv = self.csr.get(0x305, 0)
            if not mtv:
                raise IllegalInstruction('未知指令 0x%08X @ 0x%08X' % (inst, self.pc))
            self._trap_now(2, mtv)                 # mcause=2,pc ← mtvec
            return

        if next_pc & 3:
            raise RuntimeError('PC 未 4 字节对齐: 0x%08X' % next_pc)
        self.pc = next_pc
        self.mtime += 1                                 # 1 指令 = 1 mtime tick
