from __future__ import annotations

import socket
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from client import ReliableFlightClient, RemoteError  # noqa: E402
from common.flight import Flight  # noqa: E402
from common.message import (  # noqa: E402
    MessageKind,
    Operation,
    ProtocolError,
    decode_message,
    encode_message,
    encode_request_payload,
)


def reserve_udp_port() -> int:
    temporary = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    temporary.bind(("127.0.0.1", 0))
    port = temporary.getsockname()[1]
    temporary.close()
    return port


class RunningCppServer:
    """Build and run the real C++ server used by the Python client."""

    binary = PROJECT_ROOT / "flight_server"

    @classmethod
    def build(cls) -> None:
        subprocess.run(
            ["make", "flight_server"],
            cwd=PROJECT_ROOT,
            check=True,
            stdout=subprocess.DEVNULL,
        )

    def __init__(self, semantics: str = "at-most-once", drop_first_reply: bool = False) -> None:
        self.port = reserve_udp_port()
        command = [
            str(self.binary),
            "--host",
            "127.0.0.1",
            "--port",
            str(self.port),
            "--semantics",
            semantics,
        ]
        if drop_first_reply:
            command.append("--drop-first-reply")
        self.process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

    def __enter__(self) -> "RunningCppServer":
        # Give the freshly spawned native process time to bind its UDP socket.
        time.sleep(0.20)
        if self.process.poll() is not None:
            error = self.process.stderr.read() if self.process.stderr else ""
            if self.process.stderr:
                self.process.stderr.close()
            raise RuntimeError(f"C++ server failed to start: {error}")
        return self

    def __exit__(self, *_: object) -> None:
        self.process.terminate()
        try:
            self.process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=1.0)
        if self.process.stderr:
            self.process.stderr.close()


def make_client(server: RunningCppServer, semantics: str = "at-most-once") -> ReliableFlightClient:
    return ReliableFlightClient(
        "127.0.0.1",
        server.port,
        semantics=semantics,
        timeout=0.15,
        retries=3,
    )


class ProtocolTests(unittest.TestCase):
    def test_flight_binary_round_trip_supports_variable_length_utf8(self) -> None:
        original = Flight(42, "新加坡", "München", 7, 5, 99.25, 8)
        decoded, offset = Flight.from_bytes(original.to_bytes())
        self.assertEqual(decoded, original)
        self.assertEqual(offset, len(original.to_bytes()))

    def test_request_round_trip_and_malformed_length(self) -> None:
        payload = encode_request_payload(
            Operation.SEARCH_FLIGHTS,
            {"source": "Singapore", "destination": "Tokyo"},
        )
        data = encode_message(MessageKind.REQUEST, Operation.SEARCH_FLIGHTS, 7, payload)
        message = decode_message(data)
        self.assertEqual(message.request_id, 7)
        with self.assertRaises(ProtocolError):
            decode_message(data[:-1])


class CrossLanguageServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        RunningCppServer.build()

    def test_python_client_uses_all_six_cpp_server_services(self) -> None:
        with RunningCppServer() as server, make_client(server) as client:
            self.assertEqual(
                client.search_flights("singapore", "TOKYO"), [1001, 1002]
            )
            self.assertEqual(client.get_flight(1001).departure_time, "08:30")

            reservation = client.reserve_seats(1001, 2)
            self.assertEqual(reservation["seats"], 38)

            price = client.set_price(1001, 499.50)
            self.assertEqual(price["price"], 499.50)
            client.set_price(1001, 499.50)
            self.assertEqual(client.get_flight(1001).price, 499.50)

            added = client.add_seats(1001, 4)
            self.assertEqual(added["seats"], 42)

            with self.assertRaises(RemoteError):
                client.get_flight(9999)
            with self.assertRaises(RemoteError):
                client.reserve_seats(1001, 10_000)

    def test_cpp_server_callback_reaches_python_monitor_client(self) -> None:
        with RunningCppServer() as server:
            monitor_client = make_client(server)
            booking_client = make_client(server)
            received: list[tuple[int, int]] = []

            monitor_thread = threading.Thread(
                target=lambda: monitor_client.monitor_seats(
                    1001,
                    0.45,
                    lambda flight_id, seats: received.append((flight_id, seats)),
                )
            )
            monitor_thread.start()
            time.sleep(0.08)
            booking_client.reserve_seats(1001, 1)
            monitor_thread.join(timeout=1.0)
            monitor_client.close()
            booking_client.close()

            self.assertFalse(monitor_thread.is_alive())
            self.assertIn((1001, 39), received)

    def test_at_least_once_reexecutes_non_idempotent_cpp_operation(self) -> None:
        with RunningCppServer(
            semantics="at-least-once", drop_first_reply=True
        ) as server, make_client(server, "at-least-once") as client:
            reply = client.add_seats(1001, 3)
            self.assertEqual(reply["seats"], 46)

    def test_at_most_once_cpp_server_returns_cached_result(self) -> None:
        with RunningCppServer(
            semantics="at-most-once", drop_first_reply=True
        ) as server, make_client(server, "at-most-once") as client:
            reply = client.add_seats(1001, 3)
            self.assertEqual(reply["seats"], 43)


if __name__ == "__main__":
    unittest.main(verbosity=2)
