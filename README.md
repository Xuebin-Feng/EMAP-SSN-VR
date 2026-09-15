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

> [!IMPORTANT]
> **Windows only.** `VR_App` holds a built Windows Unity player and the viewer
> launches it directly, so every VR entry point refuses to start anywhere else
> rather than failing later on a missing `.exe`. The main program stays
> cross-platform, and its desktop viewer opens the same layout caches in 2D.
> This is why `opt_vr` ships `.bat` launchers and no `.sh` or `.app`
> counterparts.

Then generate the launcher shortcut:

```bat
opt_vr\install_vr.bat
```

This is the VR counterpart of the main program's `install.bat`, suffixed
like every other mirrored file here. It writes
`EMAP-SSN VR.lnk` beside this README and offers to copy it to your Desktop. It
installs nothing itself: the shortcut sets the Python environment up on its
first run, exactly as the `EMAP-SSN` and `EMAP-SSN Tools` shortcuts do, so that
first launch takes noticeably longer than later ones.

## Repository layout

The tree mirrors the main program's, so a file has the same role in both.
Anything with a counterpart upstream carries a `_VR` suffix — or `_vr` where the
upstream name is lowercase — and the three names that are *not* suffixed are
load-bearing: upstream command modules import `Command_Engine`,
`Viewer_Command_Portal` and `commands.<name>` by those exact names, and
`_bootstrap_vr` puts `opt_vr/src` ahead of the parent's `src` so they resolve to
the VR versions. Renaming them would route shared commands back into the desktop
Qt/VisPy stack.

