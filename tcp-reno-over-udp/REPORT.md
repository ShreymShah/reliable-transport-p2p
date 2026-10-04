# TCP Reno over UDP: Report

Shrey Shah

## 1. How the congestion control mechanisms were implemented

Slow start begins with `cwnd = 1` and increments `cwnd` by 1 for every new ACK (so `cwnd` roughly doubles each RTT) until it reaches `ssthresh`, after which congestion avoidance grows `cwnd` linearly by `1/cwnd` per ACK.

Fast retransmit fires when the client receives 3 duplicate ACKs for the same `last_ack`: `ssthresh` is set to `cwnd/2`, `cwnd` is halved, and the missing packet is retransmitted immediately. To match the TCP Reno algorithm from lecture, a `recovery_point` is recorded at entry so duplicate ACKs from the same loss event do not repeatedly halve `cwnd`, and recovery exits once the cumulative ACK reaches that point.

## 2. How timeouts and retransmissions were handled

The client uses `sock.settimeout(0.5)` so a `socket.timeout` exception fires when no ACK arrives within 500 ms. On timeout, `ssthresh = cwnd // 2`, `cwnd = 1`, recovery state is cleared, and `next_seq` is reset to `last_ack` so the inner send loop immediately retransmits the unacknowledged packet.

Retransmissions also fire:

- via fast retransmit (on 3 duplicate ACKs),
- via partial-ACK retransmission during recovery (when a new ACK advances but is still below the recovery point), and
- via a re-retransmit path triggered when 3 more duplicate ACKs accumulate during recovery (handling the case where the retransmission itself was lost).

Each retransmission event is timestamped into `retransmission_list` for graphing.

## 3. Insights from the graphs

The cwnd vs. RTT graphs show the loss and recovery relationship clearly:

- **1% loss:** `cwnd` ramps up to about 35 packets with a single visible dip caused by the hardcoded test timeout (`cwnd` drops to 1 around RTT 9 to 15), then climbs linearly through congestion avoidance.
- **10% loss:** `cwnd` oscillates rapidly between 2 and 10 in a classic Reno sawtooth, averaging about 4 to 6.
- **50% loss:** `cwnd` is collapsed to 1 most of the time with only brief spikes to about 5 to 10, showing congestion control essentially stuck in slow start.

The retransmissions vs. time graphs reflect this:

- **1% loss** accumulates only about 39 retransmissions over about 6 s, mostly concentrated in a few bursts from the timeout event.
- **10% loss** climbs steadily to about 123 over about 13 s, a linear trend reflecting the constant loss rate.
- **50% loss** reaches about 470 retransmissions over about 60 s, with visible plateaus between timeout-driven bursts.

Higher packet loss directly translates to longer transfer time, smaller average `cwnd`, and a higher retransmission slope.

| Loss | Congestion window vs. RTT | Retransmissions vs. time |
|------|---------------------------|--------------------------|
| 1% | ![cwnd at 1% loss](graphs/cwnd_1.png) | ![retransmissions at 1% loss](graphs/retransmit_1.png) |
| 10% | ![cwnd at 10% loss](graphs/cwnd_10.png) | ![retransmissions at 10% loss](graphs/retransmit_10.png) |
| 50% | ![cwnd at 50% loss](graphs/cwnd_50.png) | ![retransmissions at 50% loss](graphs/retransmit_50.png) |

## 4. Challenges faced and lessons learned

The hardest challenges were:

- **Preventing the cwnd cascade,** where every 3-duplicate-ACK event halved `cwnd`, driving it to 1 within a few drops.
- **Handling the deadlock at small cwnd,** where a single dropped packet at `cwnd = 2` could not generate enough duplicate ACKs to fire fast retransmit.

Both required implementing one-halving-per-loss-event recovery, `cwnd` inflation during recovery, partial-ACK retransmission, and sending an extra packet on each early duplicate ACK.

Coordinating the client-side Reno state with the server-side cumulative ACK semantics also required careful design. In particular, the server buffers out-of-order packets so that the gap-filling ACK after a fast retransmit advances `expected_seq` correctly, and both the timer ACK and immediate duplicate ACK paths honor the hardcoded test suppression.

The biggest lesson was that the textbook three-line summary of slow start, congestion avoidance, and fast retransmit is not enough. The recovery details (when not to halve `cwnd`, when to keep retransmitting, how to handle partial ACKs) are where correctness actually lives.
