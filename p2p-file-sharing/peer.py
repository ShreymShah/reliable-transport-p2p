import socket
import struct
import sys
import os
import time
import threading
import random
import hashlib

if len(sys.argv) < 6 or len(sys.argv) > 7:
    print("Incorrect system arguments to begin the program.")
    print("Usage: python3 peer.py <listen_host> <listen_port> <tracker_host> <tracker_port> <shared_dir> [loss_prob]")
    sys.exit(1)

listen_host = sys.argv[1]
listen_port = int(sys.argv[2])
tracker_addr = (sys.argv[3], int(sys.argv[4]))
shared_dir = sys.argv[5]
loss_prob = float(sys.argv[6]) if len(sys.argv) == 7 else 0.0

peer_id = random.randint(0, 2**32 - 1)

if not os.path.isdir(shared_dir):
    print("SHARED DIRECTORY DOES NOT EXIST")
    sys.exit(1)

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

def compute_checksum(data):
    return sum(data) % 65535

def file_md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        while True:
            block = f.read(1024)
            if not block:
                break
            h.update(block)
    return h.hexdigest()

def list_local_files():
    return [f for f in os.listdir(shared_dir) if os.path.isfile(os.path.join(shared_dir, f))]

def print_with_format(msg):
    print(f"\r{msg}\n> ", end="", flush=True)

def register_with_tracker():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(tracker_addr)
        fields = [listen_host, str(listen_port)] + list_local_files()
        payload = struct.pack("!I", peer_id) + pack_strings(fields)
        send_msg(sock, b"O", payload)
        recv_msg(sock)
        sock.close()
    except Exception as e:
        print(f"COULD NOT REACH TRACKER: {e}")

def periodic_register():
    while True:
        register_with_tracker()
        time.sleep(10)

def query_tracker(filename, include_self=False):
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(tracker_addr)
        send_msg(sock, b"Q", filename.encode("utf-8"))
        msg_type, payload = recv_msg(sock)
        sock.close()
        if msg_type != b"P":
            return []
        peers = []
        for entry in unpack_strings(payload):
            host, p, pid = entry.split("|")
            if include_self or int(pid) != peer_id:
                peers.append((host, int(p), int(pid)))
        return peers
    except Exception as e:
        print(f"COULD NOT REACH TRACKER: {e}")
        return []

def list_tracker_files():
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(tracker_addr)
        send_msg(sock, b"L")
        msg_type, payload = recv_msg(sock)
        sock.close()
        if msg_type != b"F":
            return []
        return unpack_strings(payload)
    except Exception as e:
        print(f"COULD NOT REACH TRACKER: {e}")
        return []

def serve_file(conn, filename):
    path = os.path.join(shared_dir, filename)
    if not os.path.isfile(path):
        send_msg(conn, b"X", "FILE NOT FOUND".encode("utf-8"))
        return

    file_size = os.path.getsize(path)
    meta = struct.pack("!Q", file_size) + pack_strings([file_md5(path)])
    send_msg(conn, b"M", meta)

    conn.settimeout(0.5)
    with open(path, "rb") as f:
        seq = 0
        while True:
            data = f.read(1024)
            if not data:
                break

            packet = struct.pack("!IH", seq, compute_checksum(data)) + data
            retries = 0
            while True:
                send_msg(conn, b"T", packet)
                try:
                    msg_type, payload = recv_msg(conn)
                    if msg_type == b"A":
                        ack_id, ack_seq = struct.unpack("!II", payload)
                        if ack_seq >= seq + len(data):
                            break
                    raise socket.timeout
                except socket.timeout:
                    retries += 1
                    if retries > 30:
                        print_with_format(f"GAVE UP on chunk at offset {seq} after 30 retries")
                        conn.settimeout(None)
                        return
                    print_with_format(f"RETRANSMIT chunk at offset {seq} (retry {retries})")

            seq += len(data)

    send_msg(conn, b"E", struct.pack("!I", peer_id))
    conn.settimeout(None)
    print_with_format(f"Served '{filename}' ({file_size} bytes)")

def handle_peer(conn, addr):
    try:
        msg_type, payload = recv_msg(conn)
        if msg_type == b"R":
            filename = payload.decode("utf-8")
            print_with_format(f"REQUEST for '{filename}' from {addr}")
            serve_file(conn, filename)
        else:
            send_msg(conn, b"X", "EXPECTED A FILE REQUEST".encode("utf-8"))
    except Exception as e:
        print_with_format(f"ERROR serving {addr}: {e}")
    finally:
        conn.close()

