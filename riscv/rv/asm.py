"""RV32I 汇编器:两遍扫描、标签、伪指令、数据段。

- 助记符与操作数顺序跟 GNU as 一致(将来接真工具链无缝切换)
- 寄存器:x0~x31 或 ABI 名(zero/ra/sp/t0~t6/s0~s11/a0~a7/fp)
- 伪指令:li/la(恒展开 lui+addi,尺寸可预测)、mv、not、neg、nop、
  j、call、ret(jal/jalr 的单操作数形式)
- 数据:  .origin、.string/.asciz、.byte、.word、.space
- 注释:  # 开头;立即数支持 0x 十六进制、负数、字符 'A'

用法:python3 -m rv.asm program.asm -o program.bin
"""
import re
import struct

from .cpu import MASK32, RAM_BASE

REGS = {}
for _k in range(32):
    REGS['x%d' % _k] = _k
for _k, _n in enumerate(['zero', 'ra', 'sp', 'gp', 'tp', 't0', 't1', 't2',
                         's0', 's1', 'a0', 'a1', 'a2', 'a3', 'a4', 'a5',
                         'a6', 'a7', 's2', 's3', 's4', 's5', 's6', 's7',
                         's8', 's9', 's10', 's11', 't3', 't4', 't5', 't6']):
    REGS[_n] = _k
REGS['fp'] = 8

ESCAPES = {'n': '\n', 't': '\t', '0': '\0', '\\': '\\', '"': '"', "'": "'"}

BRANCH3 = {'beq': 0, 'bne': 1, 'blt': 4, 'bge': 5, 'bltu': 6, 'bgeu': 7}
LOADS = {'lb': 0, 'lh': 1, 'lw': 2, 'lbu': 4, 'lhu': 5}
STORES = {'sb': 0, 'sh': 1, 'sw': 2}
IMM_ALU = {'addi': 0, 'slti': 2, 'sltiu': 3, 'xori': 4, 'ori': 6, 'andi': 7}
OP_IMM_SHIFTS = {'slli': (1, 0x00), 'srli': (5, 0x00), 'srai': (5, 0x20)}
REG_ALU = {'add': (0, 0x00), 'sub': (0, 0x20), 'sll': (1, 0x00), 'slt': (2, 0x00),
           'sltu': (3, 0x00), 'xor': (4, 0x00), 'srl': (5, 0x00), 'sra': (5, 0x20),
           'or': (6, 0x00), 'and': (7, 0x00)}
CSR_OPS = {'csrrw': 1, 'csrrs': 2, 'csrrc': 3,
           'csrrwi': 5, 'csrrsi': 6, 'csrrci': 7}
M_ALU = {'mul': 0, 'mulh': 1, 'mulhsu': 2, 'mulhu': 3,
         'div': 4, 'divu': 5, 'rem': 6, 'remu': 7}


def parse_int(tok):
    tok = tok.strip()
    if len(tok) >= 3 and tok[0] == "'" and tok[-1] == "'":
        body = tok[1:-1]
        if body[0] == '\\' and len(body) >= 2:
            body = ESCAPES.get(body[1], body[1])
        return ord(body)
    return int(tok, 0)


def reg(tok):
    tok = tok.strip().lower()
    if tok not in REGS:
        raise SyntaxError('未知寄存器: %r' % tok)
    return REGS[tok]


def imm_val(tok, labels):
    """立即数:数字 / 字符 / 标签 / %hi(expr) / %lo(expr)。"""
    tok = tok.strip()
    m = re.fullmatch(r'%(hi|lo)\((.+)\)', tok)
    if m:
        inner = m.group(2).strip()
        if inner in labels:
            base = labels[inner]
        else:
            base = parse_int(inner)
        hi = (base + 0x800) >> 12
        return hi if m.group(1) == 'hi' else base - (hi << 12)
    if tok in labels:
        return labels[tok]
    return parse_int(tok)


