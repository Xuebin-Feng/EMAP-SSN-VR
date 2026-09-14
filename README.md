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

## Opening it

```bash
opt_vr/Viewer.bat
```

That opens the **main program's Config GUI** — opt_vr has no settings UI of its
own. Choose the dataset, network, threshold and layout cache exactly as you
would for the desktop viewer; the Launch button then starts the VR viewer
instead. Set **Layout Dimensions** to `3` for a true 3D layout.

The batch file runs the main program's GUI with `--viewer`, pointing it at
`opt_vr/Viewer.py`:

```bash
.venv/Scripts/python.exe src/EMAPSSN_Config.py --viewer opt_vr/Viewer.py
```

That option is the whole integration. `EMAPSSN_Config` launches whichever
viewer path it is given and otherwise behaves identically, so the per-launch
settings snapshot, the selected cache and the `(New Layout Cache)` handoff to
`Layout_Cache_Generator.py` all work unchanged. `Viewer.py` accepts the same
`--settings PATH [--delete-settings]` contract as the desktop viewer, which is
what lets one GUI drive either front end without special-casing.

The viewer never computes a layout. If you need a cache without the GUI:

```bash
python src/Layout_Cache_Generator.py <layout_settings.json>
```

3D caches are published to their own folder, suffixed `_3D`, and carry a
distinct manifest id, so they never collide with the 2D cache built from the
same inputs. A 2D cache still opens; its coordinates are lifted onto the
`z = 0` plane and a warning is printed.

To skip the GUI and open the viewer directly against the saved settings, run
`Viewer.py`. With nothing pinned it resolves the cache through the main
program's own `resolve_selected_cache`, so it honours whatever the GUI last
saved; `TARGET_CACHE_PATH`, or the `SSN_TARGET_CACHE` environment variable,
overrides that.

## Configuration

Settings are shared with the main program. `viewer_settings.json` in the
EMAP-SSN project root is the source of truth, and the EMAP-SSN Config GUI is
what writes it — **the VR runtime only ever reads it**, so no Qt is imported
into the headless VR process. `Settings.py` layers the handful of VR-only
keys (Unity host/port, edge-render budget) on top of the shared defaults in
`src/desktop/Viewer_State.py`. Drop a `vr_settings.json` beside
`Settings.py` to override any of them locally.

## Which commands are shared

`commands/` falls through to `src/commands`, so a command is either shared from
upstream or overridden here. `Command_Compatibility.py` decides which, instead
of leaving it to memory — that is how the previous fork drifted.

```bash
../.venv/Scripts/python.exe Command_Compatibility.py
```

Each command is probed twice: once by executing it behind an import hook that
refuses Qt and VisPy, and once by comparing the `viewer.<attr>` reads in its AST
against the surface `Viewer.py` actually provides. A command marked `redundant`
has a local override that upstream could serve; one marked `broken` cannot be
loaded at all, and `--check` exits non-zero so the test suite catches it.

Both probes are load-time only. A clean verdict means "imports, and only touches
API this viewer has" — not that the behaviour is what you want. Deleting a
redundant override is still a judgement call.

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
