# -*- coding: utf-8 -*-
"""Disassemble a method's bytecode with constants resolved inline.

    python3 disasm.py <jar> <class/Path.class> [methodNameSubstring]

cpstr.py shows strings and constvals.py shows `static final` values, but neither
shows a number that is pushed inline (bipush/sipush/ldc) or compared against.
That is where spawn radii, distance checks and chances actually live.
"""
import struct, zipfile, sys

jar, cls = sys.argv[1], sys.argv[2]
args = [a for a in sys.argv[3:] if a != '-a']
SHOWALL = '-a' in sys.argv
want = args[0] if args else None
raw = zipfile.ZipFile(jar).read(cls)

cnt = struct.unpack_from('>H', raw, 8)[0]
p = 10
pool = {}
i = 1
while i < cnt:
    tag = raw[p]; p += 1
    if tag == 1:
        l = struct.unpack_from('>H', raw, p)[0]; p += 2
        pool[i] = ('utf8', raw[p:p + l].decode('utf8', 'replace')); p += l
    elif tag in (7, 8, 16, 19, 20):
        pool[i] = ({7: 'class', 8: 'string'}.get(tag, 'ref'),
                   struct.unpack_from('>H', raw, p)[0]); p += 2
    elif tag in (9, 10, 11, 12):
        pool[i] = ('pair', struct.unpack_from('>HH', raw, p)); p += 4
    elif tag == 3:
        pool[i] = ('int', struct.unpack_from('>i', raw, p)[0]); p += 4
    elif tag == 4:
        pool[i] = ('float', struct.unpack_from('>f', raw, p)[0]); p += 4
    elif tag == 5:
        pool[i] = ('long', struct.unpack_from('>q', raw, p)[0]); p += 8; i += 1
    elif tag == 6:
        pool[i] = ('double', struct.unpack_from('>d', raw, p)[0]); p += 8; i += 1
    elif tag == 15:
        pool[i] = ('mh', 0); p += 3
    elif tag == 17:
        pool[i] = ('dyn', struct.unpack_from('>HH', raw, p)); p += 4
    elif tag == 18:
        pool[i] = ('indy', struct.unpack_from('>HH', raw, p)); p += 4
    else:
        raise ValueError('cp tag %d at %d' % (tag, p))
    i += 1


def u(idx):
    t, v = pool.get(idx, ('?', '?'))
    return v if t == 'utf8' else '?'


def const(idx):
    t, v = pool.get(idx, ('?', '?'))
    if t in ('int', 'float', 'long', 'double'):
        return '%s %s' % (t, v)
    if t == 'string':
        return '"%s"' % u(v)
    if t == 'class':
        return u(v)
    if t == 'pair':
        c, nt = v
        cn = u(pool[c][1]).split('/')[-1]
        n, d = pool[nt][1]
        return '%s.%s %s' % (cn, u(n), u(d))
    return str(v)


# ---- opcode table: name -> operand byte count (negative = special)
OPS = {}
for o, n, a in [
    (0x00, 'nop', 0), (0x01, 'aconst_null', 0), (0x10, 'bipush', 1), (0x11, 'sipush', 2),
    (0x12, 'ldc', 1), (0x13, 'ldc_w', 2), (0x14, 'ldc2_w', 2),
    (0x84, 'iinc', 2), (0xb2, 'getstatic', 2), (0xb3, 'putstatic', 2),
    (0xb4, 'getfield', 2), (0xb5, 'putfield', 2), (0xb6, 'invokevirtual', 2),
    (0xb7, 'invokespecial', 2), (0xb8, 'invokestatic', 2), (0xb9, 'invokeinterface', 4),
    (0xba, 'invokedynamic', 4), (0xbb, 'new', 2), (0xbc, 'newarray', 1),
    (0xbd, 'anewarray', 2), (0xc0, 'checkcast', 2), (0xc1, 'instanceof', 2),
    (0xc5, 'multianewarray', 3), (0xc6, 'ifnull', 2), (0xc7, 'ifnonnull', 2),
]:
    OPS[o] = (n, a)
for o, n in [(0x99, 'ifeq'), (0x9a, 'ifne'), (0x9b, 'iflt'), (0x9c, 'ifge'),
             (0x9d, 'ifgt'), (0x9e, 'ifle'), (0x9f, 'if_icmpeq'), (0xa0, 'if_icmpne'),
             (0xa1, 'if_icmplt'), (0xa2, 'if_icmpge'), (0xa3, 'if_icmpgt'),
             (0xa4, 'if_icmple'), (0xa5, 'if_acmpeq'), (0xa6, 'if_acmpne'),
             (0xa7, 'goto')]:
    OPS[o] = (n, 2)
