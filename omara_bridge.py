#!/usr/bin/env python3
"""
tcp_omara_ble_bridge_clean.py

Clean TCP-to-BLE bridge for mGBA Pokemon Yellow scent packets.

Expected Lua behavior:
    Lua sends exactly one packet format over TCP:
        a 27-byte binary packet.

Python behavior:
    - listens for mGBA TCP packets
    - resynchronizes the TCP byte stream on sync byte 0xA5
    - validates XOR checksum
    - decodes map/item/player/scent data
    - adds all human-readable names in Python
    - optionally writes a compact payload to BLE

Lua -> Python packet, 27 bytes:
    byte 0      sync = 0xA5
    byte 1      type: 0 none/off, 1 nearest ungrabbed hidden item
    byte 2      distance, or 255 when none
    byte 3      hidden item index, or 255 when none
    byte 4      map id
    byte 5      player x
    byte 6      player y
    byte 7      item x, or 0 when none
    byte 8      item y, or 0 when none
    byte 9      scent multiplier percent, 0-100
    bytes 10-25 16 scent outputs in SCENTS order, 0-100
    byte 26     checksum = XOR of bytes 1..25, excluding sync

Default BLE payload:
    20 bytes:
        ASCII "OMS1" + 16 scent bytes

Install for real BLE:
    pip install bleak

Examples:
    No BLE, readable debug:
        python tcp_omara_ble_bridge_clean.py --no-ble --human-readable --print-payload

    Real BLE:
        python tcp_omara_ble_bridge_clean.py --ble-name omara --human-readable

    Send original 27-byte packet over BLE:
        python tcp_omara_ble_bridge_clean.py --ble-name omara --ble-payload raw27

Because apparently all of this is what it takes to make a Game Boy smell like Potion.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys
from dataclasses import dataclass
from typing import Any, Iterable, Optional, Protocol


SYNC = 0xA5
PACKET_LEN = 27

DEFAULT_TCP_HOST = "127.0.0.1"
DEFAULT_TCP_PORT = 8765

# From the Omara / ION BLE reference write characteristic.
DEFAULT_WRITE_CHARACTERISTIC_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"

SCENTS: tuple[str, ...] = (
    "Marine",
    "Petrichor",
    "Kindred",
    "Beach",
    "Floral",
    "Sweet",
    "Barnyard",
    "Winter",
    "Evergreen",
    "Terra Silva",
    "Citrus",
    "Desert",
    "Savory Spice",
    "Timber",
    "Smoky",
    "Machina",
)

MAP_NAMES: dict[int, str] = {
    0x01: "VIRIDIAN_CITY",
    0x03: "CERULEAN_CITY",
    0x05: "VERMILION_CITY",
    0x06: "CELADON_CITY",
    0x0F: "ROUTE_4",
    0x14: "ROUTE_9",
    0x15: "ROUTE_10",
    0x16: "ROUTE_11",
    0x17: "ROUTE_12",
    0x18: "ROUTE_13",
    0x1C: "ROUTE_17",
    0x22: "ROUTE_23",
    0x24: "ROUTE_25",
    0x33: "VIRIDIAN_FOREST",
    0x3D: "MT_MOON_B2F",
    0x53: "POWER_PLANT",
    0x64: "SS_ANNE_KITCHEN",
    0x68: "SS_ANNE_B1F_ROOMS",
    0x6F: "UNUSED_MAP_6F",
    0x77: "UNDERGROUND_PATH_NORTH_SOUTH",
    0x79: "UNDERGROUND_PATH_WEST_EAST",
    0x92: "POKEMON_TOWER_5F",
    0x9C: "SAFARI_ZONE_GATE",
    0xA0: "SEAFOAM_ISLANDS_B2F",
    0xA1: "SEAFOAM_ISLANDS_B3F",
    0xA2: "SEAFOAM_ISLANDS_B4F",
    0xA5: "POKEMON_MANSION_1F",
    0xB0: "COPYCATS_HOUSE_2F",
    0xC2: "VICTORY_ROAD_2F",
    0xC7: "ROCKET_HIDEOUT_B1F",
    0xC9: "ROCKET_HIDEOUT_B3F",
    0xCA: "ROCKET_HIDEOUT_B4F",
    0xD2: "SILPH_CO_5F",
    0xD7: "POKEMON_MANSION_3F",
    0xD8: "POKEMON_MANSION_B1F",
    0xDB: "SAFARI_ZONE_WEST",
    0xE2: "CERULEAN_CAVE_2F",
    0xE3: "CERULEAN_CAVE_B1F",
    0xE4: "CERULEAN_CAVE_1F",
    0xE9: "SILPH_CO_9F",
}


@dataclass(frozen=True)
class HiddenItem:
    index: int
    map_id: int
    x: int
    y: int
    name: str


HIDDEN_ITEMS: tuple[HiddenItem, ...] = (
    HiddenItem(0, 0xD2, 12, 3, "hidden item"),
    HiddenItem(1, 0xE9, 2, 15, "hidden item"),
    HiddenItem(2, 0xD7, 1, 9, "hidden item"),
    HiddenItem(3, 0xD8, 1, 9, "hidden item"),
    HiddenItem(4, 0xDB, 6, 5, "hidden item"),
    HiddenItem(5, 0xE2, 16, 13, "hidden item"),
    HiddenItem(6, 0xE3, 8, 14, "hidden item"),
    HiddenItem(7, 0x6F, 14, 11, "unused-map hidden item"),
    HiddenItem(8, 0xA0, 15, 15, "hidden item"),
    HiddenItem(9, 0xA1, 9, 16, "hidden item"),
    HiddenItem(10, 0xA2, 25, 17, "hidden item"),
    HiddenItem(11, 0x33, 1, 18, "Antidote"),
    HiddenItem(12, 0x33, 16, 42, "Potion"),
    HiddenItem(13, 0x3D, 18, 12, "hidden item"),
    HiddenItem(14, 0x3D, 33, 9, "hidden item"),
    HiddenItem(15, 0x68, 3, 1, "hidden item"),
    HiddenItem(16, 0x64, 13, 9, "hidden item"),
    HiddenItem(17, 0x77, 3, 4, "hidden item"),
    HiddenItem(18, 0x77, 4, 34, "hidden item"),
    HiddenItem(19, 0x79, 12, 2, "hidden item"),
    HiddenItem(20, 0x79, 21, 5, "hidden item"),
    HiddenItem(21, 0xC7, 21, 15, "hidden item"),
    HiddenItem(22, 0xC9, 27, 17, "hidden item"),
    HiddenItem(23, 0xCA, 25, 1, "hidden item"),
    HiddenItem(24, 0x15, 9, 17, "Super Potion"),
    HiddenItem(25, 0x15, 16, 53, "Max Ether"),
    HiddenItem(26, 0x53, 17, 16, "hidden item"),
    HiddenItem(27, 0x53, 12, 1, "hidden item"),
    HiddenItem(28, 0x16, 48, 5, "Escape Rope"),
    HiddenItem(29, 0x17, 2, 63, "Hyper Potion"),
    HiddenItem(30, 0x18, 1, 14, "hidden item"),
    HiddenItem(31, 0x18, 16, 13, "hidden item"),
    HiddenItem(32, 0x1C, 15, 14, "hidden item"),
    HiddenItem(33, 0x1C, 8, 45, "hidden item"),
    HiddenItem(34, 0x1C, 17, 72, "hidden item"),
    HiddenItem(35, 0x1C, 4, 91, "hidden item"),
    HiddenItem(36, 0x1C, 8, 121, "hidden item"),
    HiddenItem(37, 0x22, 9, 44, "hidden item"),
    HiddenItem(38, 0x22, 19, 70, "hidden item"),
    HiddenItem(39, 0x22, 8, 90, "hidden item"),
    HiddenItem(40, 0xC2, 5, 2, "hidden item"),
    HiddenItem(41, 0xC2, 26, 7, "hidden item"),
    HiddenItem(42, 0x24, 38, 3, "Ether"),
    HiddenItem(43, 0x24, 10, 1, "Elixir"),
    HiddenItem(44, 0x0F, 40, 3, "Great Ball"),
    HiddenItem(45, 0x14, 14, 7, "Ether"),
    HiddenItem(46, 0xB0, 1, 1, "hidden item"),
    HiddenItem(47, 0x01, 14, 4, "Potion"),
    HiddenItem(48, 0x03, 15, 8, "Rare Candy"),
    HiddenItem(49, 0xE4, 18, 7, "hidden item"),
    HiddenItem(50, 0x92, 4, 12, "hidden item"),
    HiddenItem(51, 0x05, 14, 11, "hidden item"),
    HiddenItem(52, 0x06, 48, 15, "hidden item"),
    HiddenItem(53, 0x9C, 10, 1, "inaccessible hidden item"),
    HiddenItem(54, 0xA5, 8, 16, "hidden item"),
)

HIDDEN_ITEM_BY_INDEX: dict[int, HiddenItem] = {
    item.index: item for item in HIDDEN_ITEMS
}


@dataclass(frozen=True)
class DecodedPacket:
    raw: bytes
    typ: int
    distance: int
    hidden_index: int
    map_id: int
    player_x: int
    player_y: int
    item_x: int
    item_y: int
    multiplier: int
    scents: tuple[int, ...]
    checksum: int

    @classmethod
    def parse(cls, raw: bytes) -> "DecodedPacket":
        if len(raw) != PACKET_LEN:
            raise ValueError(f"packet length {len(raw)} != {PACKET_LEN}")
        if raw[0] != SYNC:
            raise ValueError(f"bad sync byte 0x{raw[0]:02X}")

        expected_checksum = xor_bytes(raw[1:26])
        actual_checksum = raw[26]
        if actual_checksum != expected_checksum:
            raise ValueError(
                f"bad checksum expected=0x{expected_checksum:02X} got=0x{actual_checksum:02X}"
            )

        scents = tuple(raw[10:26])
        if len(scents) != len(SCENTS):
            raise ValueError(f"expected {len(SCENTS)} scent bytes, got {len(scents)}")

        return cls(
            raw=raw,
            typ=raw[1],
            distance=raw[2],
            hidden_index=raw[3],
            map_id=raw[4],
            player_x=raw[5],
            player_y=raw[6],
            item_x=raw[7],
            item_y=raw[8],
            multiplier=raw[9],
            scents=scents,
            checksum=actual_checksum,
        )

    @property
    def active(self) -> bool:
        return self.typ != 0 and self.distance != 0xFF and self.hidden_index != 0xFF

    @property
    def map_name(self) -> str:
        return MAP_NAMES.get(self.map_id, "UNKNOWN")

    @property
    def item(self) -> Optional[HiddenItem]:
        if not self.active:
            return None
        return HIDDEN_ITEM_BY_INDEX.get(self.hidden_index)

    @property
    def item_name(self) -> str:
        if not self.active:
            return "none"
        item = self.item
        if item is None:
            return "hidden item"
        return item.name

    @property
    def distance_label(self) -> str:
        if not self.active:
            return "off"
        if self.distance == 0:
            return "direct"
        if self.distance <= 2:
            return "near"
        if self.distance <= 5:
            return "medium"
        if self.distance <= 7:
            return "faint"
        return "far / off"

    def scent_pairs(self) -> tuple[tuple[str, int], ...]:
        return tuple(zip(SCENTS, self.scents))

    def nonzero_scent_pairs(self) -> tuple[tuple[str, int], ...]:
        return tuple((name, value) for name, value in self.scent_pairs() if value > 0)

    def metadata_warnings(self) -> list[str]:
        if not self.active or self.item is None:
            return []

        warnings: list[str] = []
        if self.item.map_id != self.map_id:
            warnings.append(
                f"item #{self.hidden_index} table map=0x{self.item.map_id:02X}, packet map=0x{self.map_id:02X}"
            )
        if self.item.x != self.item_x or self.item.y != self.item_y:
            warnings.append(
                f"item #{self.hidden_index} table pos=({self.item.x},{self.item.y}), "
                f"packet pos=({self.item_x},{self.item_y})"
            )
        return warnings


def xor_bytes(values: Iterable[int]) -> int:
    out = 0
    for value in values:
        out ^= value
    return out & 0xFF


def hex_bytes(data: bytes) -> str:
    return data.hex(" ")


def extract_raw_packets(buffer: bytearray) -> Iterable[bytes]:
    """
    Extract raw 27-byte packets from a TCP byte stream.

    On checksum failure, this drops one byte and keeps searching. That is better
    than rage-quitting the connection because one packet got framed badly, a
    bold concept previous software apparently had to discover the hard way.
    """
    while True:
        try:
            sync_index = buffer.index(SYNC)
        except ValueError:
            buffer.clear()
            return

        if sync_index:
            del buffer[:sync_index]

        if len(buffer) < PACKET_LEN:
            return

        raw = bytes(buffer[:PACKET_LEN])

        try:
            DecodedPacket.parse(raw)
        except ValueError:
            # Do not delete all 27 bytes. The next byte might begin a valid packet.
            del buffer[0]
            yield raw
            continue

        del buffer[:PACKET_LEN]
        yield raw


def build_ble_payload(packet: DecodedPacket, mode: str) -> bytes:
    if mode == "omara-scent":
        return b"OMS1" + bytes(packet.scents)

    if mode == "omara-scent-checksum":
        body = b"OMS1" + bytes(packet.scents)
        return body + bytes([xor_bytes(body)])

    if mode == "raw27":
        return packet.raw

    if mode == "human":
        return (format_one_line(packet) + "\n").encode("utf-8")

    raise ValueError(f"unknown BLE payload mode: {mode}")


def format_one_line(packet: DecodedPacket) -> str:
    if not packet.active:
        return (
            f"NONE map={packet.map_name}/0x{packet.map_id:02X} "
            f"player=({packet.player_x},{packet.player_y}) "
            f"multiplier={packet.multiplier}% checksum=0x{packet.checksum:02X}"
        )

    nonzero = packet.nonzero_scent_pairs()
    scent_text = ", ".join(f"{name}={value}" for name, value in nonzero)
    if not scent_text:
        scent_text = "all=0"

    return (
        f"{packet.item_name} #{packet.hidden_index} "
        f"dist={packet.distance} {packet.distance_label} "
        f"map={packet.map_name}/0x{packet.map_id:02X} "
        f"player=({packet.player_x},{packet.player_y}) "
        f"item=({packet.item_x},{packet.item_y}) "
        f"multiplier={packet.multiplier}% "
        f"scents=[{scent_text}] "
        f"checksum=0x{packet.checksum:02X}"
    )


def print_packet(packet: DecodedPacket, *, human_readable: bool) -> None:
    if not human_readable:
        print(format_one_line(packet), flush=True)
        return

    print("-" * 72, flush=True)

    if packet.active:
        print(f"Target: {packet.item_name} #{packet.hidden_index} ({packet.distance_label})", flush=True)
        print(f"Distance: {packet.distance} tile(s)", flush=True)
        print(f"Item: ({packet.item_x}, {packet.item_y})", flush=True)
    else:
        print("Target: none", flush=True)
        print("Distance: none", flush=True)

    print(f"Map: {packet.map_name} / 0x{packet.map_id:02X}", flush=True)
    print(f"Player: ({packet.player_x}, {packet.player_y})", flush=True)
    print(f"Scent multiplier: {packet.multiplier}%", flush=True)

    print("Scent outputs:", flush=True)
    for name, value in packet.scent_pairs():
        marker = "*" if value > 0 else " "
        print(f"  {marker} {name:<13} {value:3d}", flush=True)

    print(f"Source: binary27; checksum=0x{packet.checksum:02X}", flush=True)

    for warning in packet.metadata_warnings():
        print(f"WARNING: {warning}", file=sys.stderr, flush=True)


class PayloadSink(Protocol):
    async def write(self, payload: bytes) -> None:
        ...

    async def close(self) -> None:
        ...


class DryRunSink:
    async def write(self, payload: bytes) -> None:
        return None

    async def close(self) -> None:
        return None


class BleSink:
    def __init__(
        self,
        *,
        ble_name: str,
        ble_address: Optional[str],
        characteristic_uuid: str,
        scan_timeout: float,
        connect_timeout: float,
        write_response: bool,
    ) -> None:
        self.ble_name = ble_name
        self.ble_address = ble_address
        self.characteristic_uuid = characteristic_uuid
        self.scan_timeout = scan_timeout
        self.connect_timeout = connect_timeout
        self.write_response = write_response
        self.client: Any = None

    async def connect(self) -> None:
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError as exc:
            raise RuntimeError("real BLE requires bleak. Install it with: pip install bleak") from exc

        if self.ble_address:
            print(f"Scanning for BLE address/id: {self.ble_address}", flush=True)
            device = await BleakScanner.find_device_by_address(
                self.ble_address,
                timeout=self.scan_timeout,
            )
        else:
            name_filter = self.ble_name.lower().strip()
            print(f"Scanning for BLE name containing {name_filter!r}", flush=True)

            def matches(device: Any, _advertisement_data: Any) -> bool:
                name = getattr(device, "name", None)
                return bool(name and name_filter in name.lower())

            device = await BleakScanner.find_device_by_filter(
                matches,
                timeout=self.scan_timeout,
            )

        if device is None:
            raise RuntimeError("BLE device not found")

        device_name = getattr(device, "name", None) or "<unnamed>"
        device_address = getattr(device, "address", None) or "<unknown>"
        print(f"Found BLE device: {device_name} [{device_address}]", flush=True)

        self.client = BleakClient(device, timeout=self.connect_timeout)
        await self.client.connect()

        if not self.client.is_connected:
            raise RuntimeError("BLE connect failed")

        print(f"BLE connected; write characteristic={self.characteristic_uuid}", flush=True)

    async def write(self, payload: bytes) -> None:
        if self.client is None or not self.client.is_connected:
            raise RuntimeError("BLE client is not connected")

        await self.client.write_gatt_char(
            self.characteristic_uuid,
            payload,
            response=self.write_response,
        )

    async def close(self) -> None:
        if self.client is not None:
            with contextlib.suppress(Exception):
                await self.client.disconnect()


@dataclass
class BridgeStats:
    valid_packets: int = 0
    invalid_packets: int = 0
    payloads_written: int = 0
    payloads_skipped: int = 0


async def handle_mgba_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    *,
    sink: PayloadSink,
    args: argparse.Namespace,
    stats: BridgeStats,
) -> None:
    peer = writer.get_extra_info("peername")
    print(f"mGBA connected from {peer}", flush=True)

    buffer = bytearray()
    last_payload: Optional[bytes] = None

    try:
        while True:
            chunk = await reader.read(4096)
            if not chunk:
                print("mGBA disconnected", flush=True)
                return

            buffer.extend(chunk)

            for raw in extract_raw_packets(buffer):
                try:
                    packet = DecodedPacket.parse(raw)
                except ValueError as exc:
                    stats.invalid_packets += 1
                    if args.print_invalid:
                        print(f"discard: {exc}; raw={hex_bytes(raw)}", file=sys.stderr, flush=True)
                    continue

                stats.valid_packets += 1
                payload = build_ble_payload(packet, args.ble_payload)

                if not args.quiet:
                    print_packet(packet, human_readable=args.human_readable)

                if args.suppress_duplicates and payload == last_payload:
                    stats.payloads_skipped += 1
                    if not args.quiet:
                        label = "DRY RUN" if args.no_ble else "BLE"
                        print(f"{label}: skipped unchanged payload; mode={args.ble_payload}", flush=True)
                    continue

                try:
                    await sink.write(payload)
                except Exception as exc:
                    print(f"BLE write failed: {exc}", file=sys.stderr, flush=True)
                    continue

                last_payload = payload
                stats.payloads_written += 1

                if not args.quiet:
                    label = "dry-run" if args.no_ble else "sent"
                    print(f"BLE: {label}; payload_mode={args.ble_payload}; bytes={len(payload)}", flush=True)
                    if args.print_payload:
                        if args.ble_payload == "human":
                            print(payload.decode("utf-8", errors="replace").rstrip("\n"), flush=True)
                        else:
                            print(f"Payload: {hex_bytes(payload)}", flush=True)

    finally:
        writer.close()
        await writer.wait_closed()


async def run_server(args: argparse.Namespace, sink: PayloadSink) -> None:
    stats = BridgeStats()

    async def client_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        await handle_mgba_client(reader, writer, sink=sink, args=args, stats=stats)

    server = await asyncio.start_server(client_handler, args.host, args.port)
    sockets = server.sockets or []
    bound = ", ".join(str(sock.getsockname()) for sock in sockets)

    print(f"Listening for mGBA TCP on {bound}", flush=True)
    print(f"Expected packet: {PACKET_LEN} bytes, sync=0x{SYNC:02X}", flush=True)
    print(f"BLE mode: {'dry-run' if args.no_ble else 'real'}", flush=True)
    print(f"BLE payload mode: {args.ble_payload}", flush=True)
    print("Start this before loading the Lua script in mGBA.", flush=True)

    try:
        async with server:
            await server.serve_forever()
    finally:
        print(
            "Stats: "
            f"valid={stats.valid_packets} "
            f"invalid={stats.invalid_packets} "
            f"written={stats.payloads_written} "
            f"skipped={stats.payloads_skipped}",
            flush=True,
        )


async def make_sink(args: argparse.Namespace) -> PayloadSink:
    if args.no_ble:
        print("BLE disabled: dry-run mode. No real BLE connection will be made.", flush=True)
        return DryRunSink()

    sink = BleSink(
        ble_name=args.ble_name,
        ble_address=args.ble_address,
        characteristic_uuid=args.characteristic_uuid,
        scan_timeout=args.scan_timeout,
        connect_timeout=args.connect_timeout,
        write_response=args.write_response,
    )
    await sink.connect()
    return sink


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Clean TCP-to-BLE bridge for mGBA Pokemon Yellow Omara scent packets"
    )

    parser.add_argument("--host", default=DEFAULT_TCP_HOST, help="TCP host/interface to listen on")
    parser.add_argument("--port", type=int, default=DEFAULT_TCP_PORT, help="TCP port to listen on")

    output = parser.add_argument_group("Output")
    output.add_argument("--human-readable", action="store_true", help="print expanded multi-line packet details")
    output.add_argument("--quiet", action="store_true", help="do not print decoded packets")
    output.add_argument("--print-payload", action="store_true", help="print BLE payload bytes")
    output.add_argument("--print-invalid", action="store_true", help="print invalid raw packets after failed parsing")

    ble = parser.add_argument_group("BLE")
    ble.add_argument("--no-ble", action="store_true", help="do not connect to BLE; dry-run only")
    ble.add_argument("--ble-name", default="omara", help="BLE device-name substring")
    ble.add_argument("--ble-address", default=None, help="specific BLE address/id")
    ble.add_argument("--characteristic-uuid", default=DEFAULT_WRITE_CHARACTERISTIC_UUID, help="BLE write characteristic UUID")
    ble.add_argument("--scan-timeout", type=float, default=15.0, help="BLE scan timeout seconds")
    ble.add_argument("--connect-timeout", type=float, default=30.0, help="BLE connect timeout seconds")
    ble.add_argument("--write-response", action="store_true", help="use BLE write-with-response")

    payload = parser.add_argument_group("Payload")
    payload.add_argument(
        "--ble-payload",
        choices=("omara-scent", "omara-scent-checksum", "raw27", "human"),
        default="omara-scent",
        help="payload sent to BLE",
    )
    payload.add_argument(
        "--send-duplicates",
        dest="suppress_duplicates",
        action="store_false",
        help="send identical consecutive payloads instead of suppressing them",
    )
    payload.set_defaults(suppress_duplicates=True)

    return parser


async def async_main(args: argparse.Namespace) -> int:
    if args.ble_payload == "human":
        print(
            "Note: --ble-payload human can exceed small BLE write sizes. "
            "Use omara-scent unless your receiver expects text.",
            file=sys.stderr,
            flush=True,
        )

    sink = await make_sink(args)
    try:
        await run_server(args, sink)
    finally:
        await sink.close()

    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        print("\nbye", flush=True)
        return 130
    except Exception as exc:
        print(f"fatal: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
