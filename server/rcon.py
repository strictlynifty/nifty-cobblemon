#!/usr/bin/env python3
"""Send a console command to the Cobblemon server over loopback RCON."""
import socket, struct, sys, os

HOST, PORT = "127.0.0.1", 25575
BASE = os.path.dirname(os.path.abspath(__file__))

def pkt(rid, typ, body):
    data = struct.pack("<ii", rid, typ) + body.encode("utf8") + b"\x00\x00"
    return struct.pack("<i", len(data)) + data

def recv(s):
    ln = struct.unpack("<i", s.recv(4))[0]
    buf = b""
    while len(buf) < ln:
        chunk = s.recv(ln - len(buf))
        if not chunk:
            break
        buf += chunk
    rid, typ = struct.unpack("<ii", buf[:8])
    return rid, typ, buf[8:-2].decode("utf8", "replace")

def main():
    if len(sys.argv) < 2:
        print("usage: rcon.py <command...>", file=sys.stderr); return 2
    pw = open(os.path.join(BASE, ".rconpw")).read().strip()
    cmd = " ".join(sys.argv[1:])
    with socket.create_connection((HOST, PORT), timeout=15) as s:
        s.sendall(pkt(1, 3, pw))            # SERVERDATA_AUTH
        rid, _, _ = recv(s)
        if rid == -1:
            print("RCON auth failed", file=sys.stderr); return 1
        s.sendall(pkt(2, 2, cmd))           # SERVERDATA_EXECCOMMAND
        _, _, body = recv(s)
        print(body.strip())
    return 0

if __name__ == "__main__":
    sys.exit(main())