# ---------- 六种格式的编码器 ----------
def enc_r(f7, rs2, rs1, f3, rd, op):
    return (f7 << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | op


def enc_i(imm, rs1, f3, rd, op):
    return ((imm & 0xFFF) << 20) | (rs1 << 15) | (f3 << 12) | (rd << 7) | op


def enc_s(imm, rs2, rs1, f3, op):
    imm &= 0xFFF
    return ((imm >> 5) << 25) | (rs2 << 20) | (rs1 << 15) | (f3 << 12) \
        | ((imm & 0x1F) << 7) | op


def enc_b(imm, rs2, rs1, f3):
    imm &= 0x1FFF
    return (((imm >> 12) & 1) << 31) | (((imm >> 5) & 0x3F) << 25) | (rs2 << 20) \
        | (rs1 << 15) | (f3 << 12) | (((imm >> 1) & 0xF) << 8) \
        | (((imm >> 11) & 1) << 7) | 0x63


def enc_u(imm, rd, op):
    return ((imm & 0xFFFFF) << 12) | (rd << 7) | op


def enc_j(imm, rd):
    imm &= 0x1FFFFF
    return (((imm >> 20) & 1) << 31) | (((imm >> 1) & 0x3FF) << 21) \
        | (((imm >> 11) & 1) << 20) | (((imm >> 12) & 0xFF) << 12) | (rd << 7) | 0x6F


def expand_pseudo(mnem, args, lineno):
    """伪指令 → 原始指令行列表;不是伪指令返回 None。"""
    def need(n):
        if len(args) != n:
            raise SyntaxError('第 %d 行: %s 需要 %d 个操作数' % (lineno, mnem, n))

    if mnem in ('li', 'la'):          # 恒展开为 lui+addi,保证两遍扫描尺寸可预测
        need(2)
        return ['lui %s, %%hi(%s)' % (args[0], args[1]),
                'addi %s, %s, %%lo(%s)' % (args[0], args[0], args[1])]
    if mnem == 'mv':
        need(2)
        return ['addi %s, %s, 0' % (args[0], args[1])]
    if mnem == 'nop':
        return ['addi x0, x0, 0']
    if mnem == 'not':
        need(2)
        return ['xori %s, %s, -1' % (args[0], args[1])]
    if mnem == 'neg':
        need(2)
        return ['sub %s, x0, %s' % (args[0], args[1])]
    if mnem == 'j':
        need(1)
        return ['jal x0, %s' % args[0]]
    if mnem == 'call':
        need(1)
        return ['jal ra, %s' % args[0]]
    if mnem == 'ret':
        return ['jalr x0, ra, 0']
    if mnem == 'jal' and len(args) == 1:
        return ['jal ra, %s' % args[0]]
    if mnem == 'jalr' and len(args) == 1:
        return ['jalr ra, %s, 0' % args[0]]
    if mnem == 'csrr':
        need(2)
        return ['csrrs %s, %s, x0' % (args[0], args[1])]
    if mnem == 'csrw':
        need(2)
        return ['csrrw x0, %s, %s' % (args[0], args[1])]
    return None


def parse_string(argstr, lineno):
    argstr = argstr.strip()
    if len(argstr) < 2 or argstr[0] != '"' or argstr[-1] != '"':
        raise SyntaxError('第 %d 行: .string 需要 "..." 包起来' % lineno)
    body = argstr[1:-1]
    out, i = bytearray(), 0
    while i < len(body):
        c = body[i]
        if c == '\\' and i + 1 < len(body):
            out += ESCAPES.get(body[i + 1], body[i + 1]).encode('utf-8')
            i += 2
        else:
            out += c.encode('utf-8')
            i += 1
    return bytes(out) + b'\0'          # 补 \0,等同 .asciz


def parse_items(src):
    """→ (items, labels);item = (kind, payload, lineno),标签指向条目序号。"""
    items, labels = [], {}
    for lineno, raw in enumerate(src.splitlines(), 1):
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        while True:                    # 一行可以带多个标签
            m = re.match(r'^([A-Za-z_.$][\w.$]*):\s*', line)
            if not m:
                break
            labels[m.group(1)] = len(items)
            line = line[m.end():]
        if not line:
            continue
        parts = line.split(None, 1)
        mnem = parts[0].lower()
        argstr = parts[1].strip() if len(parts) > 1 else ''
        if mnem in ('.origin', '.org'):
            if items:
                raise SyntaxError('第 %d 行: .origin 只能出现在最前面' % lineno)
            items.append(('origin', parse_int(argstr), lineno))
            continue
        if mnem in ('.string', '.asciz'):
            items.append(('string', parse_string(argstr, lineno), lineno))
            continue
        args = [a.strip() for a in argstr.split(',')] if argstr else []
        if mnem == '.byte':
            items.append(('byte', [parse_int(a) & 0xFF for a in args], lineno))
        elif mnem == '.word':
            items.append(('word', [parse_int(a) for a in args], lineno))
        elif mnem == '.space':
            items.append(('space', parse_int(args[0]), lineno))
        else:
            expanded = expand_pseudo(mnem, args, lineno)
            if expanded is not None:
                for e in expanded:
                    items.append(('ins', e, lineno))
            else:
                items.append(('ins', line, lineno))
    return items, labels


def encode_ins(text, labels, addr):
    m = re.match(r'^(\S+)\s*(.*)$', text.strip())
    mnem = m.group(1).lower()
    args = [a.strip() for a in m.group(2).split(',')] if m.group(2) else []

    def need(n):
        if len(args) != n:
            raise SyntaxError('%r 需要 %d 个操作数,得到 %d' % (text, n, len(args)))

    def target(tok):
        """分支/跳转:标签 → 相对偏移;裸数字 → 当作绝对地址。"""
        return imm_val(tok, labels) - addr

    def mem_operand(tok):
        mm = re.fullmatch(r'(.*?)\((\w+)\)', tok.strip())
        if not mm:
            raise SyntaxError('内存操作数应为 off(reg): %r' % tok)
        off = imm_val(mm.group(1), labels) if mm.group(1).strip() else 0
        return off, reg(mm.group(2))

    if mnem in ('lui', 'auipc'):
        need(2)
        return enc_u(imm_val(args[1], labels), reg(args[0]),
                     0x37 if mnem == 'lui' else 0x17)
    if mnem == 'jal':
        need(2)
        return enc_j(target(args[1]), reg(args[0]))
    if mnem == 'jalr':
        if len(args) == 2:             # jalr rd, off(rs1)
            off, base = mem_operand(args[1])
            return enc_i(off, base, 0, reg(args[0]), 0x67)
        need(3)                        # jalr rd, rs1, imm
        return enc_i(imm_val(args[2], labels), reg(args[1]), 0, reg(args[0]), 0x67)
    if mnem in BRANCH3:
        need(3)
        return enc_b(target(args[2]), reg(args[1]), reg(args[0]), BRANCH3[mnem])
    if mnem in LOADS:
        need(2)
        off, base = mem_operand(args[1])
        return enc_i(off, base, LOADS[mnem], reg(args[0]), 0x03)
    if mnem in STORES:
        need(2)
        off, base = mem_operand(args[1])
        return enc_s(off, reg(args[0]), base, STORES[mnem], 0x23)
    if mnem in IMM_ALU:
        need(3)
        return enc_i(imm_val(args[2], labels), reg(args[1]), IMM_ALU[mnem],
                     reg(args[0]), 0x13)
    if mnem in OP_IMM_SHIFTS:
        need(3)
        f3, f7 = OP_IMM_SHIFTS[mnem]
        return enc_i((f7 << 5) | (imm_val(args[2], labels) & 0x1F),
                     reg(args[1]), f3, reg(args[0]), 0x13)
    if mnem in REG_ALU:
        need(3)
        f3, f7 = REG_ALU[mnem]
        return enc_r(f7, reg(args[2]), reg(args[1]), f3, reg(args[0]), 0x33)
    if mnem in M_ALU:                                # M 扩展:乘除
        need(3)
        return enc_r(0x01, reg(args[2]), reg(args[1]), M_ALU[mnem],
                     reg(args[0]), 0x33)
    if mnem in CSR_OPS:                              # Zicsr 一族
        need(3)
        f3 = CSR_OPS[mnem]
        csr = imm_val(args[1], labels) & 0xFFF
        if f3 >= 5:                                  # 立即数形式:zimm 在 rs1 字段
            return enc_i(csr, imm_val(args[2], labels) & 0x1F, f3, reg(args[0]), 0x73)
        return enc_i(csr, reg(args[2]), f3, reg(args[0]), 0x73)
    if mnem == 'mret':
        return 0x30200073
    if mnem == 'wfi':
        return 0x10500073
    if mnem == 'fence':
        return 0x0000000F
    if mnem == 'ecall':
        return 0x00000073
    if mnem == 'ebreak':
        return 0x00100073
    raise SyntaxError('不认识的指令: %r' % text)


def _size_of(kind, payload):
    if kind == 'ins':
        return 4
    if kind == 'word':
        return 4 * len(payload)
    if kind in ('byte', 'string'):
        return len(payload)
    if kind == 'space':
        return payload
    return 0                           # origin


def assemble(src, origin=RAM_BASE):
    items, labels = parse_items(src)
    if items and items[0][0] == 'origin':
        origin = items[0][1]
        items = items[1:]
    sizes = [_size_of(k, v) for k, v, _ in items]
    addrs, a = [], origin
    for s in sizes:
        addrs.append(a)
        a += s
    label_addr = {name: (addrs[i] if i < len(addrs) else a)
                  for name, i in labels.items()}
    out = bytearray()
    for (kind, payload, _ln), size, addr in zip(items, sizes, addrs):
        if kind == 'ins':
            out += struct.pack('<I', encode_ins(payload, label_addr, addr))
        elif kind == 'word':
            for w in payload:
                out += struct.pack('<I', w & MASK32)
        elif kind == 'byte':
            out += bytes(payload)
        elif kind == 'string':
            out += payload
        elif kind == 'space':
            out += bytes(size)
    return bytes(out)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description='RV32I 汇编器')
    ap.add_argument('src')
    ap.add_argument('-o', '--out', required=True)
    a = ap.parse_args(argv)
    with open(a.src, encoding='utf-8') as fh:
        code = assemble(fh.read())
    with open(a.out, 'wb') as fh:
        fh.write(code)
    print('写出 %s(%d 字节,入口 0x%08X)' % (a.out, len(code), RAM_BASE))


if __name__ == '__main__':
    main()
