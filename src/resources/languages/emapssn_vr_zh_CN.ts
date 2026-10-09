<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="zh_CN" sourcelanguage="en">
<context>
    <name>Config</name>
    <message>
        <location filename="../../EMAPSSN_Config_VR.py" line="+65"/>
        <source>EMAP-SSN VR Configuration</source>
        <extracomment>This window configures the VR front end, so it names itself accordingly rather than borrowing the desktop program&apos;s display names.</extracomment>
        <translation type="unfinished">EMAP-SSN VR 配置</translation>
    </message>
    <message>
        <location line="+63"/>
        <source>VR Client Build: Folder containing the VR client (EMAP-SSN-VR.exe). Relative paths start in opt_vr.
install_vr.bat installs the client in player/.</source>
        <extracomment>VR&apos;s own tips; the window translates them (translate(&quot;Config&quot;, tip)).</extracomment>
        <translation type="unfinished">VR 客户端构建：存放 VR 客户端（EMAP-SSN-VR.exe）的文件夹。相对路径从 opt_vr 开始。
install_vr.bat 会把客户端安装到 player/ 中。</translation>
    </message>
    <message>
        <location line="+1"/>
        <source>VR Client Host: Local address where the Python viewer listens for the VR client.
Save &amp; Run passes it to the client it starts.</source>
        <translation type="unfinished">VR 客户端主机：Python 查看器监听 VR 客户端连接的本地地址。
“保存并运行”会把它传给所启动的客户端。</translation>
    </message>
    <message>
        <location line="+1"/>
        <source>VR Client Port: TCP port where the Python viewer listens for the VR client (1–65535).
Save &amp; Run passes it to the client it starts.</source>
        <translation type="unfinished">VR 客户端端口：Python 查看器监听 VR 客户端连接的 TCP 端口（1–65535）。
“保存并运行”会把它传给所启动的客户端。</translation>
    </message>
    <message>
        <location line="+1"/>
        <source>Limit Rendered Edges: ON caps the edges sent to the VR client at Max Edges; OFF sends all retained edges.
Reducing the rendered edges can improve VR performance.</source>
        <translation type="unfinished">限制绘制的边：开启时，发送给 VR 客户端的边不超过“最大边数”；关闭时发送所有保留的边。
减少绘制的边可以提高 VR 性能。</translation>
    </message>
    <message>
        <location line="+1"/>
        <source>Max Edges: Maximum number of edges sent to the VR client when Limit Rendered Edges is ON.
Above this limit, the viewer samples edges with a preference for weaker connections. Zero sends no edges.</source>
        <translation type="unfinished">最大边数：开启“限制绘制的边”时，发送给 VR 客户端的最大边数。
超过此上限时，查看器会抽样选取边，并优先选择较弱的连接。设为 0 则不发送任何边。</translation>
    </message>
    <message>
        <location line="+1"/>
        <source>Distance Scale: Spacing between the nodes in the headset; 1.0 keeps the layout&apos;s own spacing.
The VR viewer starts at this value, and the two-hand gesture in the headset changes it during a session.</source>
        <translation type="unfinished">距离缩放：头显中节点之间的间距；1.0 保持布局本身的间距。
VR 查看器从此值开始，在会话中可用头显里的双手手势调整。</translation>
    </message>
    <message>
        <location line="+1"/>
        <source>Quit with VR Client: ON closes the Python viewer when the VR client closes.
OFF keeps the viewer and its command console running for debugging.</source>
        <translation type="unfinished">随 VR 客户端退出：开启时，VR 客户端关闭后也关闭 Python 查看器。
关闭时，查看器及其命令控制台会继续运行，便于调试。</translation>
    </message>
    <message>
        <location line="+1843"/>
        <source>Saved Config: Selects the settings profile used for this tab.
(custom) uses the current viewer_settings_vr.json values; (default) uses read-only built-in defaults; (new) creates a named profile; named entries load profiles from the Saved Config Directory.</source>
        <extracomment>Layout dimensionality is fixed: the VR viewer has no 2D mode, exactly as the desktop viewer has no 3D one. Settings that belong to the Python/VR client bridge. The desktop program has no equivalent, so they are declared here rather than in the shared schema. Settings the desktop viewer draws but the VR client does not. Keeping a control for them would invite tuning something with no effect: nothing in the VR runtime reads any of these, and no shared command does either. The bridge settings sit on the Visual Effects tab, so they share its profile group rather than forming one of their own.</extracomment>
        <translation type="unfinished">已保存配置：选择此选项卡使用的设置配置方案。
（自定义）使用当前 viewer_settings_vr.json 中的值；（默认）使用只读的内置默认值；（新建）创建一个命名的配置方案；其他命名条目从已保存配置目录加载配置方案。</translation>
    </message>
    <message>
        <location line="+12"/>
        <source>Selects a pre-computed 3D layout coordinate cache file (.h5) from the cache directory.
Instantly restores previously computed node positions to bypass physics simulation.</source>
        <translation type="unfinished">从缓存目录中选择预先计算的三维布局坐标缓存文件（.h5）。
可立即恢复先前计算的节点位置，从而跳过物理模拟。</translation>
    </message>
    <message>
        <location line="+27"/>
        <source>Minimum gap kept between independent clusters as they are packed onto concentric spherical shells around the largest one.
