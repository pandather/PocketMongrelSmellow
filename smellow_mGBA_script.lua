-- mgba_yellow_scent_tcp_rewrite.lua
-- Pokemon Yellow hidden item scent transmitter for mGBA.
--
-- Clean rewrite:
--   - no LuaSocket require()
--   - uses mGBA's built-in global socket object
--   - reads map/player position
--   - checks hidden-item obtained flags
--   - finds nearest ungrabbed hidden item on current map
--   - computes 16 scent channels, 0-100
--   - sends either a 27-byte binary packet or a readable text line over TCP
--   - draws a small debug buffer in mGBA
--
-- Start tcp_omara_ble_bridge.py first, then load this script.
-- mGBA's socket.connect() is blocking. Yes, really. Humanity persists.

------------------------------------------------------------
-- User settings
------------------------------------------------------------

local CFG = {
  tcp_enabled = true,
  tcp_host = "127.0.0.1",
  tcp_port = 8765,

  -- "binary" = fixed 27-byte packet for tcp_omara_ble_bridge.py
  -- "text"   = readable one-line packet for terminal debugging
  packet_mode = "binary",

  -- Only send when the generated payload changed.
  send_only_on_change = true,

  -- Render/send cadence. 15 frames ~= 4 times/sec at 60 FPS.
  update_frames = 15,

  -- Retry TCP connection about once per second at 60 FPS.
  reconnect_frames = 60,

  buffer_name = "Yellow Scent Debug",
}

------------------------------------------------------------
-- Game data
------------------------------------------------------------

local ADDR = {
  wCurMap = 0xD35D,
  wYCoord = 0xD360,
  wXCoord = 0xD361,

  -- Hidden item flag base:
  -- index 47 is Viridian City Potion.
  -- index 47 changed $D6F4 bit 7, so base = $D6F4 - floor(47 / 8) = $D6EF.
  wObtainedHiddenItemsFlags = 0xD6EF,
}

local MAP = {
  VIRIDIAN_CITY = 0x01,
  CERULEAN_CITY = 0x03,
  VERMILION_CITY = 0x05,
  CELADON_CITY = 0x06,

  ROUTE_4 = 0x0F,
  ROUTE_9 = 0x14,
  ROUTE_10 = 0x15,
  ROUTE_11 = 0x16,
  ROUTE_12 = 0x17,
  ROUTE_13 = 0x18,
  ROUTE_17 = 0x1C,
  ROUTE_23 = 0x22,
  ROUTE_25 = 0x24,

  VIRIDIAN_FOREST = 0x33,
  MT_MOON_B2F = 0x3D,
  POWER_PLANT = 0x53,

  SS_ANNE_KITCHEN = 0x64,
  SS_ANNE_B1F_ROOMS = 0x68,

  UNUSED_MAP_6F = 0x6F,

  UNDERGROUND_PATH_NORTH_SOUTH = 0x77,
  UNDERGROUND_PATH_WEST_EAST = 0x79,

  POKEMON_TOWER_5F = 0x92,
  SAFARI_ZONE_GATE = 0x9C,

  SEAFOAM_ISLANDS_B2F = 0xA0,
  SEAFOAM_ISLANDS_B3F = 0xA1,
  SEAFOAM_ISLANDS_B4F = 0xA2,

  POKEMON_MANSION_1F = 0xA5,
  COPYCATS_HOUSE_2F = 0xB0,

  VICTORY_ROAD_2F = 0xC2,

  ROCKET_HIDEOUT_B1F = 0xC7,
  ROCKET_HIDEOUT_B3F = 0xC9,
  ROCKET_HIDEOUT_B4F = 0xCA,

  SILPH_CO_5F = 0xD2,

  POKEMON_MANSION_3F = 0xD7,
  POKEMON_MANSION_B1F = 0xD8,

  SAFARI_ZONE_WEST = 0xDB,

  CERULEAN_CAVE_2F = 0xE2,
  CERULEAN_CAVE_B1F = 0xE3,
  CERULEAN_CAVE_1F = 0xE4,

  SILPH_CO_9F = 0xE9,
}

