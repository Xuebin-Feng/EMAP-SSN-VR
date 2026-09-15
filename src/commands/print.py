# Copyright 2026 Xuebin Feng
# Author affiliation: University of Toronto
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Export the current network state as a publication figure.

The main program's ``print`` renders the VisPy canvas: it reads
``viewer.canvas``, drives ``viewer.view.camera`` and calls ``canvas.render()``
to grab pixels. None of that exists here - the VR viewer is headless and the
headset owns the camera - so the upstream command dies with an AttributeError
before writing anything.

Figures are still worth having: a user who spends a session colouring,
clustering and hiding nodes in VR needs a way to take that state into a paper.
So this version rebuilds the picture from the state arrays instead of
screen-grabbing it. Everything it needs - ``pos``, ``current_colors``,
``current_sizes``, ``current_shapes``, ``visible_mask`` and ``edges`` - is
plain data on the viewer, so the export works with no renderer, no window and
no Unity client attached.

Two consequences of not being a screenshot, both deliberate:

* The layout is three dimensional, so a flat figure needs a projection plane.
  ``xy`` (the default), ``xz`` and ``yz`` are offered; the chosen plane is
  recorded in the file so a figure cannot be misread as "the" 2D layout.
* The framing comes from the data bounds, not from wherever the headset
  happens to be pointing, so the same state always prints the same figure.
  There is nothing to tile, which is why upstream's ``full`` modifier is
  rejected rather than silently ignored.
"""

import datetime
import math
import os

import numpy as np

import Command_Engine
import Settings_VR as cfg
import Viewer_Utils_VR as utils

#: Fraction of the bounding box added as a margin on each side.
PADDING_FRACTION = 0.05
MINIMUM_PADDING = 5.0

#: PNG raster geometry. The figure is laid out in world units and only then
#: scaled, so node diameters keep the proportions they have in the SVG.
PNG_FIGURE_WIDTH_INCHES = 10.0
PNG_DPI = 300

PLANES = {
    "xy": (0, 1, "X", "Y"),
    "xz": (0, 2, "X", "Z"),
    "yz": (1, 2, "Y", "Z"),
}

#: Shapes drawn as strokes only; a fill would collapse them to a blob.
STROKE_ONLY_SHAPES = ("cross", "+", "x", "vbar", "|", "hbar", "-", "_", "ring")

#: matplotlib markers that have no interior. It colours these through the
#: FACE colour and warns if an edge colour is supplied, which is the opposite
#: of the SVG convention, so they are separated out.
UNFILLED_MARKERS = ("+", "x", "|", "_")

#: Upstream shape vocabulary mapped onto matplotlib markers for PNG output.
MATPLOTLIB_MARKERS = {
    "circle": "o", "disc": "o", "o": "o", "ring": "o",
    "square": "s", "s": "s",
    "triangle": "^", "triangle_up": "^", "^": "^",
    "triangle_down": "v", "v": "v",
    "diamond": "D", "D": "D",
    "star": "*", "*": "*",
    "cross": "+", "+": "+",
    "x": "x",
    "vbar": "|", "|": "|",
    "hbar": "_", "-": "_", "_": "_",
    "arrow": ">", "tailed_arrow": ">", "->": ">", ">": ">",
    "clobber": "p", "p": "p",
    "cross_lines": "P", "P": "P", "++": "P",
}

HELP_TEXT = """Usage: print [FILENAME] [PLANE] [MODIFIERS]
       print help

Description:
  Writes the current network state - colours, sizes, shapes, visibility and
  the edges between visible nodes - to a figure beneath the Analysis Results
  directory (Saved_Images/). The figure is rebuilt from the layout data, not
  captured from a screen, so it does not depend on the headset view and is
  reproducible from the same state.

Plane (default: xy):
  xy | xz | yz  Which pair of layout axes to project onto. The layout is 3D;
                the plane used is written into the file as a comment.

Modifiers:
  svg          Vector output (default). Layered edges and nodes, one element
               per node, suitable for editing in Illustrator or Inkscape.
  png          Raster output at 300 dpi. Requires matplotlib.
  transparent  Omit the background, leaving the page showing through.

Not supported here:
  full         Upstream stitches camera tiles to beat OpenGL edge-clipping.
               There is no camera and no renderer in the VR viewer, and the
               vector export has no resolution limit, so tiling is moot.

