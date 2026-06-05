# CSC 364 Assignment 4 — Simple Peer-to-Peer (P2P) File System

Author: Shrey Shah

A small peer-to-peer file sharing system. Each peer acts as both a **server** (it
serves files it owns) and a **client** (it downloads files from other peers). A
central **tracker** keeps a registry of which peer is offering which files so peers
can find each other (the registry add-on).

## Files

| File          | Description                                                        |
|---------------|--------------------------------------------------------------------|
| `peer.py`     | A peer node: serves files, downloads files, registers with tracker |
| `tracker.py`  | Central registry that maps files to the peers offering them        |
| `peerA_files/`, `peerB_files/` | Sample shared directories for testing             |

## How to run

Start the tracker first, then start one or more peers. Each peer shares the files in
its own directory and downloads into that same directory (so anything it downloads is
then re-shared with the rest of the network).

```
# 1. start the tracker
python3 tracker.py localhost 5050

# 2. start peer A (serves the files in peerA_files/)
python3 peer.py localhost 5101 localhost 5050 peerA_files

# 3. start peer B (serves the files in peerB_files/)
python3 peer.py localhost 5102 localhost 5050 peerB_files
```

Peer arguments:

```
python3 peer.py <listen_host> <listen_port> <tracker_host> <tracker_port> <shared_dir> [loss_prob]
```

`loss_prob` is optional (default `0.0`). It simulates packet loss on incoming
transfers so the retransmission logic can be demonstrated, e.g. `0.35` for 35% loss.

### Peer commands (interactive prompt)

| Command          | Action                                                       |
|------------------|--------------------------------------------------------------|
| `list`           | Show every file offered anywhere in the network (asks tracker)|
| `files`          | Show the files this peer is sharing locally                  |
| `peers <file>`   | Show which peers are offering `<file>`                       |
| `get <file>`     | Look up `<file>`, download it from a peer, and start sharing it|
| `help`           | Show the command list                                        |
| `exit`           | Quit                                                         |

Example: on peer B type `get report.txt` to download `report.txt` from peer A.

## Design

### Roles

- **Peer** — runs a TCP server thread to answer file requests, and a client path
  (`get`) to download files. On startup it advertises its files to the tracker and
  re-advertises every 10 seconds (periodic updates) on a background thread.
- **Tracker** — a TCP server holding a registry `peer_id -> {host, port, files,
  last_seen}`. It answers file lookups and prunes peers that stop re-advertising
  (older than 30 seconds).

### Discovery flow

1. A peer connects to the tracker and sends an **OFFER** with its id, address and
   file list. The tracker stores it and replies with an **ACK**.
2. To find a file, a peer sends a **QUERY** with the filename. The tracker replies
   with the list of peers (host, port, id) that currently offer it.
3. The peer connects directly to one of those peers and requests the file. File data
   is transferred peer-to-peer; the tracker is never in the data path.

## Wire protocol

### Framing

The system uses TCP, so every logical message is length-framed on the byte stream:

```
+----------+------------------+------------------+
| type (1) | payload len (4)  | payload (len)    |
+----------+------------------+------------------+
```

`type` is a single ASCII byte. Multi-byte integers are network byte order (`struct`
format `!`). Lists of strings inside a payload are encoded as
`count(4) + [len(4) + bytes]...`.

### Message types

The four message types required by the assignment are `O`, `R`, `T`, `A`. A few extra
types (`M`, `E`, `X`, `Q`, `P`, `L`, `F`) are used for framing the transfer, errors,
and the tracker registry.

| Type | Name          | Direction       | Payload                                              |
|------|---------------|-----------------|------------------------------------------------------|
| `O`  | Offer/Register| peer → tracker  | `peer_id(4)` + strings`[host, port, *filenames]`     |
| `Q`  | Query         | peer → tracker  | filename bytes                                       |
| `P`  | Peers (reply) | tracker → peer  | strings of `host|port|peer_id` for each match        |
| `L`  | List          | peer → tracker  | (empty)                                              |
| `F`  | Files (reply) | tracker → peer  | strings of every filename in the network             |
| `R`  | Request       | peer → peer     | filename bytes                                        |
| `M`  | Meta          | peer → peer     | `file_size(8)` + strings`[md5_hex]`                  |
| `T`  | Transfer      | peer → peer     | `seq(4)` + `checksum(2)` + chunk data (≤1024 bytes)  |
| `A`  | Ack           | peer → peer     | `peer_id(4)` + `ack_seq(4)`                          |
| `E`  | End           | peer → peer     | `peer_id(4)`                                         |
| `X`  | Error         | any             | error message bytes (e.g. `FILE NOT FOUND`)          |

`seq` and `ack_seq` are **byte offsets** into the file (cumulative, like a TCP
sequence number). `ack_seq` is the next byte offset the receiver expects.

### File transfer (stop-and-wait with acknowledgements)

```
client                              server
  | --------- R filename ---------->  |
  | <-------- M size, md5 ----------  |
  | <-------- T seq,csum,data ------  |   chunk 0
  | --------- A peer_id, ack ------>  |
  | <-------- T seq,csum,data ------  |   chunk 1
  | --------- A peer_id, ack ------>  |
  |                ...                |
  | <-------- E peer_id ------------  |   end of file
```

The server sends one 1024-byte chunk at a time and waits for that chunk's `A` ack
before sending the next one.

## Error handling

- **Per-chunk checksum.** Every `T` chunk carries a 16-bit checksum
  (`sum(data) % 65535`). If a received chunk fails the checksum, the receiver drops it
  and does not ack it, which forces the sender to retransmit.
- **Acknowledgements.** The receiver acks each in-order chunk with its next expected
  byte offset (cumulative ack).
- **Timeout + retransmission.** After sending a chunk the server waits up to
  `ACK_TIMEOUT` (0.5 s). If no valid ack arrives it retransmits the same chunk, up to
  `MAX_RETRIES` (30) times before giving up. The retry budget is intentionally large so
  that simulated loss always recovers; only a genuinely dead peer exhausts it.
- **Duplicate handling.** If an ack is lost and the server retransmits a chunk the
  receiver already wrote, the receiver detects the duplicate (`seq < expected`) and
  simply re-acks without writing it again.
- **Missing file / bad request.** The server replies with an `X` error message
  (e.g. `FILE NOT FOUND`) instead of file data.
- **Stale peers.** The tracker drops peers that stop re-advertising within 30 s.

### Simulating loss

Because TCP itself does not lose data, the `loss_prob` argument lets the receiver
randomly pretend a chunk or an ack was lost, which drives the retransmission code
path. Run a peer like:

```
python3 peer.py localhost 5102 localhost 5050 peerB_files 0.35
```

and you will see `[loss] dropped ...` on the downloader and `RETRANSMIT ...` on the
server, while the final file still passes its integrity check.

## Add-ons

- **Tracker server (central registry).** `tracker.py` lets peers discover each other
  by file name instead of needing hard-coded peer addresses.
- **File integrity check.** The `M` metadata message includes the whole-file MD5. The
  downloader recomputes the MD5 of the saved file and reports `[integrity OK]` or
  `INTEGRITY CHECK FAILED`.

## Testing

Tested locally with one tracker and two peers:

1. **Clean transfer** — peer B downloads a small file (`hello.txt`) and a multi-chunk
   file (`report.txt`, ~8 chunks) from peer A. Both pass the MD5 integrity check, and
   the files appear in peer B's `list` afterward (it now re-shares them).
2. **Lossy transfer** — peer B runs with `loss_prob = 0.35`. Chunks and acks are
   dropped and retransmitted, and both files still transfer correctly and pass the
   integrity check.
