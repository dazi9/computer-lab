"""极简 CHIP-8 汇编器(两遍扫描,支持标签 / DB 数据 / 注释)。

RISC-V 阶段"自己写汇编器"的前菜,语法刻意保持同款风格:
    loop:   LD  I, ball
            DRW V0, V1, 6
            SE  V5, 0
            JP  wait
    ball:   DB  0x3C, 0x7E
"""
import re


def vreg(tok):
    m = re.fullmatch(r'[Vv]([0-9A-Fa-f])', tok)
    if not m:
        raise SyntaxError('应为寄存器 V0~VF: %r' % tok)
    return int(m.group(1), 16)


def _imm(tok, labels, bits, name):
    v = labels[tok] if tok in labels else int(tok, 0)
    if not 0 <= v < (1 << bits):
        raise SyntaxError('%s 越界: %r' % (name, tok))
    return v


def parse_items(src):
    """切成 ('ins', 文本) / ('db', [字节]) 条目;标签指向下一条目的序号。"""
    items, labels = [], {}
    for raw in src.splitlines():
        line = raw.split(';', 1)[0].strip()
        while True:
            m = re.match(r'^(\w+):\s*', line)
            if not m:
                break
            labels[m.group(1)] = len(items)
            line = line[m.end():]
        if not line:
            continue
        toks = line.split()
        if toks[0].upper() == 'DB':
            items.append(('db', [int(x.rstrip(','), 0) for x in toks[1:]]))
        else:
            items.append(('ins', line))
    return items, labels


def encode_ins(line, labels):
    t = line.replace(',', ' ').split()
    op = t[0].upper()

    def two(hi, lo):
        return bytes([hi, lo])

    i12 = lambda tok: _imm(tok, labels, 12, '12 位立即数')
    i8 = lambda tok: _imm(tok, labels, 8, '8 位立即数')

    if op == 'JP':
        n = i12(t[1])
        return two(0x10 | n >> 8, n & 0xFF)
    if op == 'CALL':
        n = i12(t[1])
        return two(0x20 | n >> 8, n & 0xFF)
    if op in ('SE', 'SNE'):
        x = vreg(t[1])
        if t[2].upper().startswith('V'):
            y = vreg(t[2])
            return two((0x50 if op == 'SE' else 0x90) | x, y << 4)
        return two((0x30 if op == 'SE' else 0x40) | x, i8(t[2]))
    if op == 'LD':
        d, s = t[1], t[2]
        if d.upper() == 'I':
            n = i12(s)
            return two(0xA0 | n >> 8, n & 0xFF)
        if s.upper() == 'DT':                    # LD Vx, DT
            return two(0xF0 | vreg(d), 0x07)
        if d.upper() == 'DT':                    # LD DT, Vx
            return two(0xF0 | vreg(s), 0x15)
        if not s.upper().startswith('V'):        # LD Vx, nn
            return two(0x60 | vreg(d), i8(s))
        return two(0x80 | vreg(d), vreg(s) << 4)  # LD Vx, Vy
    if op == 'ADD':
        d, s = t[1], t[2]
        if s.upper().startswith('V'):
            return two(0x80 | vreg(d), vreg(s) << 4 | 0x4)
        return two(0x70 | vreg(d), i8(s))
    if op == 'DRW':
        return two(0xD0 | vreg(t[1]), vreg(t[2]) << 4 | int(t[3], 0))
    if op == 'SKP':                              # 按键按下则跳过
        return two(0xE0 | vreg(t[1]), 0x9E)
    if op == 'SKNP':                             # 没按下则跳过
        return two(0xE0 | vreg(t[1]), 0xA1)
    raise SyntaxError('不认识的指令: ' + line)


def assemble(src, origin=0x200):
    items, labels = parse_items(src)
    sizes = [len(val) if kind == 'db' else 2 for kind, val in items]
    addrs, a = [], origin
    for s in sizes:
        addrs.append(a)
        a += s
    label_addr = {name: addrs[idx] for name, idx in labels.items()}
    out = bytearray()
    for (kind, val) in items:
        if kind == 'db':
            out += bytes(val)
        else:
            out += encode_ins(val, label_addr)
    return bytes(out)


# 内置示例:弹跳小球 —— 演示绘图、XOR 擦除、分支、定时器
BOUNCE_SRC = """
; 弹跳小球:开机即玩的 demo
        LD  V0, 8       ; x
        LD  V1, 4       ; y
        LD  V2, 1       ; dx = +1
        LD  V3, 1       ; dy = +1
loop:   LD  I, ball
        DRW V0, V1, 6   ; 画球
        LD  V4, 4
        LD  DT, V4      ; 定时器 = 4 tick(约 66ms)
wait:   LD  V5, DT
        SE  V5, 0       ; 倒计时到 0 了吗
        JP  wait
        DRW V0, V1, 6   ; XOR 擦除旧球
        SE  V0, 0       ; 撞左墙 → dx = +1
        JP  chk_r
        LD  V2, 1
chk_r:  SE  V0, 56      ; 撞右墙 → dx = -1
        JP  chk_t
        LD  V2, 255
chk_t:  SE  V1, 0       ; 撞上墙 → dy = +1
        JP  chk_b
        LD  V3, 1
chk_b:  SE  V1, 26      ; 撞下墙 → dy = -1
        JP  move
        LD  V3, 255
move:   ADD V0, V2
        ADD V1, V3
        JP  loop
ball:   DB  0x3C, 0x7E, 0xFF, 0xFF, 0x7E, 0x3C
"""

# 键盘交互 demo:挡板 —— 终端键 '1' 左移、'4' 右移(SKP 指令的用武之地)
PADDLE_SRC = """
; 挡板:按 CHIP-8 键 1(终端 '1')左移,键 C(终端 '4')右移
        LD  V1, 30      ; 挡板 y 固定在底行
        LD  V0, 30      ; x 初始居中
loop:   LD  I, pad
        DRW V0, V1, 1   ; 画挡板
        LD  V4, 3
        LD  DT, V4      ; 每帧约 50ms
wait:   LD  V5, DT
        SE  V5, 0
        JP  wait
        LD  I, pad
        DRW V0, V1, 1   ; XOR 擦除
        LD  V2, 1       ; CHIP-8 键 1
        SKP V2
        JP  chk_r
        SE  V0, 0       ; 撞左墙就不动
        ADD V0, 255     ; x -= 1
chk_r:  LD  V2, 12      ; CHIP-8 键 C
        SKP V2
        JP  move
        SE  V0, 60      ; 撞右墙就不动
        ADD V0, 1
move:   JP  loop
pad:    DB  0xF0        ; 一行四像素
"""
