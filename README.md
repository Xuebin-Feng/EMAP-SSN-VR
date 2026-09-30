# EMAP-SSN-VR (`opt_vr`)

The VR front end for [EMAP-SSN](https://github.com/Xuebin-Feng/EMAP-SSN):
an alternative viewer that plots a Sequence Similarity Network in 3D and
renders it in a headset through a Godot 4 / OpenXR client.

This repository is consumed as the `opt_vr` submodule of EMAP-SSN and is not
designed to run standalone.

```bash
git clone https://github.com/Xuebin-Feng/EMAP-SSN.git
cd EMAP-SSN
git submodule update --init opt_vr
```

> [!IMPORTANT]
> **Windows only.** The VR client is a Windows build, and the viewer
> launches it directly, so every VR entry point refuses to start anywhere else
> rather than failing later on a missing `.exe`. The main program stays
> cross-platform, and its desktop viewer opens the same layout caches in 2D.
> This is why `opt_vr` ships `.bat` launchers and no `.sh` or `.app`
> counterparts.

Then install the VR client and the launcher shortcut:

```bat
opt_vr\install_vr.bat
```

This is the VR counterpart of the main program's `install.bat`, suffixed
like every other mirrored file here. It does two things:

- **Installs the VR client** into `player/`. The client is not in git: it is
  one asset of a GitHub release of this repository, and `player_release.json`
  pins which one, with its SHA-256. The installer downloads it, refuses it
  unless the checksum matches, and only then unpacks it. A client that is
  already the pinned version is left alone; `install_vr.bat --reinstall`
  replaces it anyway.
- **Writes `EMAP-SSN VR.lnk`** beside this README and offers to copy it to
  your Desktop. The shortcut sets the Python environment up on its first run,
  exactly as the `EMAP-SSN` and `EMAP-SSN Tools` shortcuts do, so that first
  launch takes noticeably longer than later ones.

Without network access, download the asset named in `player_release.json`
from the repository's releases page yourself, then:

```bat
set EMAPSSN_VR_CLIENT_ZIP=C:\path\to\EMAP-SSN-VR-Client-<version>-win64.zip
opt_vr\install_vr.bat
```

Updating needs nothing more than `git pull`. When the pin names a client that
`player/` does not hold, including on a first run with no client at all,
**Save & Run** installs it before starting it, with the same download and
checksum check. Offline, it starts whichever client is installed and says
which version the checkout expects.

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
├── install_vr.bat                       # installs the VR client, writes the shortcut
├── player_release.json                  # the client release to install, with its SHA-256
├── player/                              # the installed VR client (ignored)
├── Cache_Files/                         # runtime working directory (ignored)
├── viewer_settings_vr.json              # per-user settings (ignored)
├── docs/PROTOCOL.md                     # Python/VR client wire protocol
├── tools/                               # protocol reference client, fixtures, test servers
├── tests/
└── src/
    ├── _bootstrap_vr.py                 # sys.path and the Windows-only guard
    ├── EMAPSSN_Config_VR.py             # VR Configuration GUI
    ├── EMAPSSN_Viewer_VR.py             # VR viewer and VR client bridge
    ├── Settings_VR.py                   # Qt-free settings layer
    ├── Viewer_Utils_VR.py               # sequence and colour helpers
    ├── Player_Build_VR.py                # reads the installed client and the pin
    ├── Single_Instance_VR.py             # one VR viewer at a time
    ├── Detect_GPU_VR.py                  # can this machine drive a headset
    ├── Command_Compatibility_VR.py      # shared vs overridden command audit
    ├── Command_Engine.py                # name pinned: upstream imports it
    ├── Viewer_Command_Portal.py         # name pinned: upstream imports it
    ├── commands/                        # name pinned: upstream imports it
    └── bin/                             # launchers, startup handshake, client installer
```

## What lives here, and what does not

`opt_vr` contains **no part of the calculation pipeline.** Sequence
sanitization, embedding generation, alignment, network construction and layout
generation are all the main program's responsibility. This package:

- reads a layout cache published by `src/Layout_Cache_Generator.py`,
- rebuilds the edge list with the main program's own `prepare_network`, so VR
  edge filtering is identical to the desktop viewer's,
- streams that state to the VR client over a local socket, and
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
| `install_vr.bat` | installs the VR client, writes `EMAP-SSN VR.lnk` | `install.bat` |
| `src/bin/Install_Client_VR.ps1` | downloads, checks and unpacks the pinned client | — |
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
| VR client block on **Visual Effects** | host, port, distance scale, edge budget, client folder |
| removed controls | see below |
| distinct single-instance key | both windows can be open at once |

Four settings the desktop GUI offers are deliberately absent, because nothing
in the VR runtime reads them and no shared command does either:

| Removed | Why |
|---|---|
| `TEXT_SIZE`, `TEXT_COLOR` | no HUD text is drawn in the headset |
| `LOW_RESOURCE_MODE` | a VisPy canvas optimisation; the VR client does the drawing |
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
`z = 0` plane and a warning is printed. `save` is unavailable in that case,
because it would write 3D coordinates into a 2D layout folder. In a 3D session,
`save` writes a new version beside the cache the session opened.

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
keys (VR client host/port, edge-render budget) on top of the shared defaults in
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

That gap is worth stating plainly, because it is where the last round of drift
hid: `color`, `spectrum` and `export` each probed clean for months while
answering a different syntax from the desktop viewer's — `x2` against `2x`,
`prop:Length` against `{Length}`, `group:NAME` against `#NAME#`. Each accepted
exactly what upstream rejects by name. The probes cannot see that, so an
override needs a reason that survives being said out loud:

| Override | Why it cannot be shared |
| --- | --- |
| `agent`, `esmfold` | Driven end-to-end through the Viewer web server, which is out of scope for this port. Stubs that explain, instead of an AttributeError inside a web backend. |
| `zoom` | Drives a VisPy camera on a canvas this process has no equivalent of; the headset owns the viewpoint. |
| `print` | Upstream screen-grabs the canvas. A VR figure has to be rebuilt from the state arrays and projected onto a chosen plane, which is a different command. Disabled until that is designed. |
| `alignment`, `run` | Upstream opens a Qt file dialog. Identical once the file is chosen; the path is an argument here. |
| `export` | Upstream pops the system file manager through `desktop.Desktop_App`, which reaches PySide6. Otherwise a verbatim copy — keep it diffable. |
| `meta` | The web spreadsheet UI, and nothing else. Upload, download and column deletion are the main program's `Metadata_Core` functions, called directly. |

Anything not on that list is served from `src/commands`, so it cannot drift.

Where a command is overridden only because upstream's module reaches a toolkit,
the fix is to move the toolkit-free part somewhere both front ends can import
rather than to copy it. `src/Metadata_Core.py` in the parent checkout is that:
the metadata data model used to sit in `web_ui/meta_backend.py` behind a
module-level PySide6 import, so `meta` here could not upload, download or delete
without duplicating some four hundred lines. `meta_backend` re-exports every
name, so the desktop viewer is unchanged.

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

The VR client is covered from this side too. `test_protocol_v1.py` drives the
real server loop with a client written from `docs/PROTOCOL.md`;
`test_player_release.py` runs the client installer against fabricated
archives; and `test_player_integration.py` starts the installed player, the
way the viewer does, against the real server loop, and skips when `player/`
is empty. The client's own unit tests ship with its source.

## The VR client

The headset is driven by a separate program, the VR client, written with
[Godot Engine](https://godotengine.org) 4.7.2 and licensed Apache-2.0 like the
rest of the project. It speaks OpenXR, so it uses whichever runtime is active
(SteamVR, for example), and it has controller bindings for Windows Mixed Reality
and HP Reverb G2, Oculus and Meta Touch, Valve Index, HTC Vive and Cosmos, and
generic controllers, and the runtime supplies the model of whichever controller
is connected. Windows Mixed Reality controllers are the ones the client is
developed with; the other bindings follow each vendor's published controller
profile but have not been verified on hardware.

Its source is not in this repository. Every release carries the exact source
it was built from, so an installed client has its own under
`player/source/`, with instructions for building and testing it.

**How the two ends meet.** The viewer listens on **VR Client Host** and
**VR Client Port** (`127.0.0.1:5005` by default) and starts the client with that
endpoint on its command line:

```
player\EMAP-SSN-VR.exe -- --host 127.0.0.1 --port 5005 --restartable
```

so the two always agree, and any free port works. `--restartable` lets the
client ask to be started once more, which it does when SteamVR bound the
controllers before it knew them (see [docs/PROTOCOL.md](docs/PROTOCOL.md)). Once the client connects,
Python sends a binary handshake - the node count, positions (`float32` x, y,
z) and the rendered and full edge lists - and then both sides exchange
newline-delimited JSON: colour, size and visibility updates one way, the
network's transform the other. [docs/PROTOCOL.md](docs/PROTOCOL.md) is the
full contract.

The client also records a default endpoint in `player/vr_client.json`, used
only when it is started by hand. The Config GUI shows it in the tooltip of
the client fields, next to the endpoint **Save & Run** will pass.

**Developing without the viewer.** `tools/` holds what the client is tested
against: a reference client written from the protocol document
(`Protocol_V1_VR.py`), a generator for the byte-stream fixtures the client's own
tests read (`Protocol_Fixtures_VR.py`), a server that feeds random networks
through the real server loop (`Synthetic_Server_VR.py`), and a proxy that logs a
live session (`Protocol_Proxy_VR.py`).

## Hardware

Not every GPU that runs the main program can run this one. `src/Detect_GPU_VR.py`
answers that separately, because the main program's `Detect_GPU` is deciding
which PyTorch backend to install - a compute question whose answer does not
carry over. The VR client, not Python, is what renders to the headset.

| Vendor | VR | Notes |
|---|---|---|
| NVIDIA | yes | |
| AMD | yes | SteamVR's stated floor is roughly an RX 480. Expected to work with the Godot client (Vulkan and OpenXR are vendor-neutral), but not yet verified on AMD hardware |
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
the VR client, which is the moment an unsupported GPU actually bites.

What it deliberately does not do is judge whether the hardware is *fast
enough*. That depends on the headset, the scene and the network size, and a
checker that guessed would be wrong more often than useful.

## One viewer at a time

Two VR viewers cannot usefully coexist. They drive the same headset, and the
OpenXR runtime gives it to one application at a time; with the default
settings they also listen on the same endpoint. A second viewer does not give
a second view; it gives two processes fighting over one headset.

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

**Quit with VR Client**, at the bottom of the Visual Effects tab, decides what
happens when the headset app closes. On - the default - the viewer follows it
out rather than leaving an orphan holding the port. Off keeps the viewer and
its command console running, which is what you want while debugging the
client. The setting is stored as `EXIT_WITH_UNITY`, the name it had with the
Unity client, so saved settings and profiles keep working.

## Licence

Apache License 2.0 — see [LICENSE](LICENSE). This covers everything in this
repository and the VR client's own code. The client that `install_vr.bat`
downloads also contains Godot Engine (MIT) and the components compiled into
it, all under permissive terms: see
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md), which ships inside every
client release as well.

Revisions before the Godot client shipped a Unity-built player under
different terms. Its notices are in those revisions.
