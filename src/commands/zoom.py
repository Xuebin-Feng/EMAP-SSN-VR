"""Explain that zooming belongs to the headset, instead of crashing.

Deliberately shadows the main program's ``zoom``, which drives a VisPy camera
that does not exist in this process.
"""

import Command_Engine


def run(viewer, args):
    msg = ("zoom is not available in the VR viewer.\n"
           "Reason: zoom drives the desktop viewer's VisPy camera (viewer.view.camera on a\n"
           "  canvas). The VR process is headless and has no canvas or camera: the headset\n"
           "  owns the viewpoint, and node positions are sent once in the binary handshake.\n"
           "Instead:\n"
           "  - Move, or use the controller grip/scale gesture in the Unity client, to zoom.\n"
           "  - hide / select   Narrow the network down to the nodes you care about.\n"
           "  - reset hide      Bring every hidden node back.")
    Command_Engine.print_help(viewer, msg)