SIMPLE = {0x02: 'iconst_m1', 0x03: 'iconst_0', 0x04: 'iconst_1', 0x05: 'iconst_2',
          0x06: 'iconst_3', 0x07: 'iconst_4', 0x08: 'iconst_5', 0x09: 'lconst_0',
          0x0a: 'lconst_1', 0x0b: 'fconst_0', 0x0c: 'fconst_1', 0x0d: 'fconst_2',
          0x0e: 'dconst_0', 0x0f: 'dconst_1', 0x57: 'pop', 0x58: 'pop2', 0x59: 'dup',
          0x60: 'iadd', 0x64: 'isub', 0x68: 'imul', 0x6c: 'idiv', 0x70: 'irem',
          0x63: 'dadd', 0x67: 'dsub', 0x6b: 'dmul', 0x6f: 'ddiv',
          0x62: 'fadd', 0x66: 'fsub', 0x6a: 'fmul', 0x6e: 'fdiv',
          0x91: 'i2b', 0x92: 'i2c', 0x93: 'i2s', 0x86: 'i2f', 0x87: 'i2d',
          0x8b: 'f2i', 0x8e: 'd2i', 0x8d: 'd2l', 0x8f: 'd2f', 0x8a: 'l2d',
          0x94: 'lcmp', 0x95: 'fcmpl', 0x96: 'fcmpg', 0x97: 'dcmpl', 0x98: 'dcmpg',
          0xac: 'ireturn', 0xad: 'lreturn', 0xae: 'freturn', 0xaf: 'dreturn',
          0xb0: 'areturn', 0xb1: 'return', 0xbe: 'arraylength', 0xbf: 'athrow'}


def disasm(code):
    out, i = [], 0
    while i < len(code):
        pc, op = i, code[i]
        i += 1
        if op in SIMPLE:
            out.append((pc, SIMPLE[op], ''))
            continue
        if 0x15 <= op <= 0x2d or 0x36 <= op <= 0x4e:
            if op in (0x15, 0x16, 0x17, 0x18, 0x19, 0x36, 0x37, 0x38, 0x39, 0x3a):
                out.append((pc, 'load/store', str(code[i]))); i += 1
            else:
                out.append((pc, 'load/store', ''));
            continue
        if 0x2e <= op <= 0x35 or 0x4f <= op <= 0x56:
            out.append((pc, 'array', '')); continue
        if op == 0xaa or op == 0xab:
            i += (4 - (i % 4)) % 4
            if op == 0xab:
                d, n = struct.unpack_from('>ii', code, i); i += 8 + 8 * n
            else:
                d, lo, hi = struct.unpack_from('>iii', code, i); i += 12 + 4 * (hi - lo + 1)
            out.append((pc, 'switch', '')); continue
        name, alen = OPS.get(op, ('op_%02x' % op, 0))
        arg = code[i:i + alen]; i += alen
        txt = ''
        if name in ('bipush',):
            txt = str(struct.unpack_from('>b', arg, 0)[0])
        elif name == 'sipush':
            txt = str(struct.unpack_from('>h', arg, 0)[0])
        elif name == 'ldc':
            txt = const(arg[0])
        elif name in ('ldc_w', 'ldc2_w'):
            txt = const(struct.unpack_from('>H', arg, 0)[0])
        elif alen >= 2 and name not in ('iinc',):
            idx = struct.unpack_from('>H', arg, 0)[0]
            txt = const(idx) if name not in ('ifeq', 'ifne', 'iflt', 'ifge', 'ifgt',
                                             'ifle', 'goto', 'ifnull', 'ifnonnull') \
                and not name.startswith('if_') else '-> %d' % (pc + struct.unpack_from('>h', arg, 0)[0])
        out.append((pc, name, txt))
    return out


mcount_off = 10
p2 = p
ifc = struct.unpack_from('>H', raw, p2 + 6)[0]
p2 += 8 + 2 * ifc
for _ in range(2):                      # fields, then methods
    n = struct.unpack_from('>H', raw, p2)[0]; p2 += 2
    members = []
    for _ in range(n):
        acc, ni, di, ac = struct.unpack_from('>HHHH', raw, p2); p2 += 8
        attrs = {}
        for _ in range(ac):
            ani, alen = struct.unpack_from('>HI', raw, p2); p2 += 6
            attrs[u(ani)] = raw[p2:p2 + alen]; p2 += alen
        members.append((u(ni), u(di), attrs))
    last = members
for name, desc, attrs in last:
    if want and want.lower() not in name.lower():
        continue
    code = attrs.get('Code')
    if not code:
        continue
    clen = struct.unpack_from('>I', code, 4)[0]
    body = code[8:8 + clen]
    print('\n=== %s %s ===' % (name, desc))
    for pc, op, txt in disasm(body):
        if not SHOWALL and op in ('load/store', 'array', 'nop', 'dup', 'pop'):
            continue
        print('  %4d  %-16s %s' % (pc, op, txt))
