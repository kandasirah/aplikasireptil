"""Cari port TCP bebas mulai dari angka yang diberikan (dipakai postinst REPTIL).

Dipisah ke berkas tersendiri agar isi postinst tetap POSIX shell murni.
Dijalankan oleh venv python: /opt/reptil/venv/bin/python <berkas ini> 8010
"""

import socket
import sys


def port_bebas(mulai: int, maks: int = 100) -> int | None:
    for port in range(mulai, mulai + maks):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            sock.close()
            continue
        sock.close()
        return port
    return None


def main() -> int:
    mulai = int(sys.argv[1]) if len(sys.argv) > 1 else 8010
    port = port_bebas(mulai)
    if port is None:
        return 1
    print(port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
