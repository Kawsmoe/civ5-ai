"""Probe the Civ V FireTuner protocol on localhost:4318.

Connects, dumps everything the game sends, then asks for the list of Lua
states. Read-only: it never runs Lua in the game.

Close FireTuner first (the game may only allow one tuner connection).
"""
import socket
import struct
import sys
import time

HOST, PORT = "127.0.0.1", 4318


def hexdump(data):
    for i in range(0, len(data), 16):
        chunk = data[i:i + 16]
        hexpart = " ".join(f"{b:02x}" for b in chunk)
        text = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print(f"  {i:04x}  {hexpart:<48}  {text}")


def drain(sock, seconds):
    """Print everything received for `seconds`."""
    sock.settimeout(0.25)
    end = time.time() + seconds
    got = b""
    while time.time() < end:
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            continue
        if not chunk:
            print("  [game closed the connection]")
            break
        got += chunk
    if got:
        print(f"  received {len(got)} bytes:")
        hexdump(got)
    else:
        print("  (nothing received)")
    return got


def send_framed(sock, text, tag=3):
    """Best-guess framing: uint32 length, uint32 tag, null-terminated text."""
    payload = text.encode("ascii") + b"\0"
    frame = struct.pack("<II", len(payload), tag) + payload
    print(f"> sending {text!r} (tag={tag}):")
    hexdump(frame)
    sock.sendall(frame)


def main():
    print(f"Connecting to {HOST}:{PORT} ...")
    try:
        sock = socket.create_connection((HOST, PORT), timeout=5)
    except OSError as e:
        print(f"Could not connect: {e}")
        print("Is Civ V running with EnableTuner = 1, and is FireTuner closed?")
        sys.exit(1)
    print("Connected.\n")

    print("1) Listening for anything the game sends on connect:")
    drain(sock, 2)

    print("\n2) Asking for the Lua state list:")
    send_framed(sock, "LSQ:")
    drain(sock, 3)

    sock.close()
    print("\nDone. Paste everything above back to Claude.")


if __name__ == "__main__":
    main()
