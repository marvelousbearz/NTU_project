"""Interactive UDP client for the distributed flight information system."""

from __future__ import annotations

import argparse
import random
import socket
import time
from typing import Any, Callable

from common.flight import Flight
from common.message import (
    BinaryReader,
    MessageKind,
    Operation,
    ProtocolError,
    Status,
    decode_error,
    decode_message,
    encode_message,
    encode_request_payload,
)


class RemoteError(RuntimeError):
    def __init__(self, status: Status, message: str) -> None:
        super().__init__(message)
        self.status = status


class ReliableFlightClient:
    def __init__(
        self,
        host: str,
        port: int,
        semantics: str = "at-most-once",
        timeout: float = 1.0,
        retries: int = 4,
    ) -> None:
        if semantics not in {"at-least-once", "at-most-once"}:
            raise ValueError("unsupported invocation semantics")
        if timeout <= 0 or retries < 0:
            raise ValueError("timeout must be positive and retries cannot be negative")
        self.server_address = (socket.gethostbyname(host), port)
        self.semantics = semantics
        self.timeout = timeout
        self.retries = retries
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.settimeout(timeout)
        self._next_request_id = random.SystemRandom().randint(1, 0xFFFFFFFF)

    def __enter__(self) -> "ReliableFlightClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def close(self) -> None:
        self.socket.close()

    def request(self, operation: Operation, **arguments: Any) -> Any:
        request_id = self._allocate_request_id()
        datagram = encode_message(
            MessageKind.REQUEST,
            operation,
            request_id,
            encode_request_payload(operation, arguments),
        )
        for attempt in range(self.retries + 1):
            self.socket.sendto(datagram, self.server_address)
            if attempt:
                print(
                    f"Retry {attempt}/{self.retries} for request {request_id} "
                    f"({self.semantics})"
                )
            deadline = time.monotonic() + self.timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self.socket.settimeout(remaining)
                try:
                    data, sender = self.socket.recvfrom(65_507)
                except socket.timeout:
                    break
                if sender != self.server_address:
                    continue
                try:
                    reply = decode_message(data)
                except ProtocolError:
                    continue
                if reply.kind is not MessageKind.REPLY or reply.request_id != request_id:
                    continue
                if reply.operation is not operation:
                    continue
                if reply.status is not Status.OK:
                    raise RemoteError(reply.status, decode_error(reply.payload))
                return self._decode_success(operation, reply.payload)
        raise TimeoutError(
            f"server did not reply after {self.retries + 1} attempt(s)"
        )

    def search_flights(self, source: str, destination: str) -> list[int]:
        return self.request(
            Operation.SEARCH_FLIGHTS, source=source, destination=destination
        )

    def get_flight(self, flight_id: int) -> Flight:
        return self.request(Operation.GET_FLIGHT, flight_id=flight_id)

    def reserve_seats(self, flight_id: int, seats: int) -> dict[str, int]:
        return self.request(Operation.RESERVE_SEATS, flight_id=flight_id, seats=seats)

    def set_price(self, flight_id: int, price: float) -> dict[str, float | int]:
        return self.request(Operation.SET_PRICE, flight_id=flight_id, price=price)

    def add_seats(self, flight_id: int, seats: int) -> dict[str, int]:
        return self.request(Operation.ADD_SEATS, flight_id=flight_id, seats=seats)

    def monitor_seats(
        self,
        flight_id: int,
        interval: float,
        on_update: Callable[[int, int], None] | None = None,
    ) -> list[tuple[int, int]]:
        registration = self.request(
            Operation.MONITOR_SEATS, flight_id=flight_id, interval=interval
        )
        updates: list[tuple[int, int]] = []
        callback = on_update or (
            lambda updated_flight, seats: print(
                f"Callback: flight {updated_flight} now has {seats} seat(s) available"
            )
        )
        print(
            f"Monitoring flight {registration['flight_id']} for "
            f"{registration['interval']:.1f}s; current availability is "
            f"{registration['seats']} seat(s)."
        )
        deadline = time.monotonic() + interval
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self.socket.settimeout(remaining)
            try:
                data, sender = self.socket.recvfrom(65_507)
            except socket.timeout:
                break
            if sender != self.server_address:
                continue
            try:
                message = decode_message(data)
            except ProtocolError:
                continue
            if (
                message.kind is not MessageKind.CALLBACK
                or message.operation is not Operation.MONITOR_SEATS
                or message.status is not Status.OK
            ):
                continue
            reader = BinaryReader(message.payload)
            updated_flight = reader.u32()
            seats = reader.u32()
            reader.finish()
            if updated_flight == flight_id:
                updates.append((updated_flight, seats))
                callback(updated_flight, seats)
        print("Monitor interval ended.")
        return updates

    def _allocate_request_id(self) -> int:
        request_id = self._next_request_id
        self._next_request_id = 1 if request_id == 0xFFFFFFFF else request_id + 1
        return request_id

    @staticmethod
    def _decode_success(operation: Operation, payload: bytes) -> Any:
        reader = BinaryReader(payload)
        if operation is Operation.SEARCH_FLIGHTS:
            result = [reader.u32() for _ in range(reader.u16())]
        elif operation is Operation.GET_FLIGHT:
            result = Flight.unmarshal(reader)
        elif operation is Operation.RESERVE_SEATS:
            result = {
                "flight_id": reader.u32(),
                "reserved": reader.u32(),
                "seats": reader.u32(),
            }
        elif operation is Operation.MONITOR_SEATS:
            result = {
                "flight_id": reader.u32(),
                "interval": reader.f64(),
                "seats": reader.u32(),
            }
        elif operation is Operation.SET_PRICE:
            result = {"flight_id": reader.u32(), "price": reader.f64()}
        elif operation is Operation.ADD_SEATS:
            result = {
                "flight_id": reader.u32(),
                "added": reader.u32(),
                "seats": reader.u32(),
            }
        else:
            raise ProtocolError("unsupported reply operation")
        reader.finish()
        return result