def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((listen_host, listen_port))
    server.listen()
    while True:
        conn, addr = server.accept()
        t = threading.Thread(target=handle_peer, args=(conn, addr), daemon=True)
        t.start()

def download_from_peer(host, port, filename):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((host, port))
    send_msg(sock, b"R", filename.encode("utf-8"))

    msg_type, payload = recv_msg(sock)
    if msg_type == b"X":
        print(f"PEER ERROR: {payload.decode('utf-8')}")
        sock.close()
        return False
    if msg_type != b"M":
        print("UNEXPECTED RESPONSE FROM PEER")
        sock.close()
        return False

    file_size = struct.unpack("!Q", payload[:8])[0]
    expected_md5 = unpack_strings(payload[8:])[0]

    out_path = os.path.join(shared_dir, filename)
    expected_seq = 0
    with open(out_path, "wb") as out:
        while True:
            msg_type, payload = recv_msg(sock)
            if msg_type is None:
                print("CONNECTION CLOSED MID-TRANSFER")
                sock.close()
                return False
            if msg_type == b"E":
                break

            if msg_type != b"T":
                continue

            seq, checksum = struct.unpack("!IH", payload[:6])
            data = payload[6:]

            if random.random() < loss_prob:
                print(f"[loss] dropped chunk at offset {seq} (simulated)")
                continue

            if compute_checksum(data) != checksum:
                print(f"CHECKSUM MISMATCH at offset {seq}, dropping")
                continue

            if seq == expected_seq:
                out.write(data)
                expected_seq += len(data)

            if random.random() < loss_prob:
                print(f"[loss] dropped ack for offset {expected_seq} (simulated)")
                continue

            send_msg(sock, b"A", struct.pack("!II", peer_id, expected_seq))

    sock.close()

    actual_md5 = file_md5(out_path)
    if actual_md5 == expected_md5:
        print(f"DOWNLOAD COMPLETE: '{filename}' ({file_size} bytes) saved to {out_path} [integrity OK]")
        return True
    else:
        print(f"INTEGRITY CHECK FAILED for '{filename}' (expected {expected_md5}, got {actual_md5})")
        return False

def get_file(filename):
    if os.path.isfile(os.path.join(shared_dir, filename)):
        print("YOU ALREADY HAVE THIS FILE")
        return
    peers = query_tracker(filename)
    if not peers:
        print(f"NO PEER IS OFFERING '{filename}'")
        return
    for host, port, pid in peers:
        print(f"Downloading '{filename}' from peer {pid} at {host}:{port}")
        try:
            if download_from_peer(host, port, filename):
                register_with_tracker()
                return
        except Exception as e:
            print(f"FAILED from {host}:{port}: {e}")
    print(f"COULD NOT DOWNLOAD '{filename}' FROM ANY PEER")

print(f"Peer {peer_id} sharing '{shared_dir}' on {listen_host}:{listen_port}")
print(f"Files: {list_local_files()}")
if loss_prob > 0:
    print(f"Simulating {loss_prob*100:.0f}% packet loss on incoming transfers")

server_thread = threading.Thread(target=start_server, daemon=True)
server_thread.start()

register_thread = threading.Thread(target=periodic_register, daemon=True)
register_thread.start()

time.sleep(0.3)

help_msg = """commands:
  list              show every file offered in the network (via tracker)
  files             show the files this peer is sharing locally
  peers <file>      show which peers offer a file
  get <file>        download a file from a peer and start sharing it
  help              show this help
  exit              quit
"""
print(help_msg)

try:
    while True:
        line = input("> ").strip()
        if not line:
            continue
        words = line.split()
        cmd = words[0]

        if cmd == "list":
            files = list_tracker_files()
            if files:
                print("Files available in the network:")
                for f in files:
                    print(f"  {f}")
            else:
                print("No files available.")

        elif cmd == "files":
            print("Sharing locally:")
            for f in list_local_files():
                print(f"  {f}")

        elif cmd == "peers":
            if len(words) < 2:
                print("Missing argument")
                continue
            peers = query_tracker(words[1], include_self=True)
            if peers:
                for host, port, pid in peers:
                    label = "  (this peer)" if pid == peer_id else ""
                    print(f"  peer {pid} at {host}:{port}{label}")
            else:
                print("No peers offer that file.")

        elif cmd == "get":
            if len(words) < 2:
                print("Missing argument")
                continue
            get_file(words[1])

        elif cmd == "help":
            print(help_msg)

        elif cmd == "exit":
            break

        else:
            print("UNKNOWN COMMAND (type 'help')")

except (EOFError, KeyboardInterrupt):
    pass

print("\nPeer shutting down.")
