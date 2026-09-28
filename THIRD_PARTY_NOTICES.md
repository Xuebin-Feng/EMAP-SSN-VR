# Third-Party Notices

EMAP-SSN-VR's own code is licensed under the Apache License, Version 2.0 (see
[LICENSE](LICENSE)). That covers the Python sources in `src/`, the launchers,
the tests, the documentation, and the project's Unity scripts compiled into
`unity/EMAP-SSN-VR_Data/Managed/Assembly-CSharp.dll`.

The prebuilt Windows player in `unity/` also contains third-party components.
**The Apache License does not apply to them.** Each remains under its own
license, listed below, and none of them is relicensed by this project. Use of
the prebuilt player is also subject to [END_USER_NOTICE.md](END_USER_NOTICE.md),
which passes on the terms that Unity, Microsoft, and the Unity Asset Store
require.

The Python code runs in EMAP-SSN's managed environment and adds no Python
dependencies of its own. Those dependencies are inventoried in EMAP-SSN's
[THIRD_PARTY_LICENSES.md](https://github.com/Xuebin-Feng/EMAP-SSN/blob/main/THIRD_PARTY_LICENSES.md).

Last reviewed: 2026-09-28, against the Unity 6000.4.8f1 player build. Every
binary in `unity/` was identified from its version resource and, where
possible, by SHA-256 match against the Unity project's package cache.

---

## 1. Unity Runtime

| Component | Files | License |
|---|---|---|
| Unity Runtime 6000.4.8f1 | `EMAP-SSN-VR.exe`, `UnityPlayer.dll`, `UnityCrashHandler64.exe`, `EMAP-SSN-VR_Data/Managed/UnityEngine*.dll`, `Unity.Scripting.dll`, and the built-in resources in `EMAP-SSN-VR_Data/` | Proprietary: [Unity Editor Software Terms](https://unity.com/legal/editor-terms-of-service/software) and [Unity Terms of Service](https://unity.com/legal/terms-of-service) |

Copyright © 2005-2026 Unity Technologies. Unity is a trademark of Unity
Technologies.

- The Unity Runtime is distributed only embedded in this application (Unity
  Editor Software Terms §2.2). It may not be extracted and redistributed on
  its own.
- Third-party software inside the Unity Runtime, including the Mono runtime
  described in section 5, is listed in Unity's notice file for this exact
  player, "Player-Windows-Mono-6000.4.8f1", linked from the
  [Unity 6000.4.8f1 release page](https://unity.com/releases/editor/whats-new/6000.4.8f1).

## 2. Unity packages

These packages are compiled into the player. Each package's `LICENSE.md` is
authoritative.

| Package | Version | License | Files |
|---|---|---|---|
| AI Navigation | 2.0.12 | UCL | `Unity.AI.Navigation.dll` |
| Burst | 1.8.29 | Source UCL, otherwise UPDL | `Unity.Burst.dll`, `Unity.Burst.Unsafe.dll`, `Plugins/x86_64/lib_burst_generated.dll` |
| Collections | 6.4.0 | UCL | `Unity.Collections.dll`, `Unity.Collections.LowLevel.ILSupport.dll` |
| Input System | 1.19.0 | UCL | `Unity.InputSystem.dll`, `Unity.InputSystem.ForUI.dll` |
| Mathematics | 1.3.3 | UCL | `Unity.Mathematics.dll` |
| Multiplayer Center | 1.0.1 | UPDL | `Unity.Multiplayer.Center.Common.dll` |
| Core RP, Universal RP, Universal RP Config, Shader Graph | 17.4.0 | UCL | `Unity.RenderPipelines.*.dll`, `Unity.RenderPipeline.Universal.ShaderLibrary.dll`, `Unity.UnifiedRayTracing.Runtime.dll`, `Unity.PathTracing.Runtime.dll`, `Unity.SurfaceCache.Runtime.dll`, `Unity.InternalAPIEngineBridge.RenderPipelines.Core.Runtime.Shared.dll` |
| Timeline | 1.8.12 | UCL | `Unity.Timeline.dll` |
| uGUI, including TextMeshPro | 2.0.0 | UCL | `UnityEngine.UI.dll`, `Unity.TextMeshPro.dll`, `Unity.InternalAPIEngineBridge.004.dll` |
| Visual Scripting | 1.9.11 | UPDL | `Unity.VisualScripting.*.dll` |
| XR Core Utilities | 2.6.0 | UCL | `Unity.XR.CoreUtils.dll` |
| XR Interaction Toolkit | 3.5.0 | UCL | `Unity.XR.Interaction.Toolkit.dll` |
| XR Legacy Input Helpers | 3.0.1 | UCL | `UnityEngine.SpatialTracking.dll`, `UnityEngine.XR.LegacyInputHelpers.dll` |
| XR Plugin Management | 4.6.0 | UCL | `Unity.XR.Management.dll` |
| OpenXR Plugin | 1.16.1 | Source UCL, otherwise UPDL | `Unity.XR.OpenXR*.dll`, `Plugins/x86_64/UnityOpenXR.dll` |

- UCL: [Unity Companion License](https://unity.com/legal/licenses/unity-companion-license).
- UPDL: [Unity Package Distribution License](https://unity.com/legal/licenses/unity-package-distribution-license).
- All packages are copyright Unity Technologies.

### Third-party code inside Unity packages

As listed in each package's `Third Party Notices.md`. The table lists the
components that ship in the player's runtime assemblies, as determined by
scanning them. Each package's full notice also lists its editor-only
components.

| Package | Component | License | Copyright |
|---|---|---|---|
| Core RP | RadeonRays 4.1 | MIT | Copyright (c) 2021 Advanced Micro Devices, Inc. |
| Core RP | Sobol sampler | MIT | Copyright (c) 2023 Leonhard Gruenschloss |
| Core RP | Bullet Physics SDK (portions) | Zlib | see the package notice |
| Universal RP | `FXAA3_11.h` | NVIDIA FXAA3_11.h license | Copyright (c) 2014-2015, NVIDIA Corporation |
| XR Interaction Toolkit | Gesture code from the ARCore Unity ObjectManipulation example | Apache-2.0 | Copyright © 2017 Google Inc. |
| XR Legacy Input Helpers | `ArmModel`, `SwingArmModel`, `TransitionArmModel` | Apache-2.0 | Google; see the package notice |
| OpenXR Plugin | OpenXR-SDK-Source | Apache-2.0 | The Khronos Group Inc. |
| Visual Scripting | AQN Parser | MS-PL | Copyright © 2013 Christophe Bertrand |
| Visual Scripting | Full Serializer | MIT | Copyright © 2017 Jacob Dufault |
| Visual Scripting | Ensure.That | MIT | see the package notice |
| Visual Scripting | NCalc | MIT | see the package notice |
| Visual Scripting | ANTLR 3 C# runtime (`Unity.VisualScripting.Antlr3.Runtime.dll`) | BSD-3-Clause | Copyright (c) 2011 The ANTLR Project |
| Burst | LLVM, Mono.Cecil, Smash, xxHash, musl, SLEEF, gRPC for .NET, Google.Protobuf, mimalloc | Apache-2.0 WITH LLVM-exception, NCSA, MIT, BSD-2-Clause, BSL-1.0, Apache-2.0, BSD-3-Clause | see the package notice |

- The OpenXR Plugin notice also lists the Oculus OpenXR Mobile SDK, which is
  used only for Android builds. This player contains no Android binaries.
- The AQN Parser is under the Microsoft Public License (MS-PL). Its compiled
  form is distributed under MS-PL terms, and its notices are retained here.

## 3. Valve

The SteamVR Unity Plugin 2.8.0 (SDK 2.0.10) was obtained from the Unity Asset
Store and is used under the Standard Unity Asset Store EULA, which permits
distributing it only as incorporated in this application. Components inside
the asset that carry their own open-source licenses are governed by those
licenses (Asset Store EULA, Appendix 1 §2.7).

| Component | Version | Files | License | Copyright |
|---|---|---|---|---|
| SteamVR Unity Plugin | 2.8.0 | `SteamVR.dll`, `SteamVR_Actions.dll` (generated by the plugin), `StreamingAssets/SteamVR/*` | [Standard Unity Asset Store EULA](https://unity.com/legal/as-terms) | Copyright (c) Valve Corporation |
| Json.NET, bundled with the plugin | 9.0.1 | `Valve.Newtonsoft.Json.dll` | MIT | Copyright (c) 2007 James Newton-King; Copyright (c) 2016 SaladLab |
| OpenVR Unity XR Plugin, bundled with the plugin as a package | 1.2.1 | `Plugins/x86_64/XRSDKOpenVR.dll`, `Unity.XR.OpenVR.dll`, `UnitySubsystems/XRSDKOpenVR/*`, and the OpenVR SDK 2.0.10 loader `Plugins/x86_64/openvr_api.dll` | BSD-3-Clause | Copyright (c) Valve Corporation |
| JsonCpp (inside `openvr_api.dll`) | | | MIT (or public domain) | Copyright (c) 2007-2010 Baptiste Lepilleur |

## 4. Khronos Group

| Component | Version | Files | License | Copyright |
|---|---|---|---|---|
| OpenXR loader | 1.1.53 | `Plugins/x86_64/openxr_loader.dll` | Apache-2.0 OR MIT; used here under Apache-2.0, whose text is in [LICENSE](LICENSE) | Copyright (c) 2017-2025 The Khronos Group Inc. and others |
| jsoncpp (inside the loader) | 1.9.6 | | MIT (or public domain) | Copyright (c) 2007-2010 Baptiste Lepilleur and The JsonCpp Authors |

## 5. Mono

| Component | Files | License | Copyright |
|---|---|---|---|
| Mono runtime and class libraries (Unity fork) | `MonoBleedingEdge/EmbedRuntime/*`, `MonoBleedingEdge/etc/*`, `EMAP-SSN-VR_Data/Managed/mscorlib.dll`, `System*.dll`, `Mono.*.dll` | MIT ([source](https://github.com/Unity-Technologies/mono)) | Copyright (c) 2001-2003 Ximian, Inc.; Copyright (c) 2003-2010 Novell, Inc.; Copyright (c) 2012 Xamarin, Inc.; portions Copyright (c) Microsoft Corporation |
| Boehm-Demers-Weiser garbage collector (inside `mono-2.0-bdwgc.dll`) | | [Boehm-GC](https://spdx.org/licenses/Boehm-GC.html) | Hans-J. Boehm, Alan J. Demers, Xerox Corporation, Silicon Graphics, Inc., Hewlett-Packard Development Company, and others |

These components are part of Unity's player distribution and are also listed
in Unity's player notice file (section 1).

## 6. Microsoft

| Component | Version | Files | License |
|---|---|---|---|
| DirectX 12 Agility SDK runtime | 1.618.1 | `D3D12/D3D12Core.dll` | Microsoft Software License Terms – Microsoft DirectX, distributable code ([NuGet `Microsoft.Direct3D.D3D12`](https://www.nuget.org/packages/Microsoft.Direct3D.D3D12/1.618.1)) |
| DirectStorage runtime | 1.3.0 | `dstorage.dll`, `dstoragecore.dll` | Microsoft Software License Terms – Microsoft DirectStorage SDK, distributable code ([NuGet `Microsoft.Direct3D.DirectStorage`](https://www.nuget.org/packages/Microsoft.Direct3D.DirectStorage/1.3.0)) |
| System.IO.Hashing | 9.0.0 | `EMAP-SSN-VR_Data/Managed/System.IO.Hashing.dll` | MIT, Copyright (c) .NET Foundation and Contributors. Includes code derived from xxHash (BSD-2-Clause, Copyright (c) 2012-2021 Yann Collet), Intel ISA-L CRC (BSD-3-Clause, Copyright (c) 2011-2015 Intel Corporation), and ImageSharp (Apache-2.0, Copyright (c) Six Labors) |
| System.Runtime.CompilerServices.Unsafe | 6.0.0 | `EMAP-SSN-VR_Data/Managed/System.Runtime.CompilerServices.Unsafe.dll` | MIT, Copyright (c) .NET Foundation and Contributors |

The DirectX and DirectStorage files are the copies Unity ships with its
Windows player; Unity's player notice file lists them under MIT. Microsoft's
distributable-code terms require that they be distributed only as part of
this application, under terms at least as protective of Microsoft as its own.

## 7. Oniguruma

| Component | Files | License | Copyright |
|---|---|---|---|
| Oniguruma regular-expression library, via the Onigwrap wrapper | `Plugins/x86_64/libonigwrap.dll` | Oniguruma: BSD-2-Clause. Onigwrap: MIT | Oniguruma: Copyright (c) 2002-2021 K.Kosako. Onigwrap: Copyright (c) 2024 Aikawa Yataro |

This library comes from the Unity Version Control package (2.12.4, UPDL),
which uses it for editor syntax highlighting. Nothing in the player loads it.

---

## License texts

The Apache License 2.0 text is in [LICENSE](LICENSE). The standard texts of
the other permissive licenses named above follow. Each component's own
license file, linked or cited above, is authoritative. Proprietary and
Unity-specific terms are incorporated by the links in the sections above.

### MIT License

```text
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

### BSD 2-Clause License

```text
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
```

### BSD 3-Clause License

```text
Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice,
   this list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from this
   software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
POSSIBILITY OF SUCH DAMAGE.
```

### Other licenses, by reference

- Microsoft Public License (MS-PL): <https://opensource.org/license/ms-pl-html>
- Boehm-GC: <https://spdx.org/licenses/Boehm-GC.html>
- Zlib: <https://spdx.org/licenses/Zlib.html>
- NCSA: <https://spdx.org/licenses/NCSA.html>
- Boost Software License 1.0: <https://spdx.org/licenses/BSL-1.0.html>
- Apache-2.0 WITH LLVM-exception: <https://spdx.org/licenses/LLVM-exception.html>

---

## Maintenance

Review this file after every Unity rebuild, because package updates change
both the file list and the notices.

- Do not ship debug runtime DLLs. Microsoft does not permit redistributing
  them, and nothing in the player loads one. Valve's OpenVR Unity XR Plugin
  package contains the debug Universal C Runtime (`ucrtbased.dll`), enabled
  for Windows players, so remove it from every build.
- Keep editor-only and test-only libraries out of player builds. Examples are
  `libonigwrap.dll` (Unity Version Control, editor syntax highlighting) and
  the Collections test dependencies `System.IO.Hashing.dll` and
  `System.Runtime.CompilerServices.Unsafe.dll`. Nothing in the player
  references `System.IO.Hashing.dll`, and the `Unsafe` assembly is referenced
  only by it.
- Removing packages the project does not use shrinks this inventory. For
  example, the project's scripts do not reference Visual Scripting, which
  brings UPDL terms and the MS-PL AQN Parser.