MENU = """
1. Search flight identifiers by route
2. Query flight details
3. Reserve seats
4. Monitor seat updates
5. Set airfare (additional idempotent operation)
6. Add seats (additional non-idempotent operation)
0. Exit
"""


def _read_int(prompt: str) -> int:
    return int(input(prompt).strip())


def run_menu(client: ReliableFlightClient) -> None:
    while True:
        print(MENU)
        choice = input("Select an operation: ").strip()
        try:
            if choice == "0":
                print("Client terminated.")
                return
            if choice == "1":
                source = input("Source: ").strip()
                destination = input("Destination: ").strip()
                identifiers = client.search_flights(source, destination)
                print("Matching flight identifier(s):", ", ".join(map(str, identifiers)))
            elif choice == "2":
                print(client.get_flight(_read_int("Flight identifier: ")))
            elif choice == "3":
                result = client.reserve_seats(
                    _read_int("Flight identifier: "), _read_int("Seats to reserve: ")
                )
                print(
                    f"Reservation confirmed: {result['reserved']} seat(s); "
                    f"{result['seats']} remaining."
                )
            elif choice == "4":
                client.monitor_seats(
                    _read_int("Flight identifier: "),
                    float(input("Monitor interval in seconds: ").strip()),
                )
            elif choice == "5":
                result = client.set_price(
                    _read_int("Flight identifier: "),
                    float(input("New airfare: ").strip()),
                )
                print(f"Fare updated to ${result['price']:.2f}.")
            elif choice == "6":
                result = client.add_seats(
                    _read_int("Flight identifier: "), _read_int("Seats to add: ")
                )
                print(
                    f"Added {result['added']} seat(s); "
                    f"{result['seats']} now available."
                )
            else:
                print("Unknown menu choice.")
        except (ValueError, RemoteError, TimeoutError, ProtocolError) as exc:
            print(f"Error: {exc}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8888)
    parser.add_argument(
        "--semantics",
        choices=("at-least-once", "at-most-once"),
        default="at-most-once",
        help="must match the server mode used for the experiment",
    )
    parser.add_argument("--timeout", type=float, default=1.0)
    parser.add_argument("--retries", type=int, default=4)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    with ReliableFlightClient(
        args.host,
        args.port,
        semantics=args.semantics,
        timeout=args.timeout,
        retries=args.retries,
    ) as client:
        run_menu(client)


if __name__ == "__main__":
    main()
