# SPDX-License-Identifier: Unlicense
"""Two-PC diagnostic for LAN cache sharing (UDP 6768).

Callbooker's LAN sharing is plain UDP broadcast on 6768. If the footer on
the second PC never shows "- LAN 6768" / "- cache", this tells you
whether the datagrams are crossing the network at all (i.e. is it the
Windows Firewall / the network, or Callbooker).

    On PC-B:   python dev/lan_probe.py listen
    On PC-A:   python dev/lan_probe.py send

PC-B should print a line roughly every 2 seconds. If it does, the wire is
fine and the problem is in Callbooker (tell me). If it does NOT:

  * Windows Firewall on PC-B is blocking inbound UDP 6768 - allow
    "Callbooker" (or python.exe) for the Private network, or run once:
        netsh advfirewall firewall add rule name="Callbooker 6768" ^
          dir=in action=allow protocol=UDP localport=6768
  * the network profile on PC-B is "Public" (inbound blocked by default)
    - set it to Private, or add the rule above.
  * the two PCs are on different subnets / VLANs / one is on guest Wi-Fi
    with client isolation - broadcast does not cross those.

`send` also prints which broadcast addresses it is aiming at; if your LAN
is not a /24, pass it explicitly:  python dev/lan_probe.py send 10.0.0.255
"""
import json
import os
import socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import n1mm_callbook as cb  # noqa: E402

PORT = cb.LAN_SHARE_PORT  # 6768


def _targets(extra):
    t = ["255.255.255.255"]
    for ip in cb.local_interfaces():
        p = ip.split(".")
        if len(p) == 4 and all(x.isdigit() for x in p):
            d = ".".join(p[:3]) + ".255"
            if d not in t:
                t.append(d)
    for a in extra:
        if a not in t:
            t.append(a)
    return t


def listen():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("", PORT))
    print("listening on UDP {}  (local IPs: {})".format(
        PORT, cb.local_interfaces() or ["?"]))
    print("waiting for probes / Callbooker gossip - Ctrl-C to stop\n")
    while True:
        data, addr = s.recvfrom(65535)
        try:
            m = json.loads(data.decode("utf-8", "replace"))
            kind = ("probe #{}".format(m["probe"]) if "probe" in m
                    else m.get("req") or ("entry " + str(m.get("call", "")))
                    if isinstance(m, dict) else "?")
        except ValueError:
            kind = "non-JSON ({} B)".format(len(data))
        print("  {}  from {:<15}  {}".format(
            time.strftime("%H:%M:%S"), addr[0], kind))


def send(extra):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    targets = _targets(extra)
    me = (cb.local_interfaces() or ["?"])[0]
    print("broadcasting a probe from {} to {} on port {} every 2 s - "
          "Ctrl-C to stop\n".format(me, targets, PORT))
    n = 0
    while True:
        n += 1
        body = json.dumps(
            {"cbshare": cb.LAN_PROTO, "probe": n, "from": me}
        ).encode("utf-8")
        for t in targets:
            try:
                s.sendto(body, (t, PORT))
                mark = "ok"
            except OSError as e:
                mark = "FAILED: {}".format(e)
            print("  #{:<3} -> {:<15} {}".format(n, t, mark))
        time.sleep(2)


if __name__ == "__main__":
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else ""
    if mode == "listen":
        listen()
    elif mode == "send":
        send(sys.argv[2:])
    else:
        print(__doc__)
