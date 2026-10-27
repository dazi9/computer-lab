"""CHIP-8 虚拟机核心。

1977 年的 CHIP-8 本质上是一台虚拟机:4KB 内存、16 个 8 位寄存器、
35 条指令、64x32 单色屏幕、两个 60Hz 倒计时器。这里是完整的
取指-译码-执行核心,渲染与输入在 emu.py 中,与核心解耦。
"""
import random

W, H = 64, 32

# 0~F 的字模,每字符 5 字节,按约定加载到 0x050
FONT = bytes([
    0xF0, 0x90, 0x90, 0x90, 0xF0,  # 0
    0x20, 0x60, 0x20, 0x20, 0x70,  # 1
    0xF0, 0x10, 0xF0, 0x80, 0xF0,  # 2
    0xF0, 0x10, 0xF0, 0x10, 0xF0,  # 3
    0x90, 0x90, 0xF0, 0x10, 0x10,  # 4
    0xF0, 0x80, 0xF0, 0x10, 0xF0,  # 5
    0xF0, 0x80, 0xF0, 0x90, 0xF0,  # 6
    0xF0, 0x10, 0x20, 0x40, 0x40,  # 7
    0xF0, 0x90, 0xF0, 0x90, 0xF0,  # 8
    0xF0, 0x90, 0xF0, 0x10, 0xF0,  # 9
    0xF0, 0x90, 0xF0, 0x90, 0x90,  # A
    0xE0, 0x90, 0xE0, 0x90, 0xE0,  # B
    0xF0, 0x80, 0x80, 0x80, 0xF0,  # C
    0xE0, 0x90, 0x90, 0x90, 0xE0,  # D
    0xF0, 0x80, 0xF0, 0x80, 0xF0,  # E
    0xF0, 0x80, 0xF0, 0x80, 0x80,  # F
])


