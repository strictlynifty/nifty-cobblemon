#!/usr/bin/env python3
"""Send many console commands over ONE RCON connection.

usage: rconbatch.py <file-of-commands> [--dry]
"""
import socket, struct, sys, os

COBBLEMON_DIR = os.environ.get("COBBLEMON_DIR", "/srv/cobblemon")

HOST, PORT = '127.0.0.1', 25575
BASE = COBBLEMON_DIR


def pkt(rid, typ, body):
    data = struct.pack('<ii', rid, typ) + body.encode('utf8') + b'\x00\x00'
    return struct.pack('<i', len(data)) + data


def recv(s):
    ln = struct.unpack('<i', s.recv(4))[0]
    buf = b''
    while len(buf) < ln:
        c = s.recv(ln - len(buf))
        if not c:
            break
        buf += c
    rid, typ = struct.unpack('<ii', buf[:8])
    return rid, typ, buf[8:-2].decode('utf8', 'replace')


cmds = [l.strip() for l in open(sys.argv[1]) if l.strip()]
if '--dry' in sys.argv:
    print('%d commands, first 3:' % len(cmds))
    for c in cmds[:3]:
        print('  ' + c)
    sys.exit(0)

pw = open(os.path.join(BASE, '.rconpw')).read().strip()
ok = fail = 0
bad = []
with socket.create_connection((HOST, PORT), timeout=30) as s:
    s.sendall(pkt(1, 3, pw))
    rid, _, _ = recv(s)
    if rid == -1:
        print('RCON auth failed'); sys.exit(1)
    for i, c in enumerate(cmds):
        s.sendall(pkt(2, 2, c))
        _, _, body = recv(s)
        b = body.strip()
        if 'No blocks' in b or 'Changed' in b or b == '':
            ok += 1
        else:
            fail += 1
            if len(bad) < 12:
                bad.append((c, b))
print('sent %d  ok %d  unexpected %d' % (len(cmds), ok, fail))
for c, b in bad:
    print('   %s\n     -> %s' % (c, b))
