"""
Simple UDP listener for localhost:9000 to display data from UDPSink.

Matches the binary format used by UDPSink:
  - 8206HR: 20 bytes = 8-byte timestamp (ns) + 3 floats (ch0, ch1, ch2)
  - 8401HR: 24 bytes = 8-byte timestamp (ns) + 4 floats (ch0, ch1, ch2, ch3)
  - 8274D : 490 bytes = 8-byte timestamp + 16-bit count + batch of 40 (ch5, ch6, ch7)

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
        default="0.0.0.0", #TODO set address back to 0.0.0.0
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

    sock.bind((args.host, args.port))

    print(f"Listening on {args.host}:{args.port}")
    print("-" * 60)

    count = 0

    try:
        while not _shutdown:
            try:
                data, addr = sock.recvfrom(4096)  # bigger buffer for batches
            except socket.timeout:
                continue

            if _shutdown:
                break

            n = len(data)

            # Pod8206HR (3-channel)
            if n == 20:
                ts, ch0, ch1, ch2 = struct.unpack("<Qfff", data)
                print(f"{count:6d}  ts={ts} ch0={ch0:.2f} ch1={ch1:.2f} ch2={ch2:.2f} (8206)")

            # Pod8401HR (4-channel)
            elif n == 24:
                ts, ch0, ch1, ch2, ch3 = struct.unpack("<Qffff", data)
                print(f"{count:6d}  ts={ts} ch0={ch0:.2f} ch1={ch1:.2f} ch2={ch2:.2f} ch3={ch3:.2f} (8401)")

            # Pod8274D (batch 40 samples)
            elif n == 490:
                # header = 8-byte timestamp + 2-byte sample count
                ts, n_samples = struct.unpack("<QH", data[:10])

                offset = 10

                print(f"{count:6d}  ts={ts} samples={n_samples} (8274)")

                for i in range(n_samples):
                    ch5, ch6, ch7 = struct.unpack("<fff", data[offset:offset + 12])
                    offset += 12

                    print(f"        [{i:02d}] ch5={ch5:.2f} ch6={ch6:.2f} ch7={ch7:.2f}")

            count += 1

    finally:
        sock.close()
        print("-" * 60)
        print(f"Received {count} datagrams.")


if __name__ == "__main__":
    main()