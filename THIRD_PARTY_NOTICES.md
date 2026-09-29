# Third-party notices

This file ships in two places: at the root of the
[EMAP-SSN-VR](https://github.com/Xuebin-Feng/EMAP-SSN-VR) repository, and inside
every VR client release, beside `EMAP-SSN-VR.exe`. It covers both.

**The repository** holds the Python bridge between EMAP-SSN and the headset,
its tests, tools and documentation. All of it is this project's own work under
the Apache License 2.0 (`LICENSE`); no third-party code is vendored. The Python
packages it imports come from the parent EMAP-SSN environment and are listed in
that project's `THIRD_PARTY_LICENSES.md`.

**The VR client** is not tracked in git. `install_vr.bat` downloads it from the
repository's GitHub releases into `player/`. Each release is one zip:

| File | What it is |
|---|---|
| `EMAP-SSN-VR.exe` | The player: this project's GDScript, shaders and scenes (Apache-2.0), packed into Godot Engine's official, unmodified Windows export template |
| `LICENSE`, `NOTICE` | The Apache License 2.0 and the client's notice |
| `THIRD_PARTY_NOTICES.md` | This file |
| `GODOT_LICENSE.txt` | Godot Engine's licence |
| `GODOT_COPYRIGHT.txt` | Every third-party component compiled into Godot, with its copyright holders and full licence text, written by the engine itself at export |
| `vr_client.json` | Build metadata: version, protocol, default endpoint, Godot version, source commit |
| `source/` | The complete source the player was built from |

Last reviewed: 2026-09-29, against Godot 4.7.2-stable.

## 1. Godot Engine

The player runs on [Godot Engine](https://godotengine.org) 4.7.2-stable. It uses
the official export template from the `godotengine/godot-builds` release of that
version, unmodified. No Direct3D 12 Agility SDK or ANGLE libraries are exported
beside it, so the player is a single executable.

```
Copyright (c) 2014-present Godot Engine contributors (see AUTHORS.md).
Copyright (c) 2007-2014 Juan Linietsky, Ariel Manzur.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## 2. Components compiled into Godot

Godot contains software by third parties, all under permissive licences or, for
one data file, the MPL-2.0. The engine reports the full list itself;
`GODOT_COPYRIGHT.txt` is that report, with every copyright holder and licence
text. Some entries are platform-specific (Android, Wayland, Metal, Direct3D) and
are not compiled into the Windows template; the engine lists them all, and so
does this file.

| Licence | Components |
|---|---|
| MIT (Expat) | Betsy, Chipmunk2D Joint Constraints, Jolt Physics, Joint Non-Local Means (JNLM) denoiser, Robert Penner's Easing Functions, Intel ASSAO, Temporal Anti-Aliasing resolve, Subpixel Morphological Antialiasing, AccessKit, AMD FidelityFX Super Resolution 1 and 2, Brotli, Convection Texture Tools Stand-Alone Kernels, D3D12 Memory Allocator, DirectX Headers, doctest, ENet, GamepadMotionHelpers, Graphite engine, meshoptimizer, bcdec, Fast Filtering of Reflection Probes, FastLZ, FastNoise Lite, NVIDIA NVAPI (minimal excerpt), OK Lab color space, PolyPartition / Triangulator, Quite OK Audio Format, Multi-channel signed distance field generator, SPIRV-Headers, ThorVG, ufbx, volk, Vulkan Memory Allocator, Wayland core protocol, Wayland protocols, Wslay, xatlas |
| Apache-2.0 | The Android Open Source Project, ProcessPhoenix, Arm ASTC Encoder, Basis Universal, Embree, DroidSans font, KTX, Manifold, Mbed TLS, metal-cpp, Minimal PCG32 implementation, OpenXR Loader, RVO2, SPIRV-Reflect, Swappy, Vulkan Headers |
| BSD-3-Clause | Open Dynamics Engine, ANGLE, etcpak, libbacktrace, OggVorbis, OggTheora, WebP codec, MiniUPnP Project, libjingle, SMAZ, PCRE2, hidapi, TinyEXR, V-HACD, Zstandard |
| zlib | libpng, MiniZip, Tangent Space Normal Maps implementation, Recast, SDL, zlib |
| OFL-1.1 | Inter, JetBrains Mono, Noto Sans, Open Sans and Vazirmatn fonts |
| BSD-2-Clause | mingw-std-threads, YUV2RGB |
| Unlicense or MIT | SMOL-V, stb libraries |
| Apache-2.0 or MIT | SPIRV-Cross |
| BSD-3-Clause and IJG | libjpeg-turbo |
| BSD-3-Clause and MIT | NVIDIA FXAA 3.11, simplified by Simon Rodriguez |
| MIT and Apache-2.0 | Grisu2 float serialization algorithm |
| MIT and zlib | Bullet Continuous Collision Detection and Physics Library |
| BSL-1.0 | Clipper2 |
| CC-BY-4.0 | Godot Engine logo, by Andrea Calabró |
| CC0-1.0 | Linux AppStream metadata file |
| CC0-1.0 and Apache-2.0 | glad |
| FreeType License | The FreeType Project |
| HarfBuzz (MIT-style) | HarfBuzz text shaping library |
| Unicode License | International Components for Unicode |
| Unlicense | r128 library |
| Unlicense or MIT-0 | dr_libs |
| X11 | Mesa Wayland protocols |
| glslang (BSD-3-Clause and others) | glslang |
| MPL-2.0 | CA certificates (see below) |

**CA certificates (MPL-2.0).** Godot compiles in Mozilla's bundle of root
certificates for its TLS support. The VR client makes no TLS connections, but
the bundle is part of the engine. Its source form is
[`thirdparty/certs/ca-bundle.crt`](https://github.com/godotengine/godot/blob/4.7.2-stable/thirdparty/certs/ca-bundle.crt)
in the Godot 4.7.2-stable source. The certificates come from Mozilla's
[root store](https://wiki.mozilla.org/CA/Included_Certificates) (copyright
Mozilla Contributors).

## 3. What the player does not contain

- **No Godot addons** and no Asset Library content. Only the engine is used.
- **No controller models or runtime.** Controller models are supplied at run
  time by the user's OpenXR runtime (for example SteamVR), which is installed
  separately under its own terms. The OpenXR loader compiled into Godot is the
  only OpenXR code in the player.
- **No Unity, Microsoft, Valve or Unity Asset Store components.** Revisions of
  this repository before the Godot client shipped a Unity-built player instead;
  its notices are in `THIRD_PARTY_NOTICES.md` and `END_USER_NOTICE.md` of those
  revisions.

## 4. Keeping this file current

Review it whenever the client moves to another Godot version. The export
rewrites `GODOT_LICENSE.txt` and `GODOT_COPYRIGHT.txt` from the engine it runs
on; update section 2 and the version above to match.
