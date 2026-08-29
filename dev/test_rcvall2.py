"""Does a Windows SIO_RCVALL raw socket capture a LOCALLY-originated
subnet-broadcast UDP datagram to port 6767? (VHFCtest4WIN runs on the
same PC as the callbook, so its 6767 broadcast is local-origin - the
known weak spot of SIO_RCVALL, which is documented to skip outbound.)

Run elevated. Writes result to dev/test_rcvall2.out. No VHFCtest needed.
"""
import socket
import struct
import threading
import time

OUT = __file__.replace(".py", ".out")


def log(*a):
    line = " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(OUT, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")


open(OUT, "w").close()

ips = [i for i in socket.gethostbyname_ex(socket.gethostname())[2]]
log("local IPs:", ips)
zt = next((i for i in ips if i.startswith("10.147.")), None)
targets = []
if zt:
    targets.append((zt, ".".join(zt.split(".")[:3]) + ".255", "subnet-bcast"))
    targets.append((zt, "255.255.255.255", "limited-bcast"))
    targets.append((zt, zt, "unicast-self"))

raws = []
for ip in ips:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
        s.bind((ip, 0))
        s.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
        s.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
        s.settimeout(3)
        raws.append((ip, s))
        log("RCVALL socket up on", ip)
    except OSError as e:
        log("RCVALL failed on", ip, "->", e)

if not raws:
    log("RESULT: no raw sockets - not elevated?")
    raise SystemExit

hits = []


def sniff(ip, s):
    end = time.time() + 3
    while time.time() < end:
        try:
            pkt = s.recv(65535)
        except socket.timeout:
            return
        except OSError:
            return
        if len(pkt) < 28 or pkt[9] != 17:
            continue
        ihl = (pkt[0] & 0x0F) * 4
        sport, dport = struct.unpack("!HH", pkt[ihl:ihl + 4])
        if dport != 6767:
            continue
        payload = pkt[ihl + 8:]
        hits.append((ip, socket.inet_ntoa(pkt[12:16]),
                     socket.inet_ntoa(pkt[16:20]), sport, dport, bytes(payload[:80])))


threads = [threading.Thread(target=sniff, args=(ip, s)) for ip, s in raws]
for t in threads:
    t.start()
time.sleep(0.4)

snd = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
snd.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
for bind_ip, dst, label in targets:
    try:
        snd.sendto(("<V4W><QSOINLOG><CALLSIGN>S56M</CALLSIGN><WWL>JN76GB"
                    "</WWL></QSOINLOG></V4W> " + label).encode(), (dst, 6767))
        log("sent", label, "->", dst)
    except OSError as e:
        log("send", label, "failed:", e)

for t in threads:
    t.join()
for ip, s in raws:
    try:
        s.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
        s.close()
    except OSError:
        pass

log("--- captured 6767 datagrams ---")
for h in hits:
    log(" ", h)
log("RESULT:", "CAPTURED locally-originated broadcast" if hits
    else "NOTHING captured (RCVALL misses local-origin broadcast)")