local MAP_NAME = {}
for name, id in pairs(MAP) do
  MAP_NAME[id] = name
end

-- Hidden item indices are zero-based and correspond to hidden item flag bits.
local HIDDEN_ITEMS = {
  {map=MAP.SILPH_CO_5F, x=12, y=3, name="hidden item", index=0},
  {map=MAP.SILPH_CO_9F, x=2, y=15, name="hidden item", index=1},

  {map=MAP.POKEMON_MANSION_3F, x=1, y=9, name="hidden item", index=2},
  {map=MAP.POKEMON_MANSION_B1F, x=1, y=9, name="hidden item", index=3},

  {map=MAP.SAFARI_ZONE_WEST, x=6, y=5, name="hidden item", index=4},

  {map=MAP.CERULEAN_CAVE_2F, x=16, y=13, name="hidden item", index=5},
  {map=MAP.CERULEAN_CAVE_B1F, x=8, y=14, name="hidden item", index=6},

  {map=MAP.UNUSED_MAP_6F, x=14, y=11, name="unused-map hidden item", index=7},

  {map=MAP.SEAFOAM_ISLANDS_B2F, x=15, y=15, name="hidden item", index=8},
  {map=MAP.SEAFOAM_ISLANDS_B3F, x=9, y=16, name="hidden item", index=9},
  {map=MAP.SEAFOAM_ISLANDS_B4F, x=25, y=17, name="hidden item", index=10},

  {map=MAP.VIRIDIAN_FOREST, x=1, y=18, name="Antidote", index=11},
  {map=MAP.VIRIDIAN_FOREST, x=16, y=42, name="Potion", index=12},

  {map=MAP.MT_MOON_B2F, x=18, y=12, name="hidden item", index=13},
  {map=MAP.MT_MOON_B2F, x=33, y=9, name="hidden item", index=14},

  {map=MAP.SS_ANNE_B1F_ROOMS, x=3, y=1, name="hidden item", index=15},
  {map=MAP.SS_ANNE_KITCHEN, x=13, y=9, name="hidden item", index=16},

  {map=MAP.UNDERGROUND_PATH_NORTH_SOUTH, x=3, y=4, name="hidden item", index=17},
  {map=MAP.UNDERGROUND_PATH_NORTH_SOUTH, x=4, y=34, name="hidden item", index=18},

  {map=MAP.UNDERGROUND_PATH_WEST_EAST, x=12, y=2, name="hidden item", index=19},
  {map=MAP.UNDERGROUND_PATH_WEST_EAST, x=21, y=5, name="hidden item", index=20},

  {map=MAP.ROCKET_HIDEOUT_B1F, x=21, y=15, name="hidden item", index=21},
  {map=MAP.ROCKET_HIDEOUT_B3F, x=27, y=17, name="hidden item", index=22},
  {map=MAP.ROCKET_HIDEOUT_B4F, x=25, y=1, name="hidden item", index=23},

  {map=MAP.ROUTE_10, x=9, y=17, name="Super Potion", index=24},
  {map=MAP.ROUTE_10, x=16, y=53, name="Max Ether", index=25},

  {map=MAP.POWER_PLANT, x=17, y=16, name="hidden item", index=26},
  {map=MAP.POWER_PLANT, x=12, y=1, name="hidden item", index=27},

  {map=MAP.ROUTE_11, x=48, y=5, name="Escape Rope", index=28},
  {map=MAP.ROUTE_12, x=2, y=63, name="Hyper Potion", index=29},

  {map=MAP.ROUTE_13, x=1, y=14, name="hidden item", index=30},
  {map=MAP.ROUTE_13, x=16, y=13, name="hidden item", index=31},

  {map=MAP.ROUTE_17, x=15, y=14, name="hidden item", index=32},
  {map=MAP.ROUTE_17, x=8, y=45, name="hidden item", index=33},
  {map=MAP.ROUTE_17, x=17, y=72, name="hidden item", index=34},
  {map=MAP.ROUTE_17, x=4, y=91, name="hidden item", index=35},
  {map=MAP.ROUTE_17, x=8, y=121, name="hidden item", index=36},

  {map=MAP.ROUTE_23, x=9, y=44, name="hidden item", index=37},
  {map=MAP.ROUTE_23, x=19, y=70, name="hidden item", index=38},
  {map=MAP.ROUTE_23, x=8, y=90, name="hidden item", index=39},

  {map=MAP.VICTORY_ROAD_2F, x=5, y=2, name="hidden item", index=40},
  {map=MAP.VICTORY_ROAD_2F, x=26, y=7, name="hidden item", index=41},

  {map=MAP.ROUTE_25, x=38, y=3, name="Ether", index=42},
  {map=MAP.ROUTE_25, x=10, y=1, name="Elixir", index=43},

  {map=MAP.ROUTE_4, x=40, y=3, name="Great Ball", index=44},
  {map=MAP.ROUTE_9, x=14, y=7, name="Ether", index=45},

  {map=MAP.COPYCATS_HOUSE_2F, x=1, y=1, name="hidden item", index=46},

  {map=MAP.VIRIDIAN_CITY, x=14, y=4, name="Potion", index=47},
  {map=MAP.CERULEAN_CITY, x=15, y=8, name="Rare Candy", index=48},

  {map=MAP.CERULEAN_CAVE_1F, x=18, y=7, name="hidden item", index=49},
  {map=MAP.POKEMON_TOWER_5F, x=4, y=12, name="hidden item", index=50},

  {map=MAP.VERMILION_CITY, x=14, y=11, name="hidden item", index=51},
  {map=MAP.CELADON_CITY, x=48, y=15, name="hidden item", index=52},

  {map=MAP.SAFARI_ZONE_GATE, x=10, y=1, name="inaccessible hidden item", index=53},

  {map=MAP.POKEMON_MANSION_1F, x=8, y=16, name="hidden item", index=54},
}

local SCENTS = {
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
}

local SCENT_MAX_DISTANCE = 8

local ITEM_SCENT_PROFILE_BY_NAME = {
  ["Potion"] = {
    {scent="Floral", ratio=0.55},
    {scent="Sweet", ratio=0.30},
    {scent="Citrus", ratio=0.15},
  },
  ["Super Potion"] = {
    {scent="Floral", ratio=0.45},
    {scent="Sweet", ratio=0.25},
    {scent="Evergreen", ratio=0.30},
  },
  ["Hyper Potion"] = {
    {scent="Floral", ratio=0.35},
    {scent="Evergreen", ratio=0.40},
    {scent="Citrus", ratio=0.25},
  },
  ["Antidote"] = {
    {scent="Evergreen", ratio=0.45},
    {scent="Citrus", ratio=0.35},
    {scent="Savory Spice", ratio=0.20},
  },
  ["Rare Candy"] = {
    {scent="Sweet", ratio=0.70},
    {scent="Citrus", ratio=0.20},
    {scent="Kindred", ratio=0.10},
  },
  ["Ether"] = {
    {scent="Machina", ratio=0.50},
    {scent="Winter", ratio=0.30},
    {scent="Marine", ratio=0.20},
  },
  ["Max Ether"] = {
    {scent="Machina", ratio=0.55},
    {scent="Winter", ratio=0.30},
    {scent="Petrichor", ratio=0.15},
  },
  ["Elixir"] = {
    {scent="Sweet", ratio=0.35},
    {scent="Machina", ratio=0.35},
    {scent="Winter", ratio=0.30},
  },
  ["Escape Rope"] = {
    {scent="Timber", ratio=0.45},
    {scent="Terra Silva", ratio=0.35},
    {scent="Smoky", ratio=0.20},
  },
  ["Great Ball"] = {
    {scent="Machina", ratio=0.50},
    {scent="Marine", ratio=0.30},
    {scent="Citrus", ratio=0.20},
  },
  ["inaccessible hidden item"] = {
    {scent="Smoky", ratio=0.50},
    {scent="Machina", ratio=0.30},
    {scent="Desert", ratio=0.20},
  },
  ["unused-map hidden item"] = {
    {scent="Machina", ratio=0.50},
    {scent="Smoky", ratio=0.30},
    {scent="Winter", ratio=0.20},
  },
  ["hidden item"] = {
    {scent="Kindred", ratio=0.40},
    {scent="Terra Silva", ratio=0.35},
    {scent="Machina", ratio=0.25},
  },
}

local DEFAULT_SCENT_PROFILE = {
  {scent="Kindred", ratio=0.40},
  {scent="Petrichor", ratio=0.30},
  {scent="Terra Silva", ratio=0.30},
}

------------------------------------------------------------
-- Small utilities
------------------------------------------------------------

local function log(message)
  if console ~= nil and console.log ~= nil then
    console:log(tostring(message))
  end
end

local function read8(addr)
  local value = emu:read8(addr)
  if value == nil then
    return 0
  end
  return value
end

local function clamp(n, lo, hi)
  if n < lo then
    return lo
  end
  if n > hi then
    return hi
  end
  return n
end

local function round(n)
  return math.floor(n + 0.5)
end

local function abs(n)
  if n < 0 then
    return -n
  end
  return n
end

local function distance(ax, ay, bx, by)
  return abs(ax - bx) + abs(ay - by)
end

local function hasBit(byteValue, bitIndex)
  -- Lua 5.4 has bit operators, but this script intentionally avoids them.
  local divisor = 2 ^ bitIndex
  return math.floor(byteValue / divisor) % 2 == 1
end

local function xorByte(a, b)
  -- XOR for one byte without Lua bitwise operators.
  local out = 0
  local place = 1

  for _ = 0, 7 do
    local abit = math.floor(a / place) % 2
    local bbit = math.floor(b / place) % 2

    if abit ~= bbit then
      out = out + place
    end

    place = place * 2
  end

  return out
end

local function bytesToString(bytes)
  local chars = {}

  for i = 1, #bytes do
    chars[i] = string.char(clamp(bytes[i] or 0, 0, 255))
  end

  return table.concat(chars)
end

local function safeName(s)
  s = tostring(s or "none")
  s = string.gsub(s, "%s+", "_")
  s = string.gsub(s, "[^%w_%-]", "")
  return s
end

------------------------------------------------------------
-- Hidden item logic
------------------------------------------------------------

local function getHiddenItemFlag(index)
  local byteOffset = math.floor(index / 8)
  local bitIndex = index % 8
  local addr = ADDR.wObtainedHiddenItemsFlags + byteOffset
  local byteValue = read8(addr)

  return {
    addr = addr,
    byte = byteValue,
    bit = bitIndex,
    grabbed = hasBit(byteValue, bitIndex),
  }
end

local function readPlayer()
  return {
    map = read8(ADDR.wCurMap),
    x = read8(ADDR.wXCoord),
    y = read8(ADDR.wYCoord),
  }
end

local function nearestUngrabbedItem(player)
  local best = nil
  local bestDistance = 999999

  for _, item in ipairs(HIDDEN_ITEMS) do
    if item.map == player.map then
      local flag = getHiddenItemFlag(item.index)
      if not flag.grabbed then
        local d = distance(player.x, player.y, item.x, item.y)
        if d < bestDistance then
          best = item
          bestDistance = d
        end
      end
    end
  end

  return best, bestDistance
end

------------------------------------------------------------
-- Scent mixer
------------------------------------------------------------

local function newScentOutput()
  local output = {}

  for _, name in ipairs(SCENTS) do
    output[name] = 0
  end

  return output
end

local function scentMultiplierForDistance(d)
  if d == nil then
    return 0
  end
  if d <= 0 then
    return 1
  end
  if d >= SCENT_MAX_DISTANCE then
    return 0
  end

  return (SCENT_MAX_DISTANCE - d) / SCENT_MAX_DISTANCE
end

local function scentProfileFor(item)
  if item == nil then
    return nil
  end
  return ITEM_SCENT_PROFILE_BY_NAME[item.name] or DEFAULT_SCENT_PROFILE
end

local function computeScent(item, d)
  local output = newScentOutput()
  local mult = scentMultiplierForDistance(d)
  local profile = scentProfileFor(item)

  if mult <= 0 or profile == nil then
    return output, mult
  end

  for _, component in ipairs(profile) do
    local name = component.scent
    local ratio = component.ratio or 0

    if output[name] ~= nil then
      output[name] = clamp(round(ratio * mult * 100), 0, 100)
    end
  end

  return output, mult
end

------------------------------------------------------------
-- Packet building
------------------------------------------------------------

local function buildBinaryPacket(player, item, d, output, mult)
  -- 27 bytes:
  --   1      sync, $A5
  --   2      type: 0 = none/off, 1 = target item
  --   3      distance, 255 if none
  --   4      hidden item index, 255 if none
  --   5      map id
  --   6      player x
  --   7      player y
  --   8      item x, 0 if none
  --   9      item y, 0 if none
  --   10     scent multiplier percent
  --   11-26  16 scent values in SCENTS order
  --   27     checksum = XOR of bytes 2-26

  local typ = 0
  local distByte = 255
  local indexByte = 255
  local itemX = 0
  local itemY = 0

  if item ~= nil then
    typ = 1
    distByte = clamp(d or 255, 0, 254)
    indexByte = clamp(item.index or 255, 0, 254)
    itemX = clamp(item.x or 0, 0, 255)
    itemY = clamp(item.y or 0, 0, 255)
  end

  local bytes = {
    0xA5,
    typ,
    distByte,
    indexByte,
    clamp(player.map or 0, 0, 255),
    clamp(player.x or 0, 0, 255),
    clamp(player.y or 0, 0, 255),
    itemX,
    itemY,
    clamp(round((mult or 0) * 100), 0, 100),
  }

  for _, scentName in ipairs(SCENTS) do
    bytes[#bytes + 1] = clamp(round(output[scentName] or 0), 0, 100)
  end

  local checksum = 0
  for i = 2, #bytes do
    checksum = xorByte(checksum, bytes[i])
  end

  bytes[#bytes + 1] = checksum

  return bytesToString(bytes)
end

local function buildTextPacket(player, mapName, item, d, output, mult)
  local typ = 0
  local dist = "none"
  local idx = "none"
  local ix = 0
  local iy = 0
  local itemName = "none"

  if item ~= nil then
    typ = 1
    dist = tostring(d or 255)
    idx = tostring(item.index or 255)
    ix = item.x or 0
    iy = item.y or 0
    itemName = safeName(item.name)
  end

  local parts = {
    "YSCENT1",
    "type=" .. tostring(typ),
    "distance=" .. dist,
    "index=" .. idx,
    string.format("map=0x%02X", player.map or 0),
    "map_name=" .. safeName(mapName),
    "player=" .. tostring(player.x or 0) .. "," .. tostring(player.y or 0),
    "item=" .. tostring(ix) .. "," .. tostring(iy),
    "item_name=" .. itemName,
    "multiplier=" .. tostring(clamp(round((mult or 0) * 100), 0, 100)),
  }

  for _, scentName in ipairs(SCENTS) do
    parts[#parts + 1] = safeName(scentName) .. "=" .. tostring(output[scentName] or 0)
  end

  return table.concat(parts, " ") .. "\n"
end

local function buildPacket(snapshot)
  if CFG.packet_mode == "text" then
    return buildTextPacket(
      snapshot.player,
      snapshot.mapName,
      snapshot.item,
      snapshot.distance,
      snapshot.scents,
      snapshot.multiplier
    )
  end

  return buildBinaryPacket(
    snapshot.player,
    snapshot.item,
    snapshot.distance,
    snapshot.scents,
    snapshot.multiplier
  )
end

------------------------------------------------------------
-- TCP transport, mGBA native socket only
------------------------------------------------------------

local Tcp = {
  client = nil,
  connected = false,
  lastConnectFrame = -999999,
  lastPayload = nil,
  lastStatus = "not connected",
  socketApiLogged = false,
}

local function closeTcp()
  if Tcp.client ~= nil then
    pcall(function()
      Tcp.client:close()
    end)
  end

  Tcp.client = nil
  Tcp.connected = false
end

local function nativeSocketAvailable()
  return type(socket) == "table" or type(socket) == "userdata"
end

local function tryNativeConnect()
  if not nativeSocketAvailable() then
    Tcp.lastStatus = "mGBA socket API unavailable"
    if not Tcp.socketApiLogged then
      log("TCP unavailable: mGBA global socket object is missing. No require('socket') is used.")
      Tcp.socketApiLogged = true
    end
    return nil
  end

  -- Preferred mGBA API: socket.connect(address, port) -> socket
  if type(socket.connect) == "function" then
    local ok, result = pcall(function()
      return socket.connect(CFG.tcp_host, CFG.tcp_port)
    end)

    if ok and result ~= nil then
      return result
    end

    Tcp.lastStatus = "connect failed: " .. tostring(result)
    return nil
  end

  -- Alternate API shape: socket.tcp() -> socket, then client:connect(...)
  if type(socket.tcp) == "function" then
    local ok, client = pcall(function()
      return socket.tcp()
    end)

    if not ok or client == nil then
      Tcp.lastStatus = "socket.tcp failed: " .. tostring(client)
      return nil
    end

    local connectedOk, connectResult = pcall(function()
      if type(client.connect) == "function" then
        return client:connect(CFG.tcp_host, CFG.tcp_port)
      end
      return nil
    end)

    if connectedOk and connectResult ~= nil and connectResult ~= false then
      return client
    end

    pcall(function()
      client:close()
    end)
    Tcp.lastStatus = "connect failed: " .. tostring(connectResult)
    return nil
  end

  Tcp.lastStatus = "socket object has no connect/tcp function"
  return nil
end

local function ensureTcp()
  if not CFG.tcp_enabled then
    Tcp.lastStatus = "disabled"
    return false
  end

  if Tcp.connected and Tcp.client ~= nil then
    return true
  end

  local frame = emu:currentFrame()
  if frame - Tcp.lastConnectFrame < CFG.reconnect_frames then
    return false
  end

  Tcp.lastConnectFrame = frame
  closeTcp()

  local client = tryNativeConnect()
  if client == nil then
    return false
  end

  Tcp.client = client
  Tcp.connected = true
  Tcp.lastStatus = "connected"
  log("TCP connected to " .. CFG.tcp_host .. ":" .. tostring(CFG.tcp_port))
  return true
end

local function sendTcp(payload)
  if not ensureTcp() then
    return false
  end

  local ok, result = pcall(function()
    return Tcp.client:send(payload)
  end)

  if not ok then
    Tcp.lastStatus = "send exception: " .. tostring(result)
    closeTcp()
    return false
  end

  if result == nil or result == false then
    Tcp.lastStatus = "send failed"
    closeTcp()
    return false
  end

  Tcp.lastStatus = "sent"
  return true
end

local function maybeSend(snapshot)
  if not CFG.tcp_enabled then
    return
  end

  local payload = buildPacket(snapshot)

  if CFG.send_only_on_change and payload == Tcp.lastPayload then
    Tcp.lastStatus = "unchanged"
    return
  end

  if sendTcp(payload) then
    Tcp.lastPayload = payload
  end
end

------------------------------------------------------------
-- Snapshot and debug UI
------------------------------------------------------------

local function makeSnapshot()
  local player = readPlayer()
  local mapName = MAP_NAME[player.map] or "UNKNOWN"
  local item, d = nearestUngrabbedItem(player)
  local scents, mult = computeScent(item, d)

  return {
    player = player,
    mapName = mapName,
    item = item,
    distance = d,
    scents = scents,
    multiplier = mult,
  }
end

local Ui = {
  buffer = nil,
  lastFrame = -999999,
}

local function initUi()
  if Ui.buffer ~= nil then
    return
  end

  if console == nil or console.createBuffer == nil then
    return
  end

  Ui.buffer = console:createBuffer(CFG.buffer_name)
  Ui.buffer:setSize(116, 40)
end

local function printScents(buf, scents)
  buf:print("Scent outputs, 0-100:\n")

  for _, scentName in ipairs(SCENTS) do
    buf:print(string.format("  %-13s %3d\n", scentName .. ":", scents[scentName] or 0))
  end
end

local function drawUi(snapshot)
  initUi()

  if Ui.buffer == nil then
    return
  end

  local buf = Ui.buffer
  local player = snapshot.player

  buf:clear()
  buf:print("Pokemon Yellow scent TCP debug\n")
  buf:print("--------------------------------\n")
  buf:print(string.format("Map:    %d / $%02X  %s\n", player.map, player.map, snapshot.mapName))
  buf:print(string.format("Player: x=%d y=%d\n", player.x, player.y))
  buf:print(string.format("TCP:    %s:%d  %s  mode=%s\n", CFG.tcp_host, CFG.tcp_port, Tcp.lastStatus, CFG.packet_mode))
  buf:print(string.format("Flags:  base=$%04X\n", ADDR.wObtainedHiddenItemsFlags))
  buf:print("\n")

  if snapshot.item ~= nil then
    buf:print("Nearest ungrabbed hidden item:\n")
    buf:print(string.format("  [%02d] %s\n", snapshot.item.index, snapshot.item.name))
    buf:print(string.format("  pos=(%d,%d) distance=%d\n", snapshot.item.x, snapshot.item.y, snapshot.distance))
    buf:print(string.format("  scent_multiplier=%.2f\n", snapshot.multiplier))
  else
    buf:print("Nearest ungrabbed hidden item:\n")
    buf:print("  none on this map, or all grabbed\n")
    buf:print("  scent_multiplier=0.00\n")
  end

  buf:print("\n")
  printScents(buf, snapshot.scents)
  buf:print("\n")

  buf:print("Hidden items on current map:\n")

  local any = false
  for _, item in ipairs(HIDDEN_ITEMS) do
    if item.map == player.map then
      any = true
      local d = distance(player.x, player.y, item.x, item.y)
      local flag = getHiddenItemFlag(item.index)

      buf:print(string.format(
        "  [%02d] %-24s pos=(%3d,%3d) dist=%3d grabbed=%s flag=$%04X byte=$%02X bit=%d\n",
        item.index,
        item.name,
        item.x,
        item.y,
        d,
        tostring(flag.grabbed),
        flag.addr,
        flag.byte,
        flag.bit
      ))
    end
  end

  if not any then
    buf:print("  none listed for this map\n")
  end
end

------------------------------------------------------------
-- Frame callback
------------------------------------------------------------

local function onFrame()
  local frame = emu:currentFrame()

  if frame - Ui.lastFrame < CFG.update_frames then
    return
  end

  Ui.lastFrame = frame

  local snapshot = makeSnapshot()
  maybeSend(snapshot)
  drawUi(snapshot)
end

callbacks:add("frame", onFrame)

log("Yellow scent TCP rewrite loaded.")
log("Start tcp_omara_ble_bridge.py first. This script uses mGBA native socket, not require('socket').")
