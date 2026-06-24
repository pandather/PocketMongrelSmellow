import argparse
import asyncio
import json
from bleak import BleakScanner, BleakClient
from bleak.exc import BleakError


IO_PROPS = {
    "read",
    "write",
    "write-without-response",
    "notify",
    "indicate",
}


async def probe_device(device, adv, connect_timeout, pair=False):
    name = adv.local_name or device.name or ""

    if not name:
        return None

    try:
        async with BleakClient(device, timeout=connect_timeout, pair=pair) as client:
            services = client.services

            usable_chars = []

            for service in services:
                for char in service.characteristics:
                    props = set(char.properties)

                    if props & IO_PROPS:
                        usable_chars.append({
                            "service_uuid": service.uuid,
                            "char_uuid": char.uuid,
                            "properties": sorted(props),
                        })

            if not usable_chars:
                return None

            return {
                "name": name,
                "address": device.address,
                "rssi": getattr(adv, "rssi", None),
                "characteristics": usable_chars,
            }

    except Exception:
        return None


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--connect-timeout", type=float, default=6.0)
    parser.add_argument("--name-contains", default="")
    parser.add_argument("--pair", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    found = await BleakScanner.discover(
        timeout=args.timeout,
        return_adv=True,
    )

    usable = []

    for _, item in found.items():
        device, adv = item
        name = adv.local_name or device.name or ""

        if args.name_contains and args.name_contains.lower() not in name.lower():
            continue

        result = await probe_device(
            device,
            adv,
            connect_timeout=args.connect_timeout,
            pair=args.pair,
        )

        if result:
            usable.append(result)

    if args.json:
        print(json.dumps(usable, indent=2))
    else:
        for dev in usable:
            print(dev["name"])


if __name__ == "__main__":
    asyncio.run(main())
