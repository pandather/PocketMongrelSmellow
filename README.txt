Smellow: Pokemon Yellow Omara Scent Bridge
==========================================

Smellow connects Pokemon Yellow running in mGBA to an Omara-compatible BLE scent device.

The mGBA Lua script reads the player position, current map, hidden item flags, and nearest ungrabbed hidden item. It computes 16 scent-channel outputs and sends a fixed binary packet over TCP.

The Python bridge receives that packet, validates it, prints readable debug output, and optionally forwards compact scent data to a real Omara device over Bluetooth Low Energy.

Yes, this is a Game Boy hidden-item smell bridge. Technology peaked and then wandered into the tall grass.


Repository layout
=================

.
├── requirements.txt
├── LICENSE
├── omara_bridge.py
├── smellow_mGBA_script.lua
└── .git/

Files:

requirements.txt
    Python dependencies. Should include bleak for real BLE mode.

LICENSE
    GNU GPL v3 license text.

omara_bridge.py
    Python bridge. Receives Lua packets, validates them, prints debug output,
    and optionally writes BLE payloads.

smellow_mGBA_script.lua
    mGBA Lua script. Reads Pokemon Yellow memory, computes scents, and sends TCP packets.

.git/
    Git repository metadata. Ignore it unless you enjoy poking the machinery.


License
=======

This project is licensed under the GNU General Public License version 3.

Use this SPDX identifier in source files:

    SPDX-License-Identifier: GPL-3.0-only

The full GPL v3 text should live in:

    LICENSE


Requirements
============

mGBA
----

Use an mGBA build with Lua scripting enabled and native socket support.

The Lua script expects mGBA's built-in socket object. It should not require LuaSocket.

Do not use:

    require("socket")

The script should use mGBA's native socket API directly.


Python
------

Python 3.10 or newer is recommended.

Install dependencies:

    pip install -r requirements.txt

For BLE mode, requirements.txt should include:

    bleak

Dry-run mode does not need BLE hardware.


Quick start
===========

1. Start the Python bridge first
--------------------------------

Dry-run mode, no BLE device needed:

    python omara_bridge.py --no-ble --human-readable --print-payload

The bridge should begin listening for mGBA TCP packets.


2. Load the Lua script in mGBA
------------------------------

In mGBA, load:

    smellow_mGBA_script.lua

The Lua script connects to the Python bridge and begins sending scent packets.


3. Test with real BLE
---------------------

After dry-run output looks correct:

    python omara_bridge.py --ble-name omara --human-readable --print-payload

If the device advertises under a different name:

    python omara_bridge.py --ble-name ion --human-readable --print-payload

If you know the BLE address or platform-specific device ID:

    python omara_bridge.py --ble-address XX:XX:XX:XX:XX:XX --human-readable


Architecture
============

Pokemon Yellow in mGBA
        |
        | Lua reads WRAM
        v
smellow_mGBA_script.lua
        |
        | TCP, 27-byte binary packet
        v
omara_bridge.py
        |
        | validate, decode, label, convert
        v
BLE write characteristic
        |
        | compact scent payload
        v
Omara device


What the Lua script does
========================

smellow_mGBA_script.lua reads Pokemon Yellow WRAM values including:

- current map
- player X/Y position
- hidden item flags
- nearest ungrabbed hidden item
- hidden item grabbed/ungrabbed state

It computes scent output for 16 scent channels, each from 0 to 100.

The Lua script should stay small and boring:

- read game state
- compute scent values
- send one binary packet over TCP

It should not handle Bluetooth. That is Python's problem, because one runtime suffering at a time is plenty.


Lua-to-Python packet format
===========================

Lua sends exactly one packet type:

    27-byte binary packet

Packet layout:

Byte    Meaning
----    -------
0       Sync byte, always 0xA5
1       Type: 0 = none/off, 1 = nearest ungrabbed hidden item
2       Distance, or 255 when none
3       Hidden item index, or 255 when none
4       Map ID
5       Player X
6       Player Y
7       Item X, or 0 when none
8       Item Y, or 0 when none
9       Scent multiplier percent, 0-100
10-25   16 scent channel values, each 0-100
26      XOR checksum of bytes 1-25

