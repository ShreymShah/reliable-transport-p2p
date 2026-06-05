import socket
import struct
import sys
import threading
import time

if len(sys.argv) != 3:
    print("Incorrect system arguments to begin the program.")
    sys.exit(1)

host = sys.argv[1]
port = int(sys.argv[2])

registry = {}
registry_lock = threading.Lock()

stale_sec = 30

def recv_exact(conn, n):
    data = b""
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            return None
        data += chunk
    return data

def recv_msg(conn):
    header = recv_exact(conn, 5)
    if header is None:
        return None, None
    msg_type = header[:1]
    length = struct.unpack("!I", header[1:5])[0]
    payload = recv_exact(conn, length) if length > 0 else b""
    return msg_type, payload

def send_msg(conn, msg_type, payload=b""):
    conn.sendall(msg_type + struct.pack("!I", len(payload)) + payload)

def pack_strings(strings):
    out = struct.pack("!I", len(strings))
    for s in strings:
        b = s.encode("utf-8")
        out += struct.pack("!I", len(b)) + b
    return out

def unpack_strings(payload):
    count = struct.unpack("!I", payload[:4])[0]
    offset = 4
    result = []
    for _ in range(count):
        length = struct.unpack("!I", payload[offset:offset+4])[0]
        offset += 4
        result.append(payload[offset:offset+length].decode("utf-8"))
        offset += length
    return result

def handle_offer(payload):
    peer_id = struct.unpack("!I", payload[:4])[0]
    fields = unpack_strings(payload[4:])
    peer_host = fields[0]
    peer_port = int(fields[1])
    files = set(fields[2:])

    with registry_lock:
        registry[peer_id] = {
            "host": peer_host,
            "port": peer_port,
            "files": files,
            "last_seen": time.time(),
        }
    print(f"OFFER from peer {peer_id} ({peer_host}:{peer_port}) -> {sorted(files)}")

def handle_query(payload):
    filename = payload.decode("utf-8")
    matches = []
    with registry_lock:
        for peer_id, info in registry.items():
            if filename in info["files"]:
                matches.append(f"{info['host']}|{info['port']}|{peer_id}")
    print(f"QUERY for '{filename}' -> {len(matches)} peer(s)")
    return pack_strings(matches)

def handle_list():
    files = set()
    with registry_lock:
        for info in registry.values():
            files.update(info["files"])
    return pack_strings(sorted(files))

def handle_client(conn, addr):
    try:
        msg_type, payload = recv_msg(conn)
        if msg_type is None:
            return

        if msg_type == b"O":
            handle_offer(payload)
            send_msg(conn, b"A")

        elif msg_type == b"Q":
            send_msg(conn, b"P", handle_query(payload))

        elif msg_type == b"L":
            send_msg(conn, b"F", handle_list())

        else:
            send_msg(conn, b"X", "UNKNOWN MESSAGE TYPE".encode("utf-8"))

    except Exception as e:
        print(f"ERROR handling client {addr}: {e}")
    finally:
        conn.close()

def prune_stale_peers():
    while True:
        now = time.time()
        with registry_lock:
            for peer_id in list(registry.keys()):
                if now - registry[peer_id]["last_seen"] > stale_sec:
                    print(f"PRUNING stale peer {peer_id}")
                    registry.pop(peer_id)
        time.sleep(stale_sec)

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
server.bind((host, port))
server.listen()
print(f"Tracker listening on {host}:{port}")

prune_thread = threading.Thread(target=prune_stale_peers, daemon=True)
prune_thread.start()

try:
    while True:
        conn, addr = server.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
        t.start()
except KeyboardInterrupt:
    print("\nTracker shutting down.")
finally:
    server.close()
