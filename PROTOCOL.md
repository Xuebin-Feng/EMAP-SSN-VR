# Python ↔ Unity protocol

The VR viewer is two processes: this Python backend, and a Unity/SteamVR
client. They speak over a plain TCP socket on `127.0.0.1:5005`.

This document describes the protocol as implemented in `Viewer.py`. The Python
side has been read and verified; the Unity side has **not** been rebuilt or
instrumented as part of this work, so statements about the client's behaviour
come from reading its serialized scene and assembly, not from running it under
a debugger.

## Connection

`start_server()` binds `VR_HOST:VR_PORT` (defaults `127.0.0.1:5005`), sets
`SO_REUSEADDR`, and calls `listen(1)` — **one client at a time**. After a
disconnect the accept loop simply waits for a new connection.

The endpoint is a setting, but the shipped Unity build has `127.0.0.1` and
`5005` baked into its scene, so changing it requires rebuilding the client.

## Phase 1 — binary handshake (server → client, once per connection)

Sent immediately on accept. Little-endian, **no length prefix, no delimiter,
no acknowledgement, no version field**. The client must consume exactly the
implied byte counts, in order:

| # | Bytes | Content |
|---|---|---|
| 1 | 4 | `uint32` node count *N* |
| 2 | 12 × *N* | `float32` positions, row-major `x, y, z` |
| 3 | 4 | `uint32` rendered edge count *E* |
| 4 | 8 × *E* | `int32` edge pairs, the downsampled set actually drawn |
| 5 | 4 | `uint32` full edge count *F* |
| 6 | 8 × *F* | `int32` edge pairs, the complete list for connectivity queries |

Blocks 3–4 and 5–6 are identical when edge downsampling does not trigger, so
the same array is transmitted twice.

## Phase 2 — newline-delimited JSON (both directions)

Immediately after block 6, with no separator, the server sends the initial
state packet. From then on every message in either direction is one JSON
object terminated by a single `\n`.

### Server → client: node state

Flat arrays, because Unity's `JsonUtility` cannot deserialize dictionaries.

```jsonc
{
  "colors":  [r, g, b, a, ...],   // 4 × N floats, 0..1
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

There is no message-type field: this packet is identified positionally.

### Client → server

Exactly one message type is recognised:

```jsonc
{ "type": "transform",
  "position": [x, y, z], "rotation": [x, y, z, w],
  "scale": [x, y, z], "distanceScale": 1.0 }
```

Any other `type` is silently dropped.

## Threading

Three threads. The main thread runs the terminal. One daemon thread owns
`accept()`, the handshake and **all** sends. A second daemon thread per
connection owns the receive side. Commands hand work across by pushing a fully
materialised packet onto `viewer.update_queue`; the sender drains one packet
per 0.05 s tick, so the flush rate caps at roughly 20 packets per second.

## Known limitations

These constrain what a command can meaningfully do, and each would need a
Unity-side change to lift.

1. **Positions are immutable after the handshake.** They are sent once, in
   block 2. Any command that moves nodes changes Python state only; the
   headset will not show it until a reconnect. This is why `reset network` and
   an undo of a layout change cannot be reflected visually.
2. **Selection is one-way.** The Unity client tracks hover and selection
   internally but never transmits them, so `$sele$` in a terminal command
   cannot see what the user picked up in the headset. Conversely, a terminal
   `select` is invisible in the headset.
3. **No shape channel.** `viewer.current_shapes` is maintained and saved to the
   cache but never sent.
4. **No node identity.** Headers are never transmitted, so nothing in the
   headset can be labelled or reported back by name.
5. **No framing, magic number or version.** If the two sides disagree about
   counts, the stream desynchronises silently rather than failing cleanly.
6. **Whole-state updates.** Every change resends all colours, sizes and
   visibility as JSON text — on the order of a megabyte of ASCII for a
   13,000-node network, with no delta encoding.

## Changing the protocol

The Unity project is **not** in this repository. At the time of writing it
lives outside the checkout, built with Unity `6000.4.8f1` using the **Mono**
scripting backend (not IL2CPP), with the gameplay code in a single
`SSNVRViewer` MonoBehaviour. Because it is Mono, the shipped
`Assembly-CSharp.dll` is decompilable, so the client's behaviour can be
recovered even without the project.

Any protocol change is therefore a coordinated change: the Python side here,
and a rebuilt player. Adding a message-type field and a length prefix to the
binary phase would be the sensible first step, since every item above then
becomes an additive change rather than another positional convention.