Checksum:

    checksum = byte[1] XOR byte[2] XOR ... XOR byte[25]

The sync byte 0xA5 is not included in the checksum.


Scent channel order
===================

The 16 scent values are sent in this exact order:

1.  Marine
2.  Petrichor
3.  Kindred
4.  Beach
5.  Floral
6.  Sweet
7.  Barnyard
8.  Winter
9.  Evergreen
10. Terra Silva
11. Citrus
12. Desert
13. Savory Spice
14. Timber
15. Smoky
16. Machina

The order matters. If the Omara-side receiver expects a different order, the wrong scent channels will activate, and then you get nonsense smells. Which is funny once, then immediately debugging.


Scent falloff
=============

The Lua script computes scent strength from Manhattan distance to the nearest ungrabbed hidden item.

Current falloff:

    distance 0 = 100% scent multiplier
    distance 8 or greater = 0% scent multiplier

Each item has a scent profile made from up to three scent components.

Example for Potion:

    Floral
    Sweet
    Citrus

Final scent output:

    scent_output = scent_ratio * distance_multiplier * 100

Each scent channel is clamped to an integer from 0 to 100.


Python bridge behavior
======================

omara_bridge.py is responsible for:

- listening for TCP packets from mGBA
- resynchronizing the byte stream on 0xA5
- validating packet checksum
- decoding map, player, item, distance, and scent values
- adding human-readable map names and item names
- printing debug output
- optionally connecting to BLE
- writing compact Omara payloads

Python owns names and labels. Lua only sends bytes.

This is deliberate. Lua should not become a tiny database wearing a trench coat.


Python bridge modes
===================

Dry-run mode
------------

Use this first:

    python omara_bridge.py --no-ble --human-readable --print-payload

Dry-run mode:

- does not connect to BLE
- validates packets
- prints decoded packet details
- prints the payload that would be sent to Omara


Real BLE mode
-------------

Use this after dry-run works:

    python omara_bridge.py --ble-name omara --human-readable --print-payload

The bridge scans for a BLE device whose advertised name contains the value passed to --ble-name.


Quiet mode
----------

    python omara_bridge.py --ble-name omara --quiet

Use this once everything works and you no longer need the terminal to narrate every tile step like a deeply committed tour guide.


BLE payload modes
=================

The bridge can send different payload formats to BLE.


omara-scent
-----------

Default mode.

    python omara_bridge.py --ble-name omara --ble-payload omara-scent

Payload:

    20 bytes total

Layout:

Bytes   Meaning
-----   -------
0-3     ASCII OMS1
4-19    16 scent channel values

Example:

    4f 4d 53 31 00 00 00 00 30 1a 00 00 00 00 0d 00 00 00 00 00

Decoded:

    OMS1
    Floral = 48
    Sweet = 26
    Citrus = 13
    all other scents = 0

This is the recommended mode if Omara expects compact scent data.


omara-scent-checksum
--------------------

    python omara_bridge.py --ble-name omara --ble-payload omara-scent-checksum

Payload:

    21 bytes total

Layout:

    OMS1 + 16 scent bytes + XOR checksum

Use this only if the Omara-side receiver expects a checksum on the compact scent packet.


raw27
-----

    python omara_bridge.py --ble-name omara --ble-payload raw27

Payload:

    27 bytes total

This sends the original Lua packet directly over BLE, including:

- map ID
- player position
- item position
- hidden item index
- distance
- scent multiplier
- 16 scent values
- checksum

Use this only if the Omara-side receiver wants the full game-state packet.


human
-----

    python omara_bridge.py --ble-name omara --ble-payload human

Sends a UTF-8 debug line over BLE.

This is mainly for testing. It can exceed small BLE write sizes. Use compact mode unless the receiver explicitly expects text.


Recommended commands
====================

Dry-run debug:

    python omara_bridge.py --no-ble --human-readable --print-payload

Real Omara BLE, compact payload:

    python omara_bridge.py --ble-name omara --ble-payload omara-scent

Real Omara BLE, verbose:

    python omara_bridge.py --ble-name omara --ble-payload omara-scent --human-readable --print-payload