Examples:
  print                          (timestamped SVG of the xy projection)
  print my_network               (my_network.svg)
  print my_network xz            (projected onto the x/z plane)
  print my_network transparent   (no background rectangle)
  print my_network png           (300 dpi raster instead of vector)
"""


def _output_directory():
    base = getattr(cfg, "ANALYSIS_RESULT_DIR", None) or os.path.join(
        getattr(cfg, "PROJECT_ROOT", "."), "Analysis_Results"
    )
    return os.path.join(base, "Saved_Images")


def _default_basename():
    name = getattr(cfg, "SEQUENCE_SET", None)
    if not name:
        try:
            name = utils.get_base_network_name()
        except Exception:
            name = None
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{name or 'Network'}_{stamp}"


def _svg_rgb(triple):
    """``rgb(r,g,b)`` with no spaces, which is what Illustrator expects."""
    red, green, blue = triple
    return f"rgb({red},{green},{blue})"


def _rgb_255(value, fallback=(0, 0, 0)):
    """Accept a hex string, an RGB(A) sequence or nothing, return 0-255."""
    if isinstance(value, str):
        try:
            rgba = utils.hex_to_rgba(value)
        except Exception:
            return fallback
        return tuple(int(round(float(channel) * 255)) for channel in rgba[:3])
    if value is None:
        return fallback
    try:
        return tuple(int(round(float(channel) * 255)) for channel in value[:3])
    except (TypeError, ValueError):
        return fallback


def _rgb_unit(value, fallback=(0.0, 0.0, 0.0)):
    red, green, blue = _rgb_255(
        value, tuple(int(round(channel * 255)) for channel in fallback)
    )
    return (red / 255.0, green / 255.0, blue / 255.0)


def _projected_positions(viewer, plane):
    """The visible nodes' coordinates on the requested plane."""
    positions = np.asarray(viewer.pos, dtype=np.float64)
    if positions.ndim != 2 or positions.shape[1] < 2:
        return None, "Error: viewer.pos does not hold 2D or 3D coordinates."

    first_axis, second_axis = PLANES[plane][0], PLANES[plane][1]
    if positions.shape[1] <= max(first_axis, second_axis):
        return None, (
            f"Error: the layout has {positions.shape[1]} axes, so the "
            f"'{plane}' plane does not exist. Use 'xy'."
        )
    return positions[:, (first_axis, second_axis)], None


def _bounds(viewer, points):
    """Framing for the visible nodes only, so hiding reframes the figure.

    The margin also clears the widest node's radius: the bounds are centres,
    and a large node centred on the edge of the cloud would otherwise be cut
    in half by the viewport.
    """
    visible = np.flatnonzero(viewer.visible_mask)
    shown = points[visible]
    minimum = np.min(shown, axis=0)
    maximum = np.max(shown, axis=0)
    span = maximum - minimum
    radius = float(np.max(np.asarray(viewer.current_sizes)[visible])) / 2.0
    pad_x = max(float(span[0]) * PADDING_FRACTION, MINIMUM_PADDING) + radius
    pad_y = max(float(span[1]) * PADDING_FRACTION, MINIMUM_PADDING) + radius
    left = float(minimum[0]) - pad_x
    right = float(maximum[0]) + pad_x
    bottom = float(minimum[1]) - pad_y
    top = float(maximum[1]) + pad_y
    return left, right, bottom, top


def _visible_edges(viewer):
    edges = getattr(viewer, "edges", None)
    if edges is None or len(edges) == 0:
        return np.empty((0, 2), dtype=np.int32)
    edges = np.asarray(edges)
    keep = viewer.visible_mask[edges[:, 0]] & viewer.visible_mask[edges[:, 1]]
    return edges[keep]


