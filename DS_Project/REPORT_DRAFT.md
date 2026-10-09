# SC6103 Course Project Report Draft

> Complete the group names, matriculation-card names, contribution percentages,
> machine/network details, and measured experiment output before submission.

## 1. Group information

| Member name | Matriculation number | Responsibility | Contribution |
|---|---|---|---:|
| TODO | TODO | TODO | TODO% |

The contribution percentages must total 100%.

## 2. Architecture

The system deliberately uses two implementation languages for the optional
cross-language requirement: the UDP server is implemented in C++17, while the
console client and its shared client-side models are implemented in Python 3.
Neither side imports or calls code from the other language. Their only contract is
the language-neutral byte-level network protocol described below.

The system uses one C++ UDP server and any number of Python UDP clients. The
server keeps flight data in memory. A client repeatedly reads a console command,
marshals a request to bytes, sends one UDP datagram, and waits for a matching
reply. If a timeout occurs, it retransmits the identical datagram with the same
request ID.

The server is deliberately single-threaded for request execution because the
project permits the assumption that ordinary requests are well separated. It can
still support concurrent monitors: each registration is a record containing the
client's IP/port, flight ID, and monotonic expiry time. A reservation or seat
addition sends a callback datagram to every unexpired matching record.

## 3. Flight data

Each flight stores a 32-bit unsigned identifier, two variable-length UTF-8 place
names, an hour and minute, an IEEE-754 64-bit fare, and a 32-bit unsigned seat
count. The initial in-memory dataset contains two Singapore-Tokyo flights and one
flight each on two other routes.

## 4. Message design and marshalling

Every datagram starts with this fixed 16-byte network-byte-order header:

| Field | Size | Meaning |
|---|---:|---|
| Magic | 4 bytes | ASCII `FLIT` |
| Version | 1 byte | Protocol version 1 |
| Kind | 1 byte | request, reply, or callback |
| Operation | 1 byte | operation code 1-6 |
| Status | 1 byte | success or error category |
| Request ID | 4 bytes | duplicate detection and reply matching |
| Payload length | 4 bytes | exact number of following bytes |

Unsigned integers and doubles use big-endian network order. Each UTF-8 string is
encoded as a 2-byte unsigned byte length followed by exactly that many bytes.
Payloads vary by operation. For example, a search request contains two strings;
a reservation contains a flight ID and seat count; and a flight-detail reply
contains all fields of the flight record. Errors contain a variable-length string.
Decoders reject truncation, trailing bytes, bad magic/version values, unknown enum
values, and payload lengths that disagree with the header.

The C++ server and Python client contain independent implementations of this
format. C++ uses explicit byte shifts and `memcpy` for IEEE-754 double bit patterns;
Python uses the `struct` module with the `!` network-order prefix. Successful
cross-language integration tests confirm that both implementations produce and
consume identical byte sequences.

## 5. Operations

The four required operations are route search, detail query, reservation, and
monitor registration/callback. Errors are returned for missing flights, missing
routes, non-positive counts, insufficient seats, invalid intervals, and malformed
messages.

The additional **idempotent** operation sets a flight's airfare to an absolute
value. Repeating `set price to 499.50` leaves the same final state. The additional
**non-idempotent** operation adds a number of seats. Repeating `add 3 seats`
changes the final state again, so duplicate execution is visible.

## 6. Fault tolerance and invocation semantics

The client sets a timeout and resends the exact request when no reply arrives.
This provides at-least-once delivery when communication eventually succeeds.

In at-least-once server mode, every received datagram is executed, including a
duplicate. This is safe for idempotent operations but can corrupt the intended
result for non-idempotent operations.

In at-most-once server mode, the server maintains a bounded ordered history keyed
by client address/port and request ID. The history stores both the original request
bytes and encoded reply. A duplicate returns the cached reply without executing
the operation again. Reusing an ID with different request bytes produces an error.
The result is placed in history before reply transmission, so loss of that reply
does not cause re-execution on retry.

## 7. Loss simulation and experiment

The server supports probabilistic request/reply loss and deterministic loss of the
first request or first reply for each request ID. Deterministic first-reply loss is
used for a repeatable comparison:

1. Start with flight 1001 having 40 seats.
2. Run the server in at-least-once mode with `--drop-first-reply`.
3. Ask the client to add 3 seats. The server executes once, loses the reply, then
   executes the retry. The observed final value is 46 instead of 43.
4. Restart with the same initial data in at-most-once mode.
5. Repeat the operation. The first execution produces 43 and its reply is lost.
   The retry obtains the cached reply; the final value remains 43.
6. Repeat with the idempotent set-price operation. Both modes have the same final
   fare even if the operation executes twice.

TODO: paste representative server/client logs, record machine IP addresses, and
add a table of measured attempts, elapsed time, and final values.

## 8. Validation

The automated test suite compiles and starts the actual C++ server, then exercises
it through the Python client. It checks binary round trips with variable-length
non-ASCII strings, malformed lengths, all six services, error replies, callback
delivery between two Python clients, and both invocation-semantics outcomes under
deterministic reply loss. Thus the service tests are cross-language tests rather
than tests against a Python mock server.

TODO: record the final test command output and the cross-computer demonstration.

## 9. Limitations and possible improvements

Flight data and at-most-once history are in memory and are lost on restart, which
is allowed by the brief. A production design could persist flights and deduplication
records, authenticate administrative operations, encrypt traffic, use a durable
client identity independent of UDP source port, and define fragmentation for data
larger than one safe UDP datagram.