Send full Lua packet over BLE:

    python omara_bridge.py --ble-name omara --ble-payload raw27 --human-readable --print-payload


Duplicate suppression
=====================

By default, the bridge does not resend identical consecutive BLE payloads.

This avoids spamming the BLE device with repeated "nothing changed" packets.

To force duplicate payloads to send:

    python omara_bridge.py --ble-name omara --send-duplicates


Expected dry-run output
=======================

Example near Viridian City's hidden Potion:

    Target: Potion #47 (near)
    Distance: 1 tile(s)
    Item: (14, 4)
    Map: VIRIDIAN_CITY / 0x01
    Player: (15, 4)
    Scent multiplier: 88%
    Scent outputs:
        Marine          0
        Petrichor       0
        Kindred         0
        Beach           0
      * Floral         48
      * Sweet          26
        Barnyard        0
        Winter          0
        Evergreen       0
        Terra Silva     0
      * Citrus         13
        Desert          0
        Savory Spice    0
        Timber          0
        Smoky           0
        Machina         0
    Source: binary27; checksum=0x50
    BLE: dry-run; payload_mode=omara-scent; bytes=20
    Payload: 4f 4d 53 31 00 00 00 00 30 1a 00 00 00 00 0d 00 00 00 00 00


Troubleshooting
===============

mGBA says socket is unavailable
-------------------------------

Use the version of smellow_mGBA_script.lua that uses mGBA's native socket API.

It should not call:

    require("socket")


Python never shows a connection
-------------------------------

Start Python first, then load the Lua script in mGBA.

The Lua script cannot connect to a TCP server that is not running. A cruel but consistent rule.


BLE device not found
--------------------

Try a broader device-name filter:

    python omara_bridge.py --ble-name ion

or:

    python omara_bridge.py --ble-name omara

If needed, use a direct address or platform-specific device ID:

    python omara_bridge.py --ble-address <address-or-id>


Payload ends with 00
--------------------

That is normal for omara-scent.

The final byte is the last scent channel, Machina, not a checksum. If Machina is zero, the payload ends in 00.

The Lua-to-Python 27-byte packet still has a real checksum at byte 26.


Checksum changes but compact payload does not
---------------------------------------------

That can happen.

The 27-byte Lua packet includes game-state fields such as player position and distance. The compact BLE payload includes only the 16 final scent values.

If the scent values do not change, the compact BLE payload does not change, even if the raw packet checksum changes.


Omara connects but does not react
---------------------------------

Check the payload mode.

Try compact mode first:

    python omara_bridge.py --ble-name omara --ble-payload omara-scent --human-readable --print-payload

If the receiver expects the full game-state packet, try:

    python omara_bridge.py --ble-name omara --ble-payload raw27 --human-readable --print-payload

Also confirm the BLE write characteristic UUID:

    6e400002-b5a3-f393-e0a9-e50e24dcca9e


Omara receiver notes
====================

If Omara expects compact mode, parse:

    OMS1 + 16 scent bytes

Validate:

- first four bytes are ASCII OMS1
- exactly 16 scent values follow
- each value is 0-100

Compact mode does not include:

- item names
- map names
- distance
- player position
- checksum

If the receiver needs that context, use:

    --ble-payload raw27


Development notes
=================

Keep responsibilities separated.

Lua should handle:

- reading WRAM
- hidden-item lookup
- grabbed flag lookup
- scent output computation
- TCP packet sending

Python should handle:

- packet validation
- stream resync
- map and item names
- readable output
- BLE connection
- BLE payload formatting

This split keeps the mGBA script small and keeps Python easier to test without launching the emulator.


Git notes
=========

Common commands:

Unstage files without losing local changes:

    git restore --staged .

or:

    git reset HEAD

Check status:

    git status

Commit:

    git add .
    git commit -m "Add Smellow mGBA Omara bridge"


License headers
===============

Recommended header for omara_bridge.py:

    # SPDX-License-Identifier: GPL-3.0-only

Recommended header for smellow_mGBA_script.lua:

    -- SPDX-License-Identifier: GPL-3.0-only


License
=======

Smellow is licensed under the GNU General Public License version 3.

See:

    LICENSE

SPDX identifier:

    GPL-3.0-only