Larger values spread the packed clusters further apart in the final 3D layout.</source>
        <translation type="unfinished">将独立的簇排布到围绕最大簇的同心球壳上时，簇之间保留的最小间隙。
数值越大，最终三维布局中排布的簇相距越远。</translation>
    </message>
    <message>
        <location line="+1"/>
        <source>Uses UMAP manifold learning to compute 3D coordinates directly from sequence distances.
Provides fast non-linear dimensionality reduction as an alternative to iterative physics simulations.</source>
        <translation type="unfinished">使用 UMAP 流形学习直接根据序列距离计算三维坐标。
提供快速的非线性降维，可替代迭代式物理模拟。</translation>
    </message>
    <message>
        <location line="+6"/>
        <source>Directory where calculated 3D layout coordinate files and network metadata (.h5) are saved and loaded.
Serves as the layout cache to avoid recalculating layouts when reopening networks.</source>
        <translation type="unfinished">保存和加载计算得到的三维布局坐标文件及网络元数据（.h5）的目录。
作为布局缓存，重新打开网络时无需重新计算布局。</translation>
    </message>
    <message>
        <location line="+1930"/>
        <source>Quit with VR Client:</source>
        <translation type="unfinished">随 VR 客户端退出：</translation>
    </message>
    <message>
        <location line="+46"/>
        <source>Browse</source>
        <translation type="unfinished">浏览</translation>
    </message>
    <message>
        <location line="+9"/>
        <source>VR Client Build Directory</source>
        <translation type="unfinished">VR 客户端构建目录</translation>
    </message>
    <message>
        <location line="+20"/>
        <source>VR Client Build:</source>
        <translation type="unfinished">VR 客户端构建：</translation>
    </message>
    <message>
        <location line="+5"/>
        <source>VR Client Host:</source>
        <translation type="unfinished">VR 客户端主机：</translation>
    </message>
    <message>
        <location line="+1"/>
        <source>VR Client Port:</source>
        <translation type="unfinished">VR 客户端端口：</translation>
    </message>
    <message>
        <location line="+20"/>
        <source>Limit Rendered Edges:</source>
        <translation type="unfinished">限制绘制的边：</translation>
    </message>
    <message>
        <location line="+5"/>
        <source>Max Edges:</source>
        <translation type="unfinished">最大边数：</translation>
    </message>
    <message>
        <location line="+4"/>
        <source>Distance Scale:</source>
        <translation type="unfinished">距离缩放：</translation>
    </message>
</context>
<context>
    <name>Message</name>
    <message>
        <location line="-3968"/>
        <source>No VR client is installed in this folder (vr_client.json is missing or unreadable). Save &amp; Run downloads the pinned release into player/, as install_vr.bat does; or choose the folder that holds EMAP-SSN-VR.exe.</source>
        <extracomment>VR Config&apos;s own texts are in opt_vr&apos;s catalog, emapssn_vr; the texts it shares with the desktop Config come from the main catalog. The window and taskbar icon is opt_vr&apos;s own logo, the parent&apos;s Config logo with a VR headset. The parent&apos;s Config logo stands in if it is missing. The VR client connection tooltip. The viewer passes VR Client Host and Port to the client it launches, so the two ends always agree; the endpoint recorded in the build is only where a client started by hand dials. The notes are Messages: str() is English, and the window shows display_text().</extracomment>
        <translation type="unfinished">此文件夹中没有安装 VR 客户端（vr_client.json 不存在或无法读取）。“保存并运行”会像 install_vr.bat 一样把指定版本下载到 player/ 中；也可以选择存放 EMAP-SSN-VR.exe 的文件夹。</translation>
    </message>
    <message>
        <location line="+10"/>
        <source>This folder holds an executable but no vr_client.json, so it is not an EMAP-SSN-VR client release (a Unity-era build, for example). Save &amp; Run starts it as it is and installs nothing. Choose player to use the pinned client, which install_vr.bat and Save &amp; Run install there.</source>
        <extracomment>The chosen folder holds an executable but no vr_client.json, so it is no EMAP-SSN-VR client release - typically a Unity-era build a saved profile still names. Save &amp; Run starts it as it is and installs nothing, so the download promise of BRIDGE_NOTE_MISSING would be wrong here.</extracomment>
        <translation type="unfinished">此文件夹中有可执行文件，但没有 vr_client.json，因此不是 EMAP-SSN-VR 客户端的发布版本（例如 Unity 时期的构建）。“保存并运行”会原样启动它，不安装任何内容。请选择 player 以使用指定版本的客户端，install_vr.bat 和“保存并运行”都会把它安装在那里。</translation>
    </message>
    <message>
        <location line="+38"/>
        <source>Save &amp; Run starts this VR client dialling {host}:{port}.</source>
        <translation type="unfinished">“保存并运行”会启动此 VR 客户端，连接 {host}:{port}。</translation>
    </message>
    <message>
        <location line="+2"/>
        <source>Started by hand, it dials its default {host}:{port} instead.</source>
        <translation type="unfinished">如果手动启动，它会改为连接默认的 {host}:{port}。</translation>
    </message>
</context>
</TS>