def _node_polygon(shape, centre_x, centre_y, radius):
    """Vertices for the polygonal shapes, or None for non-polygons."""
    if shape in ("square", "s"):
        return [
            (centre_x - radius, centre_y - radius),
            (centre_x + radius, centre_y - radius),
            (centre_x + radius, centre_y + radius),
            (centre_x - radius, centre_y + radius),
        ]
    if shape in ("triangle", "triangle_up", "^"):
        return [
            (centre_x, centre_y - radius),
            (centre_x + 0.866 * radius, centre_y + 0.5 * radius),
            (centre_x - 0.866 * radius, centre_y + 0.5 * radius),
        ]
    if shape in ("triangle_down", "v"):
        return [
            (centre_x, centre_y + radius),
            (centre_x + 0.866 * radius, centre_y - 0.5 * radius),
            (centre_x - 0.866 * radius, centre_y - 0.5 * radius),
        ]
    if shape in ("diamond", "D"):
        return [
            (centre_x, centre_y - radius),
            (centre_x + radius, centre_y),
            (centre_x, centre_y + radius),
            (centre_x - radius, centre_y),
        ]
    if shape in ("arrow", "tailed_arrow", "->", ">"):
        return [
            (centre_x + radius, centre_y),
            (centre_x - 0.5 * radius, centre_y - 0.866 * radius),
            (centre_x - 0.5 * radius, centre_y + 0.866 * radius),
        ]
    if shape in ("star", "*"):
        points = []
        for step in range(10):
            angle = -math.pi / 2.0 + step * math.pi / 5.0
            length = radius if step % 2 == 0 else radius * 0.4
            points.append(
                (centre_x + length * math.cos(angle),
                 centre_y + length * math.sin(angle))
            )
        return points
    if shape in ("clobber", "p"):
        points = []
        for step in range(5):
            angle = -math.pi / 2.0 + step * 2.0 * math.pi / 5.0
            points.append(
                (centre_x + radius * math.cos(angle),
                 centre_y + radius * math.sin(angle))
            )
        return points
    return None


