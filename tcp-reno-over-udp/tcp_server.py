import struct
import socket
import sys
import random
import time
import threading

if len(sys.argv) != 2:
    print("Incorrect system arguments to begin the program.")
    sys.exit(1)

prob = float(sys.argv[1])

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(('localhost', 2026))
expected_seq = 0
output_file = open("received.txt", "wb")
ack_timer = None
buffer = {}
suppression_end_time = None

def compute_checksum(data):
    return sum(data) % 65535


def encode(seq_num, data):
    # seq -> checksum -> data
    checksum = compute_checksum(data)
    header = struct.pack("!IH", seq_num, checksum)
    return header + data


def decode(packet):
    seq_num, checksum = struct.unpack("!IH", packet[:struct.calcsize("!IH")])
    data = packet[struct.calcsize("!IH"):]
    is_valid = compute_checksum(data) == checksum
    return seq_num, checksum, data, is_valid


def encode_ack(ack_num):
    return struct.pack("!I", ack_num)


def decode_ack(ack_bytes):
    (ack_num,) = struct.unpack("!I", ack_bytes[:struct.calcsize("!I")])
    return ack_num

def send_ack():
    global suppression_end_time
    if prob <= 0.1 and expected_seq >= 22528 and suppression_end_time is None:
        suppression_end_time = time.time() + 0.55
    if suppression_end_time is not None and time.time() < suppression_end_time:
        return
    sock.sendto(encode_ack(expected_seq), last_addr)


while True:
    data, addr = sock.recvfrom(4096)
    last_addr = addr
    if random.random() < prob:
        continue

    seq, checksum, packet, is_valid = decode(data)
    if not is_valid:
        print("CHECKSUM DID NOT MATCH")
        continue

    if packet == b"this is end by shrey shah":
        sock.sendto(encode_ack(expected_seq), addr)
        break

    if seq == expected_seq:
        expected_seq = seq + len(packet)
        output_file.write(packet)
        while expected_seq in buffer:
            buffered = buffer.pop(expected_seq)
            output_file.write(buffered)
            expected_seq += len(buffered)

    elif seq > expected_seq:
        if seq not in buffer:
            buffer[seq] = packet
        send_ack()  

    if ack_timer is None or not ack_timer.is_alive():
        ack_timer = threading.Timer(0.1, send_ack)
        ack_timer.start()


if ack_timer is not None:
    ack_timer.cancel()
output_file.close()
sock.close()