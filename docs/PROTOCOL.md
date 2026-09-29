# Python ↔ VR client protocol (version 1)

The VR viewer runs as two processes: the Python backend
(`src/EMAPSSN_Viewer_VR.py`) and a VR client that renders to the headset. They
talk over a plain TCP socket, on `127.0.0.1:5005` by default.

This document is the contract. The Python server is its reference
implementation, and `tests/test_protocol_v1.py` checks the server against a
client written from this document (`tools/Protocol_V1_VR.py`). Version 1 is
the protocol the original Unity client spoke, byte for byte; the Godot client
that replaces it speaks the same version.

## Connection

`start_server()` binds `VR_HOST:VR_PORT` (defaults `127.0.0.1:5005`) with
`SO_EXCLUSIVEADDRUSE` and calls `listen(1)`, so there is **one client at a
time**. After a disconnect the accept loop waits for a new connection, unless
"Quit with VR Client" (`EXIT_WITH_UNITY`) makes the viewer exit instead.

The client dials the server and retries every 2 seconds until it connects.

## Starting the client

The viewer starts the installed client itself (`launch_vr_app()`), from the
client's own folder, and passes the endpoint it listens on:

```
player\EMAP-SSN-VR.exe -- --host <VR_HOST> --port <VR_PORT> --restartable
```

- Everything after `--` belongs to the client. Engine options, such as
  `--xr-mode off` to keep a headset runtime from starting, go before it.
- A wildcard listen address (`0.0.0.0`) is passed as `127.0.0.1`.
- `--restartable` lets the client exit with code **75** to be started again.
  It does that when SteamVR bound its controllers with a catch-all profile
  (`khr/generic_controller` or `khr/simple_controller`). SteamVR binds an
  app's controllers once, when the app starts, and only for controller
  types it has seen by then, so WMR controllers that connect after the
  client started SteamVR get a binding without their grip pose or
  thumbstick. The viewer starts the client once more, without the flag, and
  a restart does not count as the client closing for "Quit with VR
  Client".
- The client dials the first of: `--host` and `--port`; the endpoint in
  `vr_client.json` beside its executable; its built-in `127.0.0.1:5005`. The
  last two only matter for a client started by hand.

`vr_client.json` describes the build:

```json
{"client": "EMAP-SSN-VR Godot client", "version": "0.1.0", "protocol": 1,
 "host": "127.0.0.1", "port": 5005, "godot": "4.7.2.stable", "commit": "..."}
```

The viewer compares `version` with the release that `player_release.json`
pins, and names both when they differ.

## Phase 1: binary handshake (server → client, once per connection)

The server sends this as soon as it accepts. Everything is little-endian, and
there is **no length prefix, no delimiter, no acknowledgement and no version
field**. The client must consume exactly the implied byte counts, in this
order:

| # | Bytes | Content |
|---|---|---|
| 1 | 4 | `uint32` node count *N* |
| 2 | 12 × *N* | `float32` positions, row-major `x, y, z` |
| 3 | 4 | `uint32` rendered edge count *E* |
| 4 | 8 × *E* | `int32` node-index pairs: the downsampled set that is drawn |
| 5 | 4 | `uint32` full edge count *F* |
| 6 | 8 × *F* | `int32` node-index pairs: the complete list, for connectivity queries |

When edge downsampling does not trigger, blocks 3–4 and 5–6 are identical and
the same array is sent twice. *E* and *F* may be zero. A 13,000-node network
with 500,000 rendered and 4.16 million full edges is a 37.5 MB handshake.

## Phase 2: newline-delimited JSON (both directions)

The server sends the initial state packet immediately after block 6, with no
separator. From then on, every message in either direction is one JSON object
terminated by a single `\n`. The server writes ASCII (`json.dumps` defaults).

### Server → client: node state

Arrays are flat, a legacy of the original client's JSON parser; they stay
flat for compatibility. Every packet carries the **whole** state.

```jsonc
{
  "colors":  [r, g, b, a, ...],   // 4 × N floats, 0..1, sRGB-encoded
  "sizes":   [s, ...],            // N floats
  "visible": [true, ...],         // N booleans
  "globalSettings": {
    "nodeScale": 10.0, "edgeThickness": 1.0,
    "edgeAlpha": 0.1,  "nodeBoundaryWidth": 0.5,
    "neighborColor": "#4488ff", "hoverColor": "#ffaa00",
    "connectedNodeColor": "#ff0000", "edgeColor": "#000000",
    "nodeBoundaryColor": "#000000"
  },
  "transformState": {
    "position": [x, y, z],
    "rotation": [x, y, z, w],     // quaternion, xyzw
    "scale":    [x, y, z],
    "distanceScale": 1.0
  }
}
```

The packet has no message-type field; it is identified by position. Colours
are the same sRGB values the desktop viewer draws, so a client must convert
them to linear before shading in a linear-light renderer. If several packets
arrive between two frames, a client applies only the newest.

### Client → server

The server recognises one message type:

```json
{"type":"transform","position":[x,y,z],"rotation":[x,y,z,w],"scale":[x,y,z],"distanceScale":d }
```

Clients write each number with four decimals in invariant formatting; the
Unity client also left a space before the closing brace, and the reference
client keeps that spelling. The server accepts any valid JSON. A client sends
at most 10 transforms per second while the user is manipulating the network,
then one more when the gesture ends. While a gesture is in progress, it
ignores the `transformState` in server packets, so the server's echo of an
older transform cannot fight the user's hands.

The server silently drops any other `type`. A client may therefore send a
hello as its first line, which version 1 servers ignore:

```json
{"type":"hello","client":"godot","version":"0.1.0","protocol":1}
```

## Coordinate frame

Positions, the transform's position and its rotation all use the frame of the
original Unity client: **left-handed, Y up, +x right, +z forward.** Python
never interprets them. It stores the last transform a client sent and echoes
it back in later packets, so every client must use the same frame on the wire.

A client with a right-handed convention, such as Godot's, converts at the
boundary. It negates z for positions and for the transform's position, and it
maps a rotation `(x, y, z, w)` to `(−x, −y, z, w)`. Scale and `distanceScale`
are unchanged.

The client places the network as follows:

- local position = `raw × 0.1 + (0, 1.5, 0)`
- world position = `T × (local × distanceScale)`, where `T` is the transform's
  position, rotation and scale
- node diameter = `size × 0.005 × scale.x`
- edge width = `edgeThickness × 0.005 × scale.x`

`distanceScale` spreads the nodes apart without changing their size.

## Threading

The Python side runs three threads:

- The main thread runs the terminal.
- One daemon thread owns `accept()`, the handshake and **every** send.
- A second daemon thread per connection owns the receive side.

Commands hand work across by pushing a complete packet onto
`viewer.update_queue`. The sender drains the queue, sleeping 0.05 s whenever
it is empty.

## Known limitations

Each of these needs a coordinated change to both server and client to lift.

1. **Positions are fixed after the handshake.** They are sent once, in
   block 2. A command that moves nodes changes only Python's state, and the
   headset won't show it until the client reconnects. This is why
   `reset network`, and undoing a layout change, can't be reflected
   visually.
2. **Selection doesn't cross over.** The client tracks hover and selection
   itself and never sends them. A terminal command using `$sele$` can't see
   what the user picked in the headset, and a terminal `select` doesn't
   appear in the headset.
3. **There is no shape channel.** `viewer.current_shapes` is maintained and
   saved to the cache but never sent.
4. **Nodes have no identity on the wire.** Headers are never sent, so nothing
   in the headset can be labelled or reported back by name.
5. **There is no framing, magic number or version.** If the two sides
   disagree about a count, the stream desynchronises silently instead of
   failing cleanly.
6. **Every update resends the whole state.** Every change resends all
   colours, sizes and visibility as JSON text: about 0.8 MB for a
   13,000-node network, with no delta encoding.

## Tools and tests

| File | Purpose |
|---|---|
| `tools/Protocol_V1_VR.py` | Reference client and a loopback runner for the production server loop |
| `tests/test_protocol_v1.py` | Conformance tests: block order and layout, edge cases, packet schema, transforms, unknown types, reconnects |
| `tools/Protocol_Fixtures_VR.py` | Records the real server's byte streams, with their expected decoding, for client tests |
| `tools/Synthetic_Server_VR.py` | Serves a random clustered network through the production loop, with a prompt that pushes packets |
| `tools/Protocol_Proxy_VR.py` | A logging proxy that writes a JSON-lines transcript of a session |

## Changing the protocol

Any change is coordinated: this document, the reference client and its
tests, the fixtures, the server and the client all move together.

The hello message is how a future version can be negotiated without breaking
older clients:

- After `accept()`, a server that knows a newer version waits up to about
  200 ms for a hello.
- If the hello names a protocol version the server supports, the server
  speaks that version.
- If no hello arrives, the server sends version 1 exactly as it does today.
  This covers clients that never send one, such as the Unity client.

Version 2 would be the place to add a length-prefixed, typed framing. That
turns every limitation above into an additive change rather than another
positional convention.
