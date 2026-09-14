# EMAP-SSN-VR (`opt_vr`)

The VR front end for [EMAP-SSN](https://github.com/Xuebin-Feng/EMAP-SSN):
an alternative viewer that plots a Sequence Similarity Network in 3D and
renders it through a Unity/SteamVR client.

This repository is consumed as the `opt_vr` submodule of EMAP-SSN and is not
designed to run standalone.

```bash
git clone https://github.com/Xuebin-Feng/EMAP-SSN.git
cd EMAP-SSN
git submodule update --init opt_vr
```

## What lives here, and what does not

`opt_vr` contains **no part of the calculation pipeline.** Sequence
sanitization, embedding generation, alignment, network construction and layout
generation are all the main program's responsibility. This package:

- reads a layout cache published by `src/Layout_Cache_Generator.py`,
- rebuilds the edge list with the main program's own `prepare_network`, so VR
  edge filtering is identical to the desktop viewer's,
- streams that state to the Unity client over a local socket, and
- exposes a terminal command console for analysis.

Everything scientific is imported from `../src`. Nothing is vendored, so the
two programs cannot drift apart the way they did before.

## Generating something to view

The viewer will not compute a layout. Produce a 3D cache with the main program
first, setting `LAYOUT_DIMENSIONS` to `3`:

```bash
python src/Layout_Cache_Generator.py <layout_settings.json>
```

3D caches are published to their own folder, suffixed `_3D`, and carry a
distinct manifest id, so they never collide with the 2D cache built from the
same inputs. Point `TARGET_CACHE_PATH` in `viewer_settings.json` — or the
`SSN_TARGET_CACHE` environment variable — at the published folder, then run:

```bash
opt_vr/SSN_VR_Viewer.bat
```

A 2D cache will still open; its coordinates are lifted onto the `z = 0` plane
and a warning is printed.

## Configuration

Settings are shared with the main program. `viewer_settings.json` in the
EMAP-SSN project root is the source of truth, and the EMAP-SSN Config GUI is
what writes it — **the VR runtime only ever reads it**, so no Qt is imported
into the headless VR process. `VR_Settings.py` layers the handful of VR-only
keys (Unity host/port, edge-render budget) on top of the shared defaults in
`src/desktop/Viewer_State.py`. Drop a `vr_settings.json` beside
`VR_Settings.py` to override any of them locally.

## Tests

```bash
cd opt_vr
../.venv/Scripts/python.exe -m unittest discover -s tests -t .
```

These cover the settings layer (alias resolution, type coercion), `sys.path`
precedence between `opt_vr` and `src`, the command package's override and
fall-through behaviour, the shared `Command_Engine` API upstream commands call,
and the load-only cache consumer.

## The Unity client

`VR_App/` holds the built Windows player. Python listens on `127.0.0.1:5005`;
the client connects, receives a binary handshake carrying node count,
positions (`float32` x, y, z), and the rendered and full edge lists, then
exchanges newline-delimited JSON for per-node colour, size and visibility
updates.

## Licence

Apache License 2.0 — see [LICENSE](LICENSE).