```
opt_vr/
├── install_vr.bat                       # writes the EMAP-SSN VR shortcut
├── VR_App/                              # the built Windows Unity player
├── Cache_Files/                         # runtime working directory (ignored)
├── viewer_settings_vr.json              # per-user settings (ignored)
├── docs/PROTOCOL.md                     # Python/Unity wire protocol
├── tests/
└── src/
    ├── _bootstrap_vr.py                 # sys.path and the Windows-only guard
    ├── EMAPSSN_Config_VR.py             # VR Configuration GUI
    ├── EMAPSSN_Viewer_VR.py             # VR viewer and Unity bridge
    ├── Settings_VR.py                   # Qt-free settings layer
    ├── Viewer_Utils_VR.py               # sequence and colour helpers
    ├── Unity_Build_VR.py                 # reads a build's baked endpoint
    ├── Single_Instance_VR.py             # one VR viewer at a time
    ├── Detect_GPU_VR.py                  # can this machine drive a headset
    ├── Command_Compatibility_VR.py      # shared vs overridden command audit
    ├── Command_Engine.py                # name pinned: upstream imports it
    ├── Viewer_Command_Portal.py         # name pinned: upstream imports it
    ├── commands/                        # name pinned: upstream imports it
    └── bin/                             # launchers and startup handshake
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

Double-click **EMAP-SSN VR**. That opens `src/EMAPSSN_Config_VR.py`, the
**VR Configuration GUI**. Choose the sequence set, network, threshold and layout cache, then press
**Save & Run**. The main program's Config GUI is a separate window for the
desktop viewer and is never involved.

The shortcut behaves exactly like the main program's. A startup terminal
appears, validates the managed environment, and closes itself the moment the Qt
window reports that it is on screen, so a healthy launch leaves no console
behind; it stays visible only while there is something to read, such as
dependency setup or a startup failure. Launching again raises the window that
is already open instead of starting a second one, and because the VR window and
the desktop Config window register different single-instance keys, both can be
open at the same time.

`opt_vr` owns no virtual environment. It imports the main program's `src` tree
for everything scientific, so it runs in the parent's managed `.venv` — and
creating, repairing and validating that environment (the uv bootstrap,
`uv venv --python 3.12`, `Install_Dependencies.py` and the cross-process setup
lock) is delegated to `src/bin/EMAPSSN.bat`. One implementation and one lock,
rather than two that can drift apart.

| Script | Role | Upstream counterpart |
|---|---|---|
| `install_vr.bat` | writes `EMAP-SSN VR.lnk` | `install.bat` |
| `src/bin/EMAPSSN_Desktop_Launcher_VR.bat` | startup terminal; closes once the GUI is ready | `src/bin/EMAPSSN_Desktop_Launcher.bat` |
| `src/bin/EMAPSSN_VR.bat` | environment validation and repair, then the GUI | `src/bin/EMAPSSN.bat` |
| `src/bin/Desktop_Launcher_Monitor_VR.py` | detached supervisor and startup handshake | `src/desktop/Desktop_Launcher_Monitor.py` |
| `src/bin/Single_Instance_Probe_VR.py` | raises an already-open VR window | `src/desktop/Single_Instance_Probe.py` |

The two Python modules import the upstream policy instead of copying it —
environment sanitizing, the atomic ready and exit files, the dismissal
handshake, the error terminal. Only the app script and the single-instance key
differ, which is why upstream owns no reference to
`opt_vr/src/EMAPSSN_Config_VR.py`: that path is absent whenever the submodule
is not checked out.

Like the main program, the root holds no launcher of its own — the shortcut
and `install_vr.bat` are the way in. To start the GUI without the shortcut,
run `src\bin\EMAPSSN_VR.bat`, which validates the environment first.

There is no 2D/3D control. The VR viewer is three dimensional by definition, so
dimensionality follows from which viewer you opened — exactly as the desktop
GUI has no such control. Every cache this GUI resolves or generates is 3D.

Settings are written to **`opt_vr/viewer_settings_vr.json`**, and every relative
directory resolves inside the submodule, so a VR configuration never disturbs
the desktop program's `viewer_settings.json`. The file is git-ignored, like its
desktop counterpart, because it holds local paths.

`src/EMAPSSN_Config_VR.py` is a **copy of the main program's
`src/EMAPSSN_Config.py`**, rebased onto the
submodule. That is deliberate: reimplementing it by hand produced a window that
merely resembled the original and kept turning out to be missing things. A copy
is identical by construction, so every feature — saved-config profiles, network
statistics, the score histogram, colour pickers, live field gating, input
consistency checks — behaves exactly as it does in the main program.

The copy diverges from its source by about **220 of 4,200 lines**, most of them
the new VR tab. The rest is small and deliberate:

| Change | Why |
|---|---|
| `PROJECT_ROOT` → `opt_vr` | every relative directory resolves in the submodule |
| `viewer_settings_vr.json` | the desktop program's settings are never touched |
| launches `src/EMAPSSN_Viewer_VR.py` | the VR viewer, not the desktop one |
| `layout_dimensions=3` forced | into cache identity and layout generation |
| Unity bridge block on **Visual Effects** | host, port, distance scale, edge budget, Unity build |
| removed controls | see below |
| distinct single-instance key | both windows can be open at once |

Four settings the desktop GUI offers are deliberately absent, because nothing
in the VR runtime reads them and no shared command does either:

| Removed | Why |
|---|---|
| `TEXT_SIZE`, `TEXT_COLOR` | no HUD text is drawn in the headset |
| `LOW_RESOURCE_MODE` | a VisPy canvas optimisation; Unity does the drawing |
| `PACKING_GEOMETRY` | in 3D `calculate_layout` branches to `pack_components_to_shells`, which arranges components on concentric spherical shells and takes no geometry argument — Square/Circle never reaches it |

`NEIGHBOR_COLOR` has no control of its own either: `Settings` republishes
`INITIAL_NODE_COLOR` under that name and it wins, so a second control would
silently discard whatever was picked in it.

Keeping it in sync with upstream is a `diff` against `src/EMAPSSN_Config.py`,
and that table is the list of hunks that are meant to differ.

The viewer never computes a layout. If you need a cache without the GUI:

```bash
python src/Layout_Cache_Generator.py <layout_settings.json>
```

3D caches are published to their own folder, suffixed `_3D`, and carry a
distinct manifest id, so they never collide with the 2D cache built from the
same inputs. A 2D cache still opens; its coordinates are lifted onto the
`z = 0` plane and a warning is printed.

To skip the GUI and open the viewer directly against the saved settings, run
`src/EMAPSSN_Viewer_VR.py`. With nothing pinned it resolves the cache through the main
program's own `resolve_selected_cache`, so it honours whatever the GUI last
saved; `TARGET_CACHE_PATH`, or the `SSN_TARGET_CACHE` environment variable,
overrides that.

## Configuration

Settings are shared with the main program. `viewer_settings.json` in the
EMAP-SSN project root is the source of truth, and the EMAP-SSN Config GUI is
what writes it — **the VR runtime only ever reads it**, so no Qt is imported
into the headless VR process. `src/Settings_VR.py` layers the handful of VR-only
keys (Unity host/port, edge-render budget) on top of the shared defaults in
the main program's `src/desktop/Viewer_State.py`. Drop a
`viewer_settings_vr.json` in the submodule root to override any of them
locally.

## Which commands are shared

`src/commands/` falls through to the main program's `src/commands`, so a
command is either shared from upstream or overridden here.
`src/Command_Compatibility_VR.py` decides which, instead of leaving it to
memory — that is how the previous fork drifted.

```bash
../.venv/Scripts/python.exe src/Command_Compatibility_VR.py
```

Each command is probed twice: once by executing it behind an import hook that
refuses Qt and VisPy, and once by comparing the `viewer.<attr>` reads in its AST
against the surface `src/EMAPSSN_Viewer_VR.py` actually provides. A command marked `redundant`
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
the load-only cache consumer, and the launcher surface — that setup is
delegated rather than duplicated, that the startup handshake uses upstream's
file names and exit codes, and that every entry point is guarded as
Windows-only.

## The Unity client

`VR_App/` holds the built Windows player. Python listens on `127.0.0.1:5005`;
the client connects, receives a binary handshake carrying node count,
positions (`float32` x, y, z), and the rendered and full edge lists, then
exchanges newline-delimited JSON for per-node colour, size and visibility
updates.

The endpoint cannot be negotiated: the client dials before Python has any way
to tell it where to dial, so the address is compiled into the build and the
server has to be told the same one. Getting that wrong produces no error at
all - Python listens on one port, the player dials another, and the headset
simply never fills in. So the Config GUI reads the address out of the build
rather than asking for it. `src/Unity_Build_VR.py` finds it in the serialized
scene, where Unity stores it as a length-prefixed string followed by the port:

```
09 00 00 00  "127.0.0.1"  00 00 00   8d 13 00 00
|- length 9  |- utf-8     |- pad     |- int32 5005
```

Choosing a build fills **Unity Host** and **Unity Port** in from it, and any
disagreement between the two is called out above the fields.

## Hardware

Not every GPU that runs the main program can run this one. `src/Detect_GPU_VR.py`
answers that separately, because the main program's `Detect_GPU` is deciding
which PyTorch backend to install - a compute question whose answer does not
carry over. The Unity client, not Python, is what renders to the headset.

| Vendor | VR | Notes |
|---|---|---|
| NVIDIA | yes | |
| AMD | yes | SteamVR's stated floor is roughly an RX 480 |
| Intel Arc (A- and B-series) | **no** | SteamVR refuses to start when it detects an Arc GPU, and Intel has published no timeline. Streaming apps such as Virtual Desktop are the only route, and they bypass this viewer's client |
| Intel integrated (UHD, Iris) | no | not a VR part |

Arc is the trap worth naming: it is a perfectly good XPU compute target, so the
main program will happily pick it, embed on it and build layouts with it, and
the headset will still never light up.

The check reads display adapter names and the registered OpenXR runtime -
about 0.7s, against roughly four seconds for the full `detect_hardware()`,
which is what makes it cheap enough to run on every launch. It reports and
never enforces: the Config GUI is useful on a machine with no headset attached,
so an unsupported verdict is printed and launched past rather than refused.

```bash
../.venv/Scripts/python.exe src/Detect_GPU_VR.py
```

Exit codes are 0 ready, 10 no supported GPU, 11 no OpenXR runtime, 12 unknown,
so a script can branch on it. The desktop launcher runs it after validating the
Python environment, and the viewer runs it again just before handing over to
the Unity client, which is the moment an unsupported GPU actually bites.

What it deliberately does not do is judge whether the hardware is *fast
enough*. That depends on the headset, the scene and the network size, and a
checker that guessed would be wrong more often than useful.

## One viewer at a time

Two VR viewers cannot usefully coexist. They drive the same headset through the
same Unity client, and they listen on the same endpoint - which the client
dials by an address compiled into its build, so it cannot be told to reach the
other one. A second viewer does not give a second view; it gives two processes
fighting over one client.

So `src/Single_Instance_VR.py` takes a Windows named mutex before anything
else, and a second viewer exits with an explanation rather than racing for the
port. The mutex is used in preference to a lock file because the kernel
releases it however the holding process died - a stale lock that refuses to
start the viewer is a worse failure than the one being prevented - and it is
session-local, so two desktop sessions on one machine do not fight over a
headset neither of them shares. The listening socket asks for
`SO_EXCLUSIVEADDRUSE` rather than `SO_REUSEADDR` for the same reason: on
Windows the latter lets an unrelated process bind a port this one is already
serving and take the connections with it.

This is the one place opt_vr deliberately differs from the main program, whose
viewer may legitimately be opened more than once because each instance owns its
own window. Nothing here owns a window.

**Quit With Unity**, at the bottom of the Visual Effects tab, decides what
happens when the headset app closes. On - the default - the viewer follows it
out rather than leaving an orphan holding the port. Off keeps the viewer and
its command console running, which is what you want while debugging the
client.

This is a heuristic over a serialized asset, not a documented API, so it
declines rather than guesses: an address merely embedded in a longer string, an
implausible port, or two endpoints that disagree all read as unknown, and
whatever you typed stands. A build that stores its endpoint some other way
costs you the convenience, never the ability to set it by hand.

The cleaner fix is the opposite direction - `EMAPSSN_Viewer_VR.py` launches the
player itself, so it could pass the endpoint as a launch argument and make
Python authoritative - but that needs a change on the Unity side and a rebuild.
Until then, reading the build is what keeps the two ends from drifting.

## Licence

Apache License 2.0 — see [LICENSE](LICENSE).
