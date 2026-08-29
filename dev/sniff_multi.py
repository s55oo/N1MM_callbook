"""Listen on several ports for BOTH UDP datagrams and TCP connections,
dump everything received verbatim.

  python sniff_multi.py [port ...]      (default: 6767 12060)

Log is written into ./vhfctest4win-captures/ next to this script.
"""
import datetime
import os
import socket
import sys
import threading

PORTS = [int(a) for a in sys.argv[1:]] or [6767, 12060]

HERE = os.path.dirname(os.path.abspath(__file__))
CAPDIR = os.path.join(HERE, "vhfctest4win-captures")
os.makedirs(CAPDIR, exist_ok=True)
LOG = os.path.join(CAPDIR, "sniff_multi_{:%Y%m%d_%H%M%S}.log".format(datetime.datetime.now()))
log = open(LOG, "a", encoding="utf-8")
lock = threading.Lock()
n = [0]


def emit(s):
    with lock:
        print(s, flush=True)
        log.write(s + "\n")
        log.flush()


def show(proto, port, addr, data):
    n[0] += 1
    ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
    emit("--- #{} {} {} :{}  from {}:{}  {} bytes ---".format(
        n[0], ts, proto, port, addr[0], addr[1], len(data)))
    try:
        emit(data.decode("utf-8"))
    except UnicodeDecodeError:
        emit(repr(data))
    emit("")


def udp_server(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    except OSError:
        pass
    try:
        s.bind(("", port))
    except OSError as e:
        emit("# UDP :{} bind failed: {}".format(port, e))
        return
    emit("# UDP listening on :{}".format(port))
    while True:
        data, addr = s.recvfrom(65535)
        show("UDP", port, addr, data)


def tcp_server(port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("", port))
        s.listen(5)
    except OSError as e:
        emit("# TCP :{} bind failed: {}".format(port, e))
        return
    emit("# TCP listening on :{}".format(port))
    while True:
        conn, addr = s.accept()
        emit("# TCP :{} connection from {}:{}".format(port, *addr))
        threading.Thread(target=tcp_client, args=(port, conn, addr), daemon=True).start()


def tcp_client(port, conn, addr):
    conn.settimeout(600)
    try:
        while True:
            data = conn.recv(65535)
            if not data:
                break
            show("TCP", port, addr, data)
    except OSError:
        pass
    finally:
        conn.close()


emit("# {}  ports {}  ->  {}".format(datetime.datetime.now(), PORTS, LOG))
for p in PORTS:
    threading.Thread(target=udp_server, args=(p,), daemon=True).start()
    threading.Thread(target=tcp_server, args=(p,), daemon=True).start()
try:
    threading.Event().wait()
except KeyboardInterrupt:
    emit("# stopped, {} message(s)".format(n[0]))
