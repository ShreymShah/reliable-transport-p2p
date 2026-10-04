import struct
import sys
import socket
import os
import time
import csv

def compute_checksum(data):
    return sum(data) % 65535

def encode(seq_num, data):
    # seq checksum data
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

def read_chunks(file):
    chunks = []
    with open(file, "rb") as f:
        while True:
            chunk = f.read(1024)
            if not chunk:
                break
            chunks.append(chunk)

    return chunks

if len(sys.argv) not in (2, 3):
    print("Usage: python3 tcp_client.py <file> [run_label]")
    sys.exit(1)

# Label for the output CSVs, e.g. "10" writes cwnd_10.csv and retransmit_10.csv
run_label = sys.argv[2] if len(sys.argv) == 3 else "run"

file = sys.argv[1]
try:
    file_size = os.path.getsize(file)

except:
    print("FILE PATH INVALID")
    sys.exit(1)

chunks = read_chunks(file)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
addr = ('localhost', 2026)

cwnd = 1
sstresh = 100
last_ack = 0
number_acks = 0
next_seq = 0
in_recovery = False
recovery_point = 0
cwnd_list = [[1, 0.0]]
start_t = time.time()
retransmission_list = [[0,0]]

sock.settimeout(0.5)


while last_ack < file_size:
    
    while (next_seq - last_ack) // 1024 < cwnd and next_seq < file_size:
        i = next_seq // 1024
        sock.sendto(encode(next_seq, chunks[i]), addr)
        next_seq += len(chunks[i])
    
        

    try:
        data, addr = sock.recvfrom(4096)
        ack_num = decode_ack(data)
        if ack_num > last_ack:
            if in_recovery and ack_num < recovery_point:
                last_ack = ack_num
                next_seq = last_ack
                retransmission_list.append([retransmission_list[-1][0] + 1, time.time() - start_t])
                number_acks = 0
            else:
                if in_recovery and ack_num >= recovery_point:
                    in_recovery = False
                    cwnd = sstresh  
                acked = (ack_num - last_ack) // 1024
                if cwnd < sstresh:
                    cwnd += acked
                    cwnd_list.append([cwnd, (time.time() - start_t) / 0.1])
                else:
                    cwnd += acked/cwnd
                    cwnd_list.append([cwnd, (time.time() - start_t) / 0.1])
                last_ack = ack_num
                if next_seq < last_ack:
                    next_seq = last_ack
                number_acks = 0

        elif ack_num == last_ack:
            number_acks+=1

            if in_recovery:
                cwnd += 1

            if not in_recovery and number_acks <= 2 and next_seq < file_size:
                i = next_seq // 1024
                sock.sendto(encode(next_seq, chunks[i]), addr)
                next_seq += len(chunks[i])

            if number_acks >= 3 and not in_recovery:
                # print('TRIPLE ACK')
                cwnd = max(cwnd // 2, 2)
                cwnd_list.append([cwnd, (time.time() - start_t) / 0.1])
                sstresh = max(cwnd, 4)
                recovery_point = next_seq
                in_recovery = True
                next_seq = last_ack
                retransmission_list.append([retransmission_list[-1][0] + 1, time.time() - start_t])
                number_acks = 0
            elif in_recovery and number_acks >= 3:
                # print('RE-RETRANSMIT')
                next_seq = last_ack
                retransmission_list.append([retransmission_list[-1][0] + 1, time.time() - start_t])
                number_acks = 0

    except socket.timeout:
        print('TIMEOUT')
        retransmission_list.append([retransmission_list[-1][0] + 1, time.time() - start_t])
        sstresh = max(cwnd // 2, 4)
        cwnd = 1
        cwnd_list.append([cwnd, (time.time() - start_t) / 0.1])
        next_seq = last_ack
        number_acks = 0
        in_recovery = False
        

    # all_time_out = True
    # # timeout check
    # for key, value in times.items():
    #     if (time.time() - value[0]) <= 0.5:
    #         all_time_out = False

    #     else:
    #         sock.sendto(encode(key, chunks[value[1]]), addr)
    #         retransmission_list.append([retransmission_list[-1][0] + 1, time.time() - start_t])
    #         times[key] = [time.time(), value[1]]

    # if times and all_time_out:
    #     if cwnd > 1:
    #             sstresh = max(cwnd // 2, 1)
    #             cwnd = 1
    #             cwnd_list.append([cwnd, (time.time() - start_t) / 0.1])
    #             number_acks = 0


end_msg = encode(next_seq, b"this is end by shrey shah")
for _ in range(10):
    sock.sendto(end_msg, addr)
    time.sleep(0.05)

sock.close()

with open(f"cwnd_{run_label}.csv", "w") as f:
    w = csv.writer(f)
    w.writerow(["cwnd", "time_rtts"])
    w.writerows(cwnd_list)

with open(f"retransmit_{run_label}.csv", "w") as f:
    w = csv.writer(f)
    w.writerow(["count", "time_s"])
    w.writerows(retransmission_list)