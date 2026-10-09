from __future__ import annotations

from dataclasses import dataclass

from common.message import BinaryReader, BinaryWriter


@dataclass(slots=True)
class Flight:
    flight_id: int
    source: str
    destination: str
    hour: int
    minute: int
    price: float
    seats: int

    def __post_init__(self) -> None:
        if not 0 <= self.hour <= 23 or not 0 <= self.minute <= 59:
            raise ValueError("departure time must be a valid 24-hour time")
        if self.price < 0:
            raise ValueError("price cannot be negative")
        if self.seats < 0:
            raise ValueError("seat availability cannot be negative")

    @property
    def departure_time(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"

    def __str__(self) -> str:
        return (
            f"Flight {self.flight_id}: {self.source} -> {self.destination}, "
            f"departure {self.departure_time}, fare ${self.price:.2f}, "
            f"{self.seats} seat(s) available"
        )

    def marshal(self, writer: BinaryWriter) -> None:
        writer.u32(self.flight_id)
        writer.string(self.source)
        writer.string(self.destination)
        writer.u8(self.hour)
        writer.u8(self.minute)
        writer.f64(self.price)
        writer.u32(self.seats)

    @classmethod
    def unmarshal(cls, reader: BinaryReader) -> "Flight":
        return cls(
            flight_id=reader.u32(),
            source=reader.string(),
            destination=reader.string(),
            hour=reader.u8(),
            minute=reader.u8(),
            price=reader.f64(),
            seats=reader.u32(),
        )

    def to_bytes(self) -> bytes:
        writer = BinaryWriter()
        self.marshal(writer)
        return writer.build()

    @classmethod
    def from_bytes(cls, data: bytes, offset: int = 0) -> tuple["Flight", int]:
        reader = BinaryReader(data, offset)
        value = cls.unmarshal(reader)
        return value, reader.offset


# Backward-compatible alias for the class name used in the starter code.
flight = Flight