class Chip8:
    def __init__(self, shift_legacy=False, mem_legacy=False):
        self.mem = bytearray(4096)
        self.mem[0x050:0x0A0] = FONT
        self.v = [0] * 16          # V0~VF,VF 兼作进位/碰撞标志
        self.i = 0                 # 12 位地址寄存器
        self.pc = 0x200            # 程序从 0x200 开始
        self.stack = []
        self.dt = 0                # 60Hz 延时定时器
        self.st = 0                # 60Hz 声音定时器
        self.display = bytearray(W * H)   # 行优先位图,1 = 亮
        self.keys = [False] * 16   # 16 键小键盘状态
        self.cycles = 0
        # 兼容开关:老机型移位指令取 Vy 作源、FX55/65 执行后 I 不自增
        self.shift_legacy = shift_legacy
        self.mem_legacy = mem_legacy

    def load(self, rom, addr=0x200):
        self.mem[addr:addr + len(rom)] = rom
        self.pc = addr

    def tick(self):
        """定时器按 60Hz 递减,主循环每帧调一次。"""
        if self.dt:
            self.dt -= 1
        if self.st:
            self.st -= 1

    def step(self):
        """执行一条指令,返回 opcode 便于调试。"""
        op = (self.mem[self.pc] << 8) | self.mem[self.pc + 1]
        self.pc = (self.pc + 2) & 0xFFF
        self.cycles += 1
        self._exec(op)
        return op

    def _exec(self, op):
        x = (op >> 8) & 0xF                     # 寄存器下标(X)
        y = (op >> 4) & 0xF
        n = op & 0xF
        nn = op & 0xFF
        nnn = op & 0xFFF
        hi = op >> 12                           # 指令族(最高 4 位)
        v = self.v

        if hi == 0x0:
            if op == 0x00E0:                    # CLS
                self.display[:] = bytearray(W * H)
            elif op == 0x00EE:                  # RET
                self.pc = self.stack.pop()
            # 其余 0NNN:调用机器码,忽略
        elif hi == 0x1:                         # JP nnn
            self.pc = nnn
        elif hi == 0x2:                         # CALL nnn
            self.stack.append(self.pc)
            self.pc = nnn
        elif hi == 0x3:                         # SE Vx, nn
            if v[x] == nn:
                self.pc = (self.pc + 2) & 0xFFF
        elif hi == 0x4:                         # SNE Vx, nn
            if v[x] != nn:
                self.pc = (self.pc + 2) & 0xFFF
        elif hi == 0x5 and n == 0:              # SE Vx, Vy
            if v[x] == v[y]:
                self.pc = (self.pc + 2) & 0xFFF
        elif hi == 0x6:                         # LD Vx, nn
            v[x] = nn
        elif hi == 0x7:                         # ADD Vx, nn(无进位)
            v[x] = (v[x] + nn) & 0xFF
        elif hi == 0x8:                         # ALU 一族
            self._alu(x, y, n)
        elif hi == 0x9 and n == 0:              # SNE Vx, Vy
            if v[x] != v[y]:
                self.pc = (self.pc + 2) & 0xFFF
        elif hi == 0xA:                         # LD I, nnn
            self.i = nnn
        elif hi == 0xB:                         # JP V0 + nnn
            self.pc = (nnn + v[0]) & 0xFFF
        elif hi == 0xC:                         # RND Vx, nn
            v[x] = random.getrandbits(8) & nn
        elif hi == 0xD:                         # DRW Vx, Vy, n
            self._draw(x, y, n)
        elif hi == 0xE:
            if nn == 0x9E:                      # 有键按下则跳过
                if self.keys[v[x] & 0xF]:
                    self.pc = (self.pc + 2) & 0xFFF
            elif nn == 0xA1:                    # 无键按下则跳过
                if not self.keys[v[x] & 0xF]:
                    self.pc = (self.pc + 2) & 0xFFF
            else:
                raise RuntimeError('未知指令 0x%04X' % op)
        elif hi == 0xF:
            self._fx(x, nn)
        else:
            raise RuntimeError('未知指令 0x%04X @ 0x%03X' % (op, self.pc - 2))

    def _alu(self, x, y, n):
        v = self.v
        if n == 0:                             # LD Vx, Vy
            v[x] = v[y]
        elif n == 1:
            v[x] |= v[y]
        elif n == 2:
            v[x] &= v[y]
        elif n == 3:
            v[x] ^= v[y]
        elif n == 4:                           # ADD,VF = 进位
            s = v[x] + v[y]
            v[x] = s & 0xFF
            v[0xF] = s > 0xFF
        elif n == 5:                           # SUB Vx-Vy,VF = 无借位
            d = v[x] - v[y]
            v[x] = d & 0xFF
            v[0xF] = d >= 0
        elif n == 6:                           # SHR,VF = 移出位
            src = v[y] if self.shift_legacy else v[x]
            v[x] = src >> 1
            v[0xF] = src & 1
        elif n == 7:                           # SUBN Vy-Vx
            d = v[y] - v[x]
            v[x] = d & 0xFF
            v[0xF] = d >= 0
        elif n == 0xE:                         # SHL
            src = v[y] if self.shift_legacy else v[x]
            v[x] = (src << 1) & 0xFF
            v[0xF] = src >> 7
        else:
            raise RuntimeError('未知 ALU 指令 0x8%X%X%X' % (x, y, n))

    def _draw(self, x, y, n):
        """异或绘制 8xN 精灵,坐标逐像素回绕,VF = 碰撞。"""
        vx = self.v[x] % W
        vy = self.v[y] % H
        collision = 0
        for row in range(n):
            bits = self.mem[(self.i + row) & 0xFFF]
            yy = (vy + row) % H
            for col in range(8):
                if bits & (0x80 >> col):
                    xx = (vx + col) % W
                    idx = yy * W + xx
                    if self.display[idx]:
                        collision = 1
                    self.display[idx] ^= 1
        self.v[0xF] = collision

    def _fx(self, x, nn):
        v = self.v
        if nn == 0x07:                         # LD Vx, DT
            v[x] = self.dt
        elif nn == 0x0A:                       # LD Vx, K:等一个按键
            down = [k for k, d in enumerate(self.keys) if d]
            if not down:
                self.pc = (self.pc - 2) & 0xFFF   # 没按键就原地重跑这条
            else:
                v[x] = down[0]
        elif nn == 0x15:                       # LD DT, Vx
            self.dt = v[x]
        elif nn == 0x18:                       # LD ST, Vx
            self.st = v[x]
        elif nn == 0x1E:                       # ADD I, Vx
            self.i = (self.i + v[x]) & 0xFFF
        elif nn == 0x29:                       # LD F, Vx:指向 Vx 的字模
            self.i = 0x050 + (v[x] & 0xF) * 5
        elif nn == 0x33:                       # BCD:百十个位
            self.mem[self.i] = v[x] // 100
            self.mem[self.i + 1] = v[x] // 10 % 10
            self.mem[self.i + 2] = v[x] % 10
        elif nn == 0x55:                       # 存 V0~Vx 到内存
            for k in range(x + 1):
                self.mem[self.i + k] = v[k]
            if not self.mem_legacy:
                self.i = (self.i + x + 1) & 0xFFF
        elif nn == 0x65:                       # 从内存读 V0~Vx
            for k in range(x + 1):
                v[k] = self.mem[self.i + k]
            if not self.mem_legacy:
                self.i = (self.i + x + 1) & 0xFFF
        else:
            raise RuntimeError('未知 FX 指令 0x%04X' % (0xF000 | x << 8 | nn))
