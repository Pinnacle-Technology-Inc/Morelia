"""
Simple UDP listener for localhost:9000 to display data from UDPSink.

Matches the binary format used by UDPSink:
  - 8206HR: 20 bytes = 8-byte timestamp (ns) + 3 floats (ch0, ch1, ch2)
  - 8401HR: 24 bytes = 8-byte timestamp (ns) + 4 floats (ch0, ch1, ch2, ch3)

Usage:
  python udp_listener.py [--host HOST] [--port PORT]
  (default: 0.0.0.0:9000 to accept on all interfaces; use 127.0.0.1 to bind localhost only)
"""

import argparse
import signal
import socket
import struct
import sys

_shutdown = False


def _on_sigint(*_):
    global _shutdown
    _shutdown = True


def main():
    parser = argparse.ArgumentParser(description="UDP listener for Morelia UDPSink stream")
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Bind address (default: 0.0.0.0; use 127.0.0.1 for localhost only)",
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=9000,
        help="Bind port (default: 9000)",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _on_sigint)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _on_sigint)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.settimeout(0.5)
    try:
        sock.bind((args.host, args.port))
    except OSError as e:
        print(f"Bind failed: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Listening on {args.host}:{args.port}. Format: timestamp_ns ch0 ch1 ch2 [ch3]. Ctrl+C to stop.")
    print("-" * 60)
    count = 0
    try:
        while not _shutdown:
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                continue
            if _shutdown:
                break
            n = len(data)
            if n == 20:
                ts, ch0, ch1, ch2 = struct.unpack("<Qfff", data)
                print(f"  {count:6d}  ts={ts:>15d}  ch0={ch0:10.2f}  ch1={ch1:10.2f}  ch2={ch2:10.2f}  (8206)")
            elif n == 24:
                ts, ch0, ch1, ch2, ch3 = struct.unpack("<Qffff", data)
                print(f"  {count:6d}  ts={ts:>15d}  ch0={ch0:8.2f}  ch1={ch1:8.2f}  ch2={ch2:8.2f}  ch3={ch3:8.2f}  (8401)")
            else:
                print(f"  {count:6d}  len={n}  from {addr}  (raw)")
            count += 1
    except KeyboardInterrupt:
        pass
    finally:
        sock.close()
    print("-" * 60)
    print(f"Received {count} datagrams.")


if __name__ == "__main__":
    main()
