from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Any


MAGIC = b"FLIT"
VERSION = 1
HEADER = struct.Struct("!4sBBBBII")
MAX_STRING_BYTES = 65_535
MAX_PAYLOAD_BYTES = 60_000


class ProtocolError(ValueError):
    pass


class MessageKind(IntEnum):
    REQUEST = 1
    REPLY = 2
    CALLBACK = 3


class Operation(IntEnum):
    SEARCH_FLIGHTS = 1
    GET_FLIGHT = 2
    RESERVE_SEATS = 3
    MONITOR_SEATS = 4
    SET_PRICE = 5       # Additional idempotent operation.
    ADD_SEATS = 6       # Additional non-idempotent operation.


class Status(IntEnum):
    OK = 0
    BAD_REQUEST = 1
    NOT_FOUND = 2
    INSUFFICIENT_SEATS = 3
    INTERNAL_ERROR = 4


class BinaryWriter:
    def __init__(self) -> None:
        self._parts: list[bytes] = []

    def u8(self, value: int) -> None:
        self._parts.append(struct.pack("!B", value))

    def u16(self, value: int) -> None:
        self._parts.append(struct.pack("!H", value))

    def u32(self, value: int) -> None:
        self._parts.append(struct.pack("!I", value))

    def f64(self, value: float) -> None:
        self._parts.append(struct.pack("!d", value))

    def string(self, value: str) -> None:
        encoded = value.encode("utf-8")
        if len(encoded) > MAX_STRING_BYTES:
            raise ProtocolError("string is too long")
        self.u16(len(encoded))
        self._parts.append(encoded)

    def build(self) -> bytes:
        return b"".join(self._parts)


class BinaryReader:
    def __init__(self, data: bytes, offset: int = 0) -> None:
        self.data = data
        self.offset = offset

    def _take(self, size: int) -> bytes:
        end = self.offset + size
        if end > len(self.data):
            raise ProtocolError("truncated message")
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def u8(self) -> int:
        return struct.unpack("!B", self._take(1))[0]

    def u16(self) -> int:
        return struct.unpack("!H", self._take(2))[0]

    def u32(self) -> int:
        return struct.unpack("!I", self._take(4))[0]

    def f64(self) -> float:
        return struct.unpack("!d", self._take(8))[0]

    def string(self) -> str:
        size = self.u16()
        try:
            return self._take(size).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ProtocolError("invalid UTF-8 string") from exc

    def finish(self) -> None:
        if self.offset != len(self.data):
            raise ProtocolError("unexpected trailing bytes")


@dataclass(frozen=True, slots=True)
class Message:
    kind: MessageKind
    operation: Operation
    status: Status
    request_id: int
    payload: bytes


def encode_message(
    kind: MessageKind,
    operation: Operation,
    request_id: int,
    payload: bytes = b"",
    status: Status = Status.OK,
) -> bytes:
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ProtocolError("payload is too large for a UDP message")
    return HEADER.pack(
        MAGIC,
        VERSION,
        int(kind),
        int(operation),
        int(status),
        request_id,
        len(payload),
    ) + payload


def decode_message(data: bytes) -> Message:
    if len(data) < HEADER.size:
        raise ProtocolError("message is shorter than the protocol header")
    magic, version, kind, operation, status, request_id, size = HEADER.unpack_from(data)
    if magic != MAGIC or version != VERSION:
        raise ProtocolError("unsupported protocol magic or version")
    payload = data[HEADER.size:]
    if size != len(payload):
        raise ProtocolError("payload length does not match header")
    try:
        return Message(
            MessageKind(kind), Operation(operation), Status(status), request_id, payload
        )
    except ValueError as exc:
        raise ProtocolError("unknown message kind, operation, or status") from exc


def encode_request_payload(operation: Operation, arguments: dict[str, Any]) -> bytes:
    writer = BinaryWriter()
    if operation is Operation.SEARCH_FLIGHTS:
        writer.string(arguments["source"])
        writer.string(arguments["destination"])
    elif operation is Operation.GET_FLIGHT:
        writer.u32(arguments["flight_id"])
    elif operation is Operation.RESERVE_SEATS:
        writer.u32(arguments["flight_id"])
        writer.u32(arguments["seats"])
    elif operation is Operation.MONITOR_SEATS:
        writer.u32(arguments["flight_id"])
        writer.f64(arguments["interval"])
    elif operation is Operation.SET_PRICE:
        writer.u32(arguments["flight_id"])
        writer.f64(arguments["price"])
    elif operation is Operation.ADD_SEATS:
        writer.u32(arguments["flight_id"])
        writer.u32(arguments["seats"])
    else:
        raise ProtocolError("unsupported request operation")
    return writer.build()


def decode_request_payload(operation: Operation, payload: bytes) -> dict[str, Any]:
    reader = BinaryReader(payload)
    if operation is Operation.SEARCH_FLIGHTS:
        result = {"source": reader.string(), "destination": reader.string()}
    elif operation is Operation.GET_FLIGHT:
        result = {"flight_id": reader.u32()}
    elif operation is Operation.RESERVE_SEATS:
        result = {"flight_id": reader.u32(), "seats": reader.u32()}
    elif operation is Operation.MONITOR_SEATS:
        result = {"flight_id": reader.u32(), "interval": reader.f64()}
    elif operation is Operation.SET_PRICE:
        result = {"flight_id": reader.u32(), "price": reader.f64()}
    elif operation is Operation.ADD_SEATS:
        result = {"flight_id": reader.u32(), "seats": reader.u32()}
    else:
        raise ProtocolError("unsupported request operation")
    reader.finish()
    return result


def encode_error(message: str) -> bytes:
    writer = BinaryWriter()
    writer.string(message)
    return writer.build()


def decode_error(payload: bytes) -> str:
    reader = BinaryReader(payload)
    value = reader.string()
    reader.finish()
    return value
