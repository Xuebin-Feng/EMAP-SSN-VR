<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" sourcelanguage="en">
<context>
    <name>Config</name>
    <message>
        <source>EMAP-SSN VR Configuration</source>
        <extracomment>This window configures the VR front end, so it names itself accordingly rather than borrowing the desktop program&apos;s display names.</extracomment>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>VR Client Build: Folder containing the VR client (EMAP-SSN-VR.exe). Relative paths start in opt_vr.
install_vr.bat installs the client in player/.</source>
        <extracomment>VR&apos;s own tips; the window translates them (translate(&quot;Config&quot;, tip)).</extracomment>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>VR Client Host: Local address where the Python viewer listens for the VR client.
Save &amp; Run passes it to the client it starts.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>VR Client Port: TCP port where the Python viewer listens for the VR client (1–65535).
Save &amp; Run passes it to the client it starts.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Limit Rendered Edges: ON caps the edges sent to the VR client at Max Edges; OFF sends all retained edges.
Reducing the rendered edges can improve VR performance.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Max Edges: Maximum number of edges sent to the VR client when Limit Rendered Edges is ON.
Above this limit, the viewer samples edges with a preference for weaker connections. Zero sends no edges.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Distance Scale: Spacing between the nodes in the headset; 1.0 keeps the layout&apos;s own spacing.
The VR viewer starts at this value, and the two-hand gesture in the headset changes it during a session.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Quit with VR Client: ON closes the Python viewer when the VR client closes.
OFF keeps the viewer and its command console running for debugging.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Saved Config: Selects the settings profile used for this tab.
(custom) uses the current viewer_settings_vr.json values; (default) uses read-only built-in defaults; (new) creates a named profile; named entries load profiles from the Saved Config Directory.</source>
        <extracomment>Layout dimensionality is fixed: the VR viewer has no 2D mode, exactly as the desktop viewer has no 3D one. Settings that belong to the Python/VR client bridge. The desktop program has no equivalent, so they are declared here rather than in the shared schema. Settings the desktop viewer draws but the VR client does not. Keeping a control for them would invite tuning something with no effect: nothing in the VR runtime reads any of these, and no shared command does either. The bridge settings sit on the Visual Effects tab, so they share its profile group rather than forming one of their own.</extracomment>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Selects a pre-computed 3D layout coordinate cache file (.h5) from the cache directory.
Instantly restores previously computed node positions to bypass physics simulation.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Minimum gap kept between independent clusters as they are packed onto concentric spherical shells around the largest one.
Larger values spread the packed clusters further apart in the final 3D layout.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Uses UMAP manifold learning to compute 3D coordinates directly from sequence distances.
Provides fast non-linear dimensionality reduction as an alternative to iterative physics simulations.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Directory where calculated 3D layout coordinate files and network metadata (.h5) are saved and loaded.
Serves as the layout cache to avoid recalculating layouts when reopening networks.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Quit with VR Client:</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Browse</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>VR Client Build Directory</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>VR Client Build:</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>VR Client Host:</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>VR Client Port:</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Limit Rendered Edges:</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Max Edges:</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Distance Scale:</source>
        <translation type="unfinished"></translation>
    </message>
</context>
<context>
    <name>Message</name>
    <message>
        <source>No VR client is installed in this folder (vr_client.json is missing or unreadable). Save &amp; Run downloads the pinned release into player/, as install_vr.bat does; or choose the folder that holds EMAP-SSN-VR.exe.</source>
        <extracomment>VR Config&apos;s own texts are in opt_vr&apos;s catalog, emapssn_vr; the texts it shares with the desktop Config come from the main catalog. The window and taskbar icon is opt_vr&apos;s own logo, the parent&apos;s Config logo with a VR headset. The parent&apos;s Config logo stands in if it is missing. The VR client connection tooltip. The viewer passes VR Client Host and Port to the client it launches, so the two ends always agree; the endpoint recorded in the build is only where a client started by hand dials. The notes are Messages: str() is English, and the window shows display_text().</extracomment>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>This folder holds an executable but no vr_client.json, so it is not an EMAP-SSN-VR client release (a Unity-era build, for example). Save &amp; Run starts it as it is and installs nothing. Choose player to use the pinned client, which install_vr.bat and Save &amp; Run install there.</source>
        <extracomment>The chosen folder holds an executable but no vr_client.json, so it is no EMAP-SSN-VR client release - typically a Unity-era build a saved profile still names. Save &amp; Run starts it as it is and installs nothing, so the download promise of BRIDGE_NOTE_MISSING would be wrong here.</extracomment>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Save &amp; Run starts this VR client dialling {host}:{port}.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Started by hand, it dials its default {host}:{port} instead.</source>
        <translation type="unfinished"></translation>
    </message>
</context>
</TS>