def _write_svg(viewer, filepath, points, plane, transparent):
    """Rebuild the visible network as a layered SVG."""
    left, right, bottom, top = _bounds(viewer, points)
    width = right - left
    height = top - bottom
    if width <= 0:
        width = 1.0
    if height <= 0:
        height = 1.0

    def to_svg(x_value, y_value):
        # SVG y grows downward; flip so +Y still points up in the figure.
        return x_value - left, top - y_value

    visible = viewer.visible_mask
    colors = viewer.current_colors
    sizes = viewer.current_sizes
    shapes = viewer.current_shapes

    edge_rgb = _rgb_255(getattr(cfg, "EDGE_COLOR", "#000000"))
    edge_alpha = float(getattr(cfg, "EDGE_ALPHA", 0.1))
    edge_width = float(getattr(cfg, "EDGE_WIDTH", 1.0))
    boundary_rgb = _rgb_255(getattr(cfg, "NODE_BOUNDARY_COLOR", "#000000"))

    _, _, first_label, second_label = PLANES[plane]
    lines = [
        '<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width:.3f} {height:.3f}" '
        f'width="{width:.3f}" height="{height:.3f}">',
        f'  <!-- EMAP-SSN VR export: {first_label}/{second_label} projection '
        f'of a 3D layout -->',
    ]

    if not transparent:
        lines.append('  <!-- Background -->')
        lines.append(
            f'  <rect width="{width:.3f}" height="{height:.3f}" '
            f'fill="rgb(255,255,255)" />'
        )

    edges = _visible_edges(viewer)
    lines.append('  <!-- Edges -->')
    lines.append('  <g id="edges" name="Edges">')
    for source, target in edges:
        x1, y1 = to_svg(points[source, 0], points[source, 1])
        x2, y2 = to_svg(points[target, 0], points[target, 1])
        lines.append(
            f'    <line x1="{x1:.3f}" y1="{y1:.3f}" '
            f'x2="{x2:.3f}" y2="{y2:.3f}" '
            f'stroke="{_svg_rgb(edge_rgb)}" stroke-opacity="{edge_alpha:.3f}" '
            f'stroke-width="{edge_width:.3f}" />'
        )
    lines.append('  </g>')

    lines.append('  <!-- Nodes -->')
    lines.append('  <g id="nodes" name="Nodes">')
    for index in np.flatnonzero(visible):
        centre_x, centre_y = to_svg(points[index, 0], points[index, 1])
        diameter = float(sizes[index])
        radius = diameter / 2.0
        shape = shapes[index]
        red, green, blue, alpha = [float(channel) for channel in colors[index]]
        fill = (
            f'fill="rgb({int(red * 255)},{int(green * 255)},{int(blue * 255)})" '
            f'fill-opacity="{alpha:.3f}"'
        )

        if shape in STROKE_ONLY_SHAPES:
            attributes = (
                f'fill="none" '
                f'stroke="rgb({int(red * 255)},{int(green * 255)},'
                f'{int(blue * 255)})" stroke-opacity="{alpha:.3f}" '
                f'stroke-width="{radius * 0.4:.3f}"'
            )
        else:
            attributes = (
                f'{fill} stroke="{_svg_rgb(boundary_rgb)}" stroke-width="0.5"'
            )

        if shape in ("cross", "+"):
            lines.append(
                f'    <path d="M {centre_x - radius:.3f} {centre_y:.3f} '
                f'L {centre_x + radius:.3f} {centre_y:.3f} '
                f'M {centre_x:.3f} {centre_y - radius:.3f} '
                f'L {centre_x:.3f} {centre_y + radius:.3f}" {attributes} />'
            )
            continue
        if shape == "x":
            offset = 0.707 * radius
            lines.append(
                f'    <path d="M {centre_x - offset:.3f} '
                f'{centre_y - offset:.3f} L {centre_x + offset:.3f} '
                f'{centre_y + offset:.3f} M {centre_x - offset:.3f} '
                f'{centre_y + offset:.3f} L {centre_x + offset:.3f} '
                f'{centre_y - offset:.3f}" {attributes} />'
            )
            continue
        if shape in ("vbar", "|"):
            lines.append(
                f'    <line x1="{centre_x:.3f}" y1="{centre_y - radius:.3f}" '
                f'x2="{centre_x:.3f}" y2="{centre_y + radius:.3f}" '
                f'{attributes} />'
            )
            continue
        if shape in ("hbar", "-", "_"):
            lines.append(
                f'    <line x1="{centre_x - radius:.3f}" y1="{centre_y:.3f}" '
                f'x2="{centre_x + radius:.3f}" y2="{centre_y:.3f}" '
                f'{attributes} />'
            )
            continue
        if shape in ("cross_lines", "P", "++"):
            arm = radius * 0.4
            lines.append(
                f'    <path d="M {centre_x - radius:.3f} {centre_y - arm:.3f} '
                f'H {centre_x - arm:.3f} V {centre_y - radius:.3f} '
                f'H {centre_x + arm:.3f} V {centre_y - arm:.3f} '
                f'H {centre_x + radius:.3f} V {centre_y + arm:.3f} '
                f'H {centre_x + arm:.3f} V {centre_y + radius:.3f} '
                f'H {centre_x - arm:.3f} V {centre_y + arm:.3f} '
                f'H {centre_x - radius:.3f} Z" {attributes} />'
            )
            continue

        polygon = _node_polygon(shape, centre_x, centre_y, radius)
        if polygon is not None:
            rendered = " ".join(f"{x:.3f},{y:.3f}" for x, y in polygon)
            lines.append(f'    <polygon points="{rendered}" {attributes} />')
            continue

        # circle, disc, ring and anything unrecognised
        lines.append(
            f'    <circle cx="{centre_x:.3f}" cy="{centre_y:.3f}" '
            f'r="{radius:.3f}" {attributes} />'
        )
    lines.append('  </g>')
    lines.append('</svg>')

    with open(filepath, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return len(edges)


def _write_png(viewer, filepath, points, plane, transparent):
    """Rasterise the same geometry through matplotlib's Agg backend.

    Agg draws into a memory buffer, so this opens no window and needs no
    display - the VR process stays headless. ``logo.py`` already relies on
    matplotlib the same way.
    """
    import matplotlib
    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection

    left, right, bottom, top = _bounds(viewer, points)
    width = max(right - left, 1e-6)
    height = max(top - bottom, 1e-6)

    figure_height = PNG_FIGURE_WIDTH_INCHES * (height / width)
    points_per_unit = (PNG_FIGURE_WIDTH_INCHES * 72.0) / width

    figure = plt.figure(
        figsize=(PNG_FIGURE_WIDTH_INCHES, figure_height), dpi=PNG_DPI
    )
    try:
        axes = figure.add_axes([0.0, 0.0, 1.0, 1.0])
        axes.set_xlim(left, right)
        axes.set_ylim(bottom, top)
        axes.set_aspect("equal")
        axes.axis("off")

        edges = _visible_edges(viewer)
        if len(edges):
            segments = [
                (tuple(points[source]), tuple(points[target]))
                for source, target in edges
            ]
            axes.add_collection(
                LineCollection(
                    segments,
                    colors=[_rgb_unit(getattr(cfg, "EDGE_COLOR", "#000000"))],
                    alpha=float(getattr(cfg, "EDGE_ALPHA", 0.1)),
                    linewidths=float(getattr(cfg, "EDGE_WIDTH", 1.0)),
                    zorder=1,
                )
            )

        boundary = _rgb_unit(getattr(cfg, "NODE_BOUNDARY_COLOR", "#000000"))
        grouped = {}
        for index in np.flatnonzero(viewer.visible_mask):
            shape = viewer.current_shapes[index]
            marker = MATPLOTLIB_MARKERS.get(shape, "o")
            stroke_only = shape in STROKE_ONLY_SHAPES
            grouped.setdefault((marker, stroke_only), []).append(index)

        for (marker, stroke_only), indices in grouped.items():
            indices = np.asarray(indices)
            # Marker area is quoted in points squared, and the figure was laid
            # out so one world unit is `points_per_unit` points.
            areas = (
                np.asarray(viewer.current_sizes, dtype=np.float64)[indices]
                * points_per_unit
            ) ** 2
            colors = np.asarray(viewer.current_colors, dtype=np.float64)[indices]
            if marker in UNFILLED_MARKERS:
                axes.scatter(
                    points[indices, 0], points[indices, 1],
                    s=areas, marker=marker, c=colors,
                    linewidths=0.8, zorder=2,
                )
            elif stroke_only:
                axes.scatter(
                    points[indices, 0], points[indices, 1],
                    s=areas, marker=marker, facecolors="none",
                    edgecolors=colors, linewidths=0.8, zorder=2,
                )
            else:
                axes.scatter(
                    points[indices, 0], points[indices, 1],
                    s=areas, marker=marker, c=colors,
                    edgecolors=[boundary], linewidths=0.5, zorder=2,
                )

        figure.savefig(
            filepath,
            dpi=PNG_DPI,
            transparent=transparent,
            facecolor="none" if transparent else "white",
        )
    finally:
        plt.close(figure)
    return len(_visible_edges(viewer))


def run(viewer, args):
    if args and args[0].lower() in ("help", "-h", "--help"):
        Command_Engine.print_help(viewer, HELP_TEXT)
        return

    plane = "xy"
    fmt = "svg"
    transparent = False
    name_parts = []

    for argument in args:
        lowered = argument.lower()
        if lowered in PLANES:
            plane = lowered
        elif lowered in ("svg", "png"):
            fmt = lowered
        elif lowered == "transparent":
            transparent = True
        elif lowered == "full":
            Command_Engine.print_help(
                viewer,
                "Error: 'full' is not available in the VR viewer.\n"
                "Upstream stitches camera tiles together to work around "
                "OpenGL edge-clipping; the VR viewer has no camera and no "
                "renderer, and its SVG output is resolution independent, so "
                "there is nothing to stitch.\nDrop the keyword: "
                "print <filename>",
            )
            return
        else:
            name_parts.append(argument)

    if not np.any(viewer.visible_mask):
        Command_Engine.print_help(
            viewer,
            "Error: every node is hidden, so there is nothing to print.\n"
            "Run 'reset hide' to bring the network back.",
        )
        return

    points, error = _projected_positions(viewer, plane)
    if points is None:
        Command_Engine.print_help(viewer, error)
        return

    save_dir = _output_directory()
    try:
        os.makedirs(save_dir, exist_ok=True)
    except OSError as problem:
        Command_Engine.print_help(
            viewer, f"Error: could not create {save_dir!r}: {problem}"
        )
        return

    extension = f".{fmt}"
    filename = "_".join(name_parts) if name_parts else _default_basename()
    if not filename.lower().endswith(extension):
        filename += extension
    filepath = os.path.join(save_dir, filename)

    node_count = int(np.count_nonzero(viewer.visible_mask))
    print(
        f"\nRendering {node_count} visible node(s) onto the "
        f"{plane} plane of the 3D layout..."
    )

    try:
        if fmt == "svg":
            edge_count = _write_svg(viewer, filepath, points, plane, transparent)
        else:
            edge_count = _write_png(viewer, filepath, points, plane, transparent)
    except ImportError:
        Command_Engine.print_help(
            viewer,
            "Error: PNG output needs matplotlib. Install it with "
            "'pip install matplotlib', or print an SVG instead:\n"
            "  print <filename> svg",
        )
        return
    except Exception as problem:
        import traceback
        traceback.print_exc()
        Command_Engine.print_help(
            viewer, f"Error: failed to write {filepath}: {problem}"
        )
        return

    Command_Engine.print_help(
        viewer,
        f"Saved {fmt.upper()}: {filepath}\n"
        f"  {node_count} node(s), {edge_count} edge(s), "
        f"{plane} projection"
        + (", transparent background" if transparent else ""),
    )
