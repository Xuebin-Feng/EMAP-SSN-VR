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
        <source>Folder containing the VR client (`EMAP-SSN-VR.exe`). Relative paths start in opt_vr.</source>
        <extracomment>Layout dimensionality is fixed: the VR viewer has no 2D mode, exactly as the desktop viewer has no 3D one. Settings that belong to the Python/VR client bridge. The desktop program has no equivalent, so they are declared here rather than in the shared schema. Settings the desktop viewer draws but the VR client does not. Keeping a control for them would invite tuning something with no effect: nothing in the VR runtime reads any of these, and no shared command does either. The bridge settings sit on the Visual Effects tab, so they share its profile group rather than forming one of their own.</extracomment>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>`install_vr.bat` installs the client in `player/`.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Local address where the Python viewer listens for the VR client.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Save &amp; Run passes it to the client it starts.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>TCP port where the Python viewer listens for the VR client (`1–65535`).</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Limits how many edges are sent to the VR client.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Reducing the rendered edges can improve VR performance.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Caps the edges sent to the VR client at Max Edges.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Sends all retained edges.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Maximum number of edges sent to the VR client when Limit Rendered Edges is ON.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Above this limit, the viewer samples edges with a preference for weaker connections. Zero sends no edges.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Spacing between the nodes in the headset; `1.0` keeps the layout&apos;s own spacing.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>The VR viewer starts at this value, and the two-hand gesture in the headset changes it during a session.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Whether the Python viewer quits with the VR client.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Closes the Python viewer when the VR client closes.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Keeps the viewer and its command console running for debugging.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Shape of the volume that disconnected components are packed into around the largest one: a cube for Square, a ball for Circle.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Components never land inside another one&apos;s enclosed space or in its narrow gaps.</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>How the 3D coordinates are computed: SSN simulates physics, while UMAP and PaCMAP compute them directly from each node&apos;s strongest edges.</source>
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
        <extracomment>The settings of VR&apos;s own tips (ConfigGUI._vr_control_tips).</extracomment>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Started by hand, it dials its default {host}:{port} instead.</source>
        <translation type="unfinished"></translation>
    </message>
</context>
<context>
    <name>Splash</name>
    <message>
        <source>VR Configuration</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>Checking VR hardware…</source>
        <translation type="unfinished"></translation>
    </message>
    <message>
        <source>EMAP-SSN VR Configuration will still open, but a headset may not work on this machine.</source>
        <translation type="unfinished"></translation>
    </message>
</context>
</TS>
