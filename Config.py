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

"""Configuration GUI for the EMAP-SSN VR viewer.

This mirrors the main program's Config GUI, but it belongs to ``opt_vr`` and
configures only the VR front end. The main program's GUI is left untouched and
knows nothing about this submodule.

Two things follow from being the VR side rather than the desktop side:

* **Layout dimensionality is not a setting.** The VR viewer is three
  dimensional by definition, so this GUI always requests 3D layouts. There is
  no 2D/3D control, the same way the desktop GUI has no such control.
* **Everything is stored inside the submodule.** Settings are written to
  ``opt_vr/vr_settings.json`` and every directory is resolved relative to
  ``opt_vr``, so a VR configuration never disturbs the desktop program's
  ``viewer_settings.json`` and the two can be configured independently.

What is *not* duplicated is anything scientific. Cache identity, manifest
matching and canonical folder naming come from ``Cache_Manifest``; layout
generation is handed to ``Layout_Cache_Generator``; fonts, palette and the
responsive field layout come from ``desktop.Desktop_App``. Only the window
itself is local, because that was the part the main GUI could not share.

Run it with ``opt_vr/Viewer.bat``, or directly::

    .venv/Scripts/python.exe opt_vr/Config.py
"""

from __future__ import annotations

import json
import os
import sys
import tempfile

import _bootstrap  # noqa: F401  - puts the parent src tree on sys.path

import Cache_Manifest as cache_manifest
import Settings as vr_settings
from Layout_Cache_Generator import LayoutGenerationSettings
from desktop.Desktop_App import (
    UI_QSS_FONT_STACK,
    ResponsiveFieldLayout,
    configure_qt_application_fonts,
    force_light_palette,
    show_window_in_front,
)
from desktop.Viewer_State import ALIASES, DEFAULTS, encode_document
from utilities.Terminal_Launcher import HoldMode, launch_in_terminal

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

OPT_VR_DIR = _bootstrap.OPT_VR_DIR
PROJECT_ROOT = _bootstrap.PROJECT_ROOT
SRC_DIR = _bootstrap.SRC_DIR

#: Written and read only by the VR side. The desktop program's
#: viewer_settings.json is never touched.
SETTINGS_FILE = os.path.join(OPT_VR_DIR, "vr_settings.json")

VIEWER_SCRIPT = os.path.join(OPT_VR_DIR, "Viewer.py")
GENERATOR_SCRIPT = os.path.join(SRC_DIR, "Layout_Cache_Generator.py")

WINDOW_TITLE = "EMAP-SSN VR Configuration"
VIEWER_TITLE = "EMAP-SSN VR Viewer"
GENERATOR_TITLE = "EMAP-SSN Layout Generator"

#: The VR viewer is three dimensional. Not a user choice - a property of which
#: viewer this GUI launches.
LAYOUT_DIMENSIONS = 3

NEW_CACHE_ENTRY = "(New Layout Cache)"

TAB_CONTENT_MARGIN = 18
TAB_ROW_SPACING = 12

#: Same field metrics as the main GUI, so the two windows read alike.
FIELD_LABEL_WIDTH = 180
FIELD_HORIZONTAL_SPACING = 12


def make_field_group(pairs, *, name="", **options):
    """One row of label/control pairs, laid out as the main GUI lays them out."""
    group = QWidget()
    group.setObjectName(name)
    first_label = pairs[0][0]
    first_label.setFixedWidth(max(FIELD_LABEL_WIDTH, first_label.minimumWidth()))
    ResponsiveFieldLayout(
        group,
        pairs,
        tuple(1 for _ in pairs),
        spacing=FIELD_HORIZONTAL_SPACING,
        wrap_labels=False,
        **options,
    )
    return group


# ---------------------------------------------------------------------------
# Widgets
#
# The main GUI defines equivalents inside its `if __name__ == "__main__"`
# block, which makes them unimportable. They are small, so they are restated
# here rather than refactored out of a file this submodule does not own.
# ---------------------------------------------------------------------------

class NoScrollComboBox(QComboBox):
    """A combo box that ignores the wheel unless it has focus."""

    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class NoScrollSpinBox(QSpinBox):
    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class NoScrollDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()


class OptionalDoubleSpinBox(NoScrollDoubleSpinBox):
    """A spin box whose empty state means ``None``.

    Similarity threshold and top-edge percent are mutually exclusive, and the
    unused one must round-trip as null rather than as zero.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setSpecialValueText(" ")
        self.setMinimum(-1.0)
        self.setValue(self.minimum())

    def optionalValue(self):
        if self.value() <= self.minimum():
            return None
        return float(self.value())

    def setOptionalValue(self, value):
        if value is None or str(value).strip().lower() in ("", "none", "null"):
            self.setValue(self.minimum())
        else:
            try:
                self.setValue(float(value))
            except (TypeError, ValueError):
                self.setValue(self.minimum())


class CacheHashWorker(QThread):
    """Hash the inputs off the UI thread.

    The network HDF5 runs to gigabytes, so hashing it inline would freeze the
    window for as long as the read takes.
    """

    finished_ok = Signal(dict)
    failed = Signal(str)

    def __init__(self, sequence_path, network_path, parent=None):
        super().__init__(parent)
        self._sequence_path = sequence_path
        self._network_path = network_path

    def run(self):
        try:
            metadata = cache_manifest.validate_network_schema(self._network_path)
            self.finished_ok.emit(
                {
                    "sequence": cache_manifest.fingerprint_file(self._sequence_path),
                    "network": cache_manifest.fingerprint_file(self._network_path),
                    "network_type": metadata.network_type,
                }
            )
        except Exception as error:  # surfaced in the cache tracker label
            self.failed.emit(str(error))


# ---------------------------------------------------------------------------
# Field specification
#
# Declarative so the tabs stay readable and every setting is visibly accounted
# for. Keys match the main program's settings schema exactly, which is what
# lets the generated layout cache be interchangeable.
# ---------------------------------------------------------------------------

VISUAL_FIELDS = (
    ("NODE_SIZE", "Node Size:", "int", {"min": 1, "max": 200}),
    ("EDGE_WIDTH", "Edge Width:", "float", {"min": 0.0, "max": 20.0, "step": 0.1}),
    ("NODE_BOUNDARY_WIDTH", "Node Boundary Width:", "float",
     {"min": 0.0, "max": 20.0, "step": 0.1}),
    ("EDGE_ALPHA", "Edge Alpha:", "float", {"min": 0.0, "max": 1.0, "step": 0.05}),
    ("TEXT_SIZE", "Text Size:", "int", {"min": 1, "max": 100}),
    ("TEXT_COLOR", "Text Colour:", "text", {}),
    ("INITIAL_NODE_COLOR", "Node Colour:", "text", {}),
    ("HOVER_COLOR", "Hover Colour:", "text", {}),
    ("CONNECTED_NODE_COLOR", "Connected Node Colour:", "text", {}),
    ("EDGE_COLOR", "Edge Colour:", "text", {}),
    ("NODE_BOUNDARY_COLOR", "Node Boundary Colour:", "text", {}),
    ("LOW_RESOURCE_MODE", "Low Resource Mode:", "bool", {}),
)

PHYSICS_FIELDS = (
    ("LAYOUT_DEVICE_SELECTION", "Compute Device:", "choice",
     {"choices": ("auto", "cpu", "cuda")}),
    ("SPRING_K", "Spring Constant:", "float", {"min": 0.0, "max": 1000.0, "step": 0.5}),
    ("COULOMB_K", "Coulomb Constant:", "float",
     {"min": 0.0, "max": 1000.0, "step": 0.5}),
    ("COULOMB_CUTOFF", "Coulomb Cutoff:", "float",
     {"min": 0.0, "max": 10000.0, "step": 1.0}),
    ("DAMPING", "Damping:", "float", {"min": 0.0, "max": 1.0, "step": 0.01}),
    ("DT", "Time Step:", "float", {"min": 0.0, "max": 1.0, "step": 0.001, "decimals": 4}),
    ("MAX_STEPS", "Max Steps:", "int", {"min": 1, "max": 10_000_000}),
    ("RMSD_THRESHOLD", "RMSD Threshold:", "float",
     {"min": 0.0, "max": 100.0, "step": 0.001, "decimals": 4}),
    ("PERCENTAGE_DROP_THRESHOLD", "Plateau Threshold %:", "float",
     {"min": 0.0, "max": 100.0, "step": 0.05}),
    ("RMSD_WINDOW", "RMSD Window:", "int", {"min": 1, "max": 100_000}),
    ("ENABLE_PROGRESSIVE_SIMULATION", "Progressive Simulation:", "bool", {}),
    ("PACKING_GEOMETRY", "Packing Geometry:", "choice",
     {"choices": ("Square", "Circle")}),
    ("PACKING_GRID_SIZE", "Packing Grid Size:", "float",
     {"min": 0.0, "max": 10000.0, "step": 1.0}),
    ("LAYOUT_SEED", "Layout Seed:", "int", {"min": 0, "max": 2_147_483_647}),
)

VR_FIELDS = (
    ("VR_HOST", "Unity Host:", "text", {}),
    ("VR_PORT", "Unity Port:", "int", {"min": 1, "max": 65535}),
    ("DISTANCE_SCALE", "Distance Scale:", "float",
     {"min": 0.001, "max": 1000.0, "step": 0.1, "decimals": 3}),
    ("NEIGHBOR_COLOR", "Neighbour Colour:", "text", {}),
    ("ENABLE_EDGE_FILTERING", "Limit Rendered Edges:", "bool", {}),
    ("MAX_RENDER_EDGES", "Max Rendered Edges:", "int", {"min": 0, "max": 100_000_000}),
)

DIRECTORY_FIELDS = (
    ("INPUT_FILE_DIR", "Input Files:"),
    ("CACHE_FILE_DIR", "Cache Files:"),
    ("ANALYSIS_RESULT_DIR", "Analysis Results:"),
    ("FASTA_DIR", "Sequence Sets:"),
    ("MSA_DIR", "Multiple Alignments:"),
    ("HDF5_DIR", "Networks:"),
    ("METADATA_DIR", "Metadata:"),
    ("HEADER_LIST_DIR", "Header Lists:"),
    ("SAVED_LAYOUT_DIR", "Layout Caches:"),
    ("SETTING_EXPORT_DIR", "Exported Settings:"),
    ("VR_APP_DIR", "Unity Build:"),
)

TOOLTIPS = {
    "ALIGNMENT_SCORE": "Alignment scoring mode used to build the similarity network.",
    "NORM_MODE": "How raw alignment scores are normalised before thresholding.",
    "ALIGNMENT_REFERENCE": "Sequence ID whose numbering anchors alignment positions.",
    "ALIGNMENT_OFFSET": "Residue offset applied to the reference numbering.",
    "FILTER_MIN_OCCUPANCY": "Minimum column occupancy retained from the alignment.",
    "SIMILARITY_THRESHOLD": "Keep edges scoring above this value. Mutually exclusive "
                            "with Top Edge %.",
    "TOP_EDGE_PERCENT": "Keep the strongest N% of possible edges. Mutually exclusive "
                        "with Similarity Threshold.",
    "UMAP_MODE": "Use UMAP to place nodes instead of the physics simulation.",
    "VR_HOST": "Address the Unity client connects to. The shipped build has "
               "127.0.0.1 baked into its scene.",
    "VR_PORT": "TCP port of the Python/Unity bridge.",
    "DISTANCE_SCALE": "Multiplier applied to layout coordinates before they reach "
                      "the headset.",
    "MAX_RENDER_EDGES": "Upper bound on edges sent to Unity, to keep the frame rate "
                        "usable on large networks.",
    "LAYOUT_SEED": "Seed for reproducible layouts. Blank or 0 means unseeded.",
}


class VRConfigGUI(QMainWindow):
    """The VR configuration window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(1100, 820)
        self.setStyleSheet(f"* {{ {UI_QSS_FONT_STACK} }}")

        self.inputs = {}
        self.labels = {}
        self.current_cache_folder = None
        self._hash_worker = None

        self.values = self._load_settings()

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(10)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs)

        self.tip_panel = QLabel("Configure the VR viewer, then press Save && Run.")
        self.tip_panel.setWordWrap(True)
        self.tip_panel.setStyleSheet("color: #555;")
        outer.addWidget(self.tip_panel)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.btn_save = QPushButton("Save")
        self.btn_save.clicked.connect(self.save_settings)
        self.btn_run = QPushButton("Save && Run")
        self.btn_run.setStyleSheet("font-weight: bold;")
        self.btn_run.clicked.connect(self.save_and_run)
        buttons.addWidget(self.btn_save)
        buttons.addWidget(self.btn_run)
        outer.addLayout(buttons)

        self.setCentralWidget(central)

        self._build_inputs_tab()
        self._build_visual_tab()
        self._build_physics_tab()
        self._build_vr_tab()
        self._build_directories_tab()

        self._apply_tooltips()
        self.refresh_file_dropdowns()
        self.refresh_cache_discovery()

    # -- settings -------------------------------------------------------

    def _load_settings(self):
        """Defaults from the shared schema, overlaid with the VR settings file."""
        values = dict(DEFAULTS)
        values.update(vr_settings.VR_DEFAULTS)
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, encoding="utf-8") as handle:
                    stored = json.load(handle)
                if isinstance(stored, dict):
                    values.update(stored)
            except (OSError, ValueError) as error:
                print(f"[VR Config] Ignoring unreadable {SETTINGS_FILE}: {error}")
        values["LAYOUT_DIMENSIONS"] = LAYOUT_DIMENSIONS
        return values

    def _resolve_directory(self, key):
        """Absolute path for a directory setting, rooted inside opt_vr."""
        raw = self.inputs[key].text().strip() if key in self.inputs else ""
        if not raw:
            raw = str(self.values.get(key, ""))
        return vr_settings.resolve_directory_path(raw) if raw else ""

    # -- widget construction --------------------------------------------

    def _register(self, key, label_text, widget):
        label = QLabel(label_text)
        self.inputs[key] = widget
        self.labels[key] = label
        return label

    def _make_field(self, key, label_text, kind, options):
        if kind == "int":
            widget = NoScrollSpinBox()
            widget.setRange(options.get("min", 0), options.get("max", 1_000_000))
            try:
                widget.setValue(int(self.values.get(key, 0) or 0))
            except (TypeError, ValueError):
                widget.setValue(options.get("min", 0))
        elif kind == "float":
            widget = NoScrollDoubleSpinBox()
            widget.setDecimals(options.get("decimals", 3))
            widget.setRange(options.get("min", 0.0), options.get("max", 1_000_000.0))
            widget.setSingleStep(options.get("step", 0.1))
            try:
                widget.setValue(float(self.values.get(key, 0.0) or 0.0))
            except (TypeError, ValueError):
                widget.setValue(options.get("min", 0.0))
        elif kind == "bool":
            widget = QCheckBox()
            widget.setChecked(bool(self.values.get(key, False)))
        elif kind == "choice":
            widget = NoScrollComboBox()
            widget.addItems(list(options.get("choices", ())))
            current = str(self.values.get(key, ""))
            if current and widget.findText(current) >= 0:
                widget.setCurrentText(current)
        else:
            widget = QLineEdit(str(self.values.get(key, "") or ""))
        widget.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        return self._register(key, label_text, widget)

    def _rows(self, specs, per_row=2):
        """Lay fields out two per row, as the main GUI does."""
        container = QWidget()
        column = QVBoxLayout(container)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(TAB_ROW_SPACING)
        pairs = []
        for key, label_text, kind, options in specs:
            label = self._make_field(key, label_text, kind, options)
            pairs.append((label, self.inputs[key]))
        for index in range(0, len(pairs), per_row):
            column.addWidget(make_field_group(
                pairs[index:index + per_row],
                name=f"row{index}", equal_fields=True, column_spacing=24,
            ))
        return container

    def _add_tab(self, content, title):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setMinimumWidth(600)
        scroll.setWidget(content)
        self.tabs.addTab(scroll, title)

    def _browse_row(self, key, label_text):
        line = QLineEdit(str(self.values.get(key, "") or ""))
        label = self._register(key, label_text, line)
        button = QPushButton("...")
        button.setFixedWidth(36)

        def choose():
            start = vr_settings.resolve_directory_path(line.text().strip()) or OPT_VR_DIR
            chosen = QFileDialog.getExistingDirectory(self, label_text, start)
            if chosen:
                line.setText(self._relative_to_opt_vr(chosen))
                self.refresh_file_dropdowns()
                self.refresh_cache_discovery()

        button.clicked.connect(choose)
        line.editingFinished.connect(self.refresh_file_dropdowns)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(label)
        layout.addWidget(line, 1)
        layout.addWidget(button)
        return row

    @staticmethod
    def _relative_to_opt_vr(path):
        """Store paths inside the submodule as relative, so it stays portable."""
        try:
            relative = os.path.relpath(path, OPT_VR_DIR)
        except ValueError:
            return path
        return path if relative.startswith("..") else relative

    # -- tabs -----------------------------------------------------------

    def _build_inputs_tab(self):
        tab = QWidget()
        form = QFormLayout(tab)
        form.setContentsMargins(
            TAB_CONTENT_MARGIN, TAB_CONTENT_MARGIN,
            TAB_CONTENT_MARGIN, TAB_CONTENT_MARGIN,
        )
        form.setSpacing(TAB_ROW_SPACING)

        self.cb_fasta = NoScrollComboBox()
        self.cb_fasta.setEditable(False)
        self.cb_hdf5 = NoScrollComboBox()
        self.cb_msa = NoScrollComboBox()
        for widget in (self.cb_fasta, self.cb_hdf5, self.cb_msa):
            widget.currentTextChanged.connect(self.refresh_cache_discovery)

        form.addRow(QLabel("Sequence Set / Subset (.fasta):"), self.cb_fasta)
        form.addRow(QLabel("Network Edges Input (.h5):"), self.cb_hdf5)
        form.addRow(QLabel("MSA Input (.fasta / _sparse.h5):"), self.cb_msa)

        self.inputs["NODE_FASTA_FILE"] = self.cb_fasta
        self.inputs["INPUT_HDF5"] = self.cb_hdf5
        self.inputs["MSA_FILE"] = self.cb_msa

        form.addRow(self._rows((
            ("ALIGNMENT_SCORE", "Alignment Score Mode:", "choice",
             {"choices": ("global", "local")}),
            ("NORM_MODE", "Normalization Mode:", "choice",
             {"choices": ("alignment_length", "shorter_sequence",
                          "longer_sequence", "average_sequence")}),
        )))
        form.addRow(self._rows((
            ("ALIGNMENT_REFERENCE", "Alignment Reference ID:", "text", {}),
            ("FILTER_MIN_OCCUPANCY", "Min Occupancy %:", "float",
             {"min": 0.0, "max": 100.0, "step": 1.0, "decimals": 2}),
        )))
        form.addRow(self._rows((
            ("ALIGNMENT_OFFSET", "Alignment Offset:", "int",
             {"min": -1_000_000, "max": 1_000_000}),
            ("UMAP_MODE", "Plot UMAP Instead:", "bool", {}),
        )))

        self.spin_thresh = OptionalDoubleSpinBox()
        self.spin_thresh.setDecimals(4)
        self.spin_thresh.setMaximum(1e9)
        self.spin_thresh.setOptionalValue(self.values.get("SIMILARITY_THRESHOLD"))
        self.spin_top = OptionalDoubleSpinBox()
        self.spin_top.setDecimals(2)
        self.spin_top.setMaximum(100.0)
        self.spin_top.setOptionalValue(self.values.get("TOP_EDGE_PERCENT"))
        self.inputs["SIMILARITY_THRESHOLD"] = self.spin_thresh
        self.inputs["TOP_EDGE_PERCENT"] = self.spin_top
        self.labels["SIMILARITY_THRESHOLD"] = QLabel("Similarity Threshold:")
        self.labels["TOP_EDGE_PERCENT"] = QLabel("Top Edge %:")
        for widget in (self.spin_thresh, self.spin_top):
            widget.valueChanged.connect(self.refresh_cache_discovery)

        form.addRow(make_field_group(
            [
                (self.labels["SIMILARITY_THRESHOLD"], self.spin_thresh),
                (self.labels["TOP_EDGE_PERCENT"], self.spin_top),
            ],
            name="edgeFilterRow", equal_fields=True, column_spacing=24,
        ))

        form.addRow(self._rows((
            ("UMAP_NEIGHBORS", "UMAP Neighbours:", "int", {"min": 2, "max": 10_000}),
            ("UMAP_MIN_DIST", "UMAP Min Distance:", "float",
             {"min": 0.0, "max": 1.0, "step": 0.01}),
        )))

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setStyleSheet("color: #ccc;")
        form.addRow(separator)

        self.lbl_cache_tracker = QLabel("Target Cache: resolving...")
        self.lbl_cache_tracker.setWordWrap(True)
        form.addRow(QLabel("Target Cache:"), self.lbl_cache_tracker)

        self.cb_cache_file = NoScrollComboBox()
        form.addRow(QLabel("Selected Cache File:"), self.cb_cache_file)

        self._add_tab(tab, "Inputs && Outputs")

    def _build_visual_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(
            TAB_CONTENT_MARGIN, TAB_CONTENT_MARGIN,
            TAB_CONTENT_MARGIN, TAB_CONTENT_MARGIN,
        )
        layout.addWidget(self._rows(VISUAL_FIELDS))
        layout.addStretch(1)
        self._add_tab(tab, "Visual Effects")

    def _build_physics_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(
            TAB_CONTENT_MARGIN, TAB_CONTENT_MARGIN,
            TAB_CONTENT_MARGIN, TAB_CONTENT_MARGIN,
        )
        note = QLabel(
            "The VR viewer always solves three dimensional layouts; there is no "
            "2D option here by design."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #555; font-style: italic;")
        layout.addWidget(note)
        layout.addWidget(self._rows(PHYSICS_FIELDS))
        layout.addStretch(1)
        self._add_tab(tab, "Simulation && Physics")

    def _build_vr_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(
            TAB_CONTENT_MARGIN, TAB_CONTENT_MARGIN,
            TAB_CONTENT_MARGIN, TAB_CONTENT_MARGIN,
        )
        note = QLabel(
            "Settings for the Python/Unity bridge. The shipped Unity build has "
            "127.0.0.1:5005 baked into its scene, so changing the endpoint also "
            "means rebuilding the client."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #555; font-style: italic;")
        layout.addWidget(note)
        layout.addWidget(self._rows(VR_FIELDS))
        layout.addStretch(1)
        self._add_tab(tab, "VR && Unity")

    def _build_directories_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(
            TAB_CONTENT_MARGIN, TAB_CONTENT_MARGIN,
            TAB_CONTENT_MARGIN, TAB_CONTENT_MARGIN,
        )
        note = QLabel(
            f"Relative paths resolve inside the submodule ({OPT_VR_DIR}). "
            f"Aliases {', '.join(sorted(ALIASES))} expand to the directories above them."
        )
        note.setWordWrap(True)
        note.setStyleSheet("color: #555; font-style: italic;")
        layout.addWidget(note)
        for key, label_text in DIRECTORY_FIELDS:
            layout.addWidget(self._browse_row(key, label_text))
        layout.addStretch(1)
        self._add_tab(tab, "Directories")

    def _apply_tooltips(self):
        for key, text in TOOLTIPS.items():
            for holder in (self.inputs, self.labels):
                widget = holder.get(key)
                if widget is not None:
                    widget.setToolTip(text)

    # -- file dropdowns --------------------------------------------------

    def refresh_file_dropdowns(self):
        for key, directory_key, suffixes in (
            ("NODE_FASTA_FILE", "FASTA_DIR", (".fasta", ".fa", ".faa")),
            ("INPUT_HDF5", "HDF5_DIR", (".h5",)),
            ("MSA_FILE", "MSA_DIR", (".fasta", ".fa", ".h5")),
        ):
            combo = self.inputs[key]
            previous = combo.currentText() or str(self.values.get(key, "") or "")
            previous = os.path.basename(previous)
            directory = self._resolve_directory(directory_key)
            names = []
            if directory and os.path.isdir(directory):
                names = sorted(
                    entry.name
                    for entry in os.scandir(directory)
                    if entry.is_file() and entry.name.lower().endswith(suffixes)
                )
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(names)
            if previous and previous in names:
                combo.setCurrentText(previous)
            combo.blockSignals(False)

    # -- cache discovery -------------------------------------------------

    def _cache_paths_from_inputs(self):
        fasta = self.inputs["NODE_FASTA_FILE"].currentText().strip()
        network = self.inputs["INPUT_HDF5"].currentText().strip()
        if not fasta or not network:
            return None, None
        return (
            os.path.join(self._resolve_directory("FASTA_DIR"), fasta),
            os.path.join(self._resolve_directory("HDF5_DIR"), network),
        )

    def _cache_setting_values(self):
        """Mirrors the generator's _manifest_settings, including dimensionality."""
        return {
            "alignment_score": self.inputs["ALIGNMENT_SCORE"].currentText() or None,
            "normalization": self.inputs["NORM_MODE"].currentText() or None,
            "umap_mode": self.inputs["UMAP_MODE"].isChecked(),
            "umap_neighbors": self.inputs["UMAP_NEIGHBORS"].value(),
            "top_edge_percent": self.spin_top.optionalValue(),
            "similarity_threshold": self.spin_thresh.optionalValue(),
            "layout_dimensions": LAYOUT_DIMENSIONS,
        }

    def _set_cache_unavailable(self, message, colour="#d32f2f"):
        self.current_cache_folder = None
        self.lbl_cache_tracker.setText(message)
        self.lbl_cache_tracker.setStyleSheet(f"color: {colour};")
        self.cb_cache_file.clear()
        self.cb_cache_file.setEnabled(False)

    def refresh_cache_discovery(self):
        sequence_path, network_path = self._cache_paths_from_inputs()
        if not sequence_path or not network_path:
            self._set_cache_unavailable("Target Cache: select a sequence set and network")
            return
        if not (os.path.isfile(sequence_path) and os.path.isfile(network_path)):
            self._set_cache_unavailable("Target Cache: input files not found")
            return
        if self._hash_worker is not None and self._hash_worker.isRunning():
            return
        self.lbl_cache_tracker.setText("Target Cache: hashing inputs...")
        self.lbl_cache_tracker.setStyleSheet("color: #555;")
        self._hash_worker = CacheHashWorker(sequence_path, network_path, self)
        self._hash_worker.finished_ok.connect(self._apply_cache_discovery)
        self._hash_worker.failed.connect(
            lambda message: self._set_cache_unavailable(f"Cache error: {message}")
        )
        self._hash_worker.start()

    def _apply_cache_discovery(self, records):
        sequence_path, network_path = self._cache_paths_from_inputs()
        if not sequence_path:
            return
        settings = self._cache_setting_values()
        try:
            compatibility = cache_manifest.build_compatibility(
                records["sequence"]["sha256"],
                records["network"]["sha256"],
                records["network_type"],
                **settings,
            )
            saved_layout_dir = self._resolve_directory("SAVED_LAYOUT_DIR")
            canonical_name = cache_manifest.build_canonical_cache_name(
                sequence_path, network_path, records["network_type"], **settings,
            )
            default_folder = cache_manifest.resolve_default_cache_folder(
                saved_layout_dir, canonical_name, compatibility
            )
            matches = cache_manifest.find_matching_manifest_folders(
                saved_layout_dir, compatibility
            )
        except Exception as error:
            self._set_cache_unavailable(f"Cache compatibility error: {error}")
            return

        self.cb_cache_file.blockSignals(True)
        self.cb_cache_file.clear()
        self.cb_cache_file.setEnabled(True)

        if len(matches) > 1:
            self.cb_cache_file.blockSignals(False)
            self._set_cache_unavailable(
                f"Error: {len(matches)} compatible cache folders found"
            )
            return

        if matches:
            folder = matches[0]["folder"]
            self.current_cache_folder = folder
            names = sorted(
                entry.name
                for entry in os.scandir(folder)
                if entry.is_file() and entry.name.lower().endswith(".h5")
            )
            self.cb_cache_file.addItems(names)
            self.cb_cache_file.addItem(NEW_CACHE_ENTRY)
            self.lbl_cache_tracker.setText(
                f"Compatible Folder: {os.path.basename(folder)}"
            )
            self.lbl_cache_tracker.setStyleSheet("color: green; font-weight: bold;")
        else:
            self.current_cache_folder = default_folder
            self.cb_cache_file.addItem(NEW_CACHE_ENTRY)
            self.lbl_cache_tracker.setText(
                f"Target Folder: {os.path.basename(default_folder)} [Needs Computing]"
            )
            self.lbl_cache_tracker.setStyleSheet("color: #d32f2f;")
        self.cb_cache_file.blockSignals(False)

    # -- collect / save ---------------------------------------------------

    def collect_data(self):
        data = dict(self.values)
        for key, widget in self.inputs.items():
            if isinstance(widget, OptionalDoubleSpinBox):
                data[key] = widget.optionalValue()
            elif isinstance(widget, QComboBox):
                data[key] = widget.currentText()
            elif isinstance(widget, QCheckBox):
                data[key] = widget.isChecked()
            elif isinstance(widget, (QSpinBox, QDoubleSpinBox)):
                data[key] = widget.value()
            elif isinstance(widget, QLineEdit):
                data[key] = widget.text().strip()
        if data.get("UMAP_MODE"):
            data["SIMILARITY_THRESHOLD"] = None
            data["TOP_EDGE_PERCENT"] = None
        elif data.get("TOP_EDGE_PERCENT") is not None:
            data["SIMILARITY_THRESHOLD"] = None
        data["LAYOUT_DIMENSIONS"] = LAYOUT_DIMENSIONS
        return data

    def save_settings(self):
        data = self.collect_data()
        try:
            handle, temporary = tempfile.mkstemp(
                dir=OPT_VR_DIR, prefix=".vr_settings_", suffix=".json"
            )
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                json.dump(data, stream, indent=4, sort_keys=True)
                stream.write("\n")
            os.replace(temporary, SETTINGS_FILE)
        except OSError as error:
            QMessageBox.critical(self, "Save Error", f"Could not write settings:\n{error}")
            return False
        self.values = data
        self.tip_panel.setText(f"Saved to {SETTINGS_FILE}")
        return True

    # -- launch -----------------------------------------------------------

    def _layout_settings_document(self, target_cache_path):
        values = dict(self.values)
        values["LAYOUT_DIMENSIONS"] = LAYOUT_DIMENSIONS
        values["TARGET_CACHE_PATH"] = target_cache_path
        for key in ("NODE_FASTA_FILE", "INPUT_HDF5", "MSA_FILE"):
            name = values.get(key) or ""
            directory = {
                "NODE_FASTA_FILE": "FASTA_DIR",
                "INPUT_HDF5": "HDF5_DIR",
                "MSA_FILE": "MSA_DIR",
            }[key]
            if name and not os.path.isabs(name):
                values[key] = os.path.join(self._resolve_directory(directory), name)
        for key, _ in DIRECTORY_FIELDS:
            values[key] = self._resolve_directory(key)
        settings = LayoutGenerationSettings.from_document(
            encode_document("layout", values), project_root=OPT_VR_DIR
        )
        return settings.to_document(project_root=OPT_VR_DIR)

    def _viewer_settings_snapshot(self, data):
        handle, path = tempfile.mkstemp(prefix="vr_viewer_", suffix=".json")
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, indent=4)
            stream.write("\n")
        return path

    def save_and_run(self):
        if self.current_cache_folder is None:
            QMessageBox.warning(
                self, "No Cache Selected",
                "Choose a sequence set and network whose layout cache can be "
                "resolved before launching.",
            )
            return
        if not self.save_settings():
            return

        selected = self.cb_cache_file.currentText()
        needs_generation = selected == NEW_CACHE_ENTRY or not selected
        if needs_generation:
            filename = cache_manifest.next_cache_version_filename(
                self.current_cache_folder
            )
        else:
            filename = selected
        target_cache_path = os.path.join(self.current_cache_folder, filename)

        data = self.collect_data()
        data["TARGET_CACHE_PATH"] = target_cache_path
        for key, _ in DIRECTORY_FIELDS:
            data[key] = self._resolve_directory(key)
        snapshot = self._viewer_settings_snapshot(data)

        environment = os.environ.copy()
        environment.pop("SSN_TARGET_CACHE", None)
        environment["SSN_VIEWER_SETTINGS_PATH"] = snapshot

        executable = sys.executable
        try:
            if needs_generation:
                document = self._layout_settings_document(target_cache_path)
                handle, layout_path = tempfile.mkstemp(
                    prefix="vr_layout_", suffix=".json"
                )
                with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
                    json.dump(document, stream, indent=4)
                    stream.write("\n")
                self.tip_panel.setText("Launching Layout_Cache_Generator.py...")
                launch_in_terminal(
                    [executable, "-u", GENERATOR_SCRIPT, layout_path,
                     "--delete-settings"],
                    cwd=PROJECT_ROOT,
                    env=environment,
                    hold=HoldMode.ON_ERROR,
                    title=GENERATOR_TITLE,
                )
            else:
                self.tip_panel.setText("Launching the VR viewer...")
                launch_in_terminal(
                    [executable, "-u", VIEWER_SCRIPT,
                     "--settings", snapshot, "--delete-settings"],
                    cwd=OPT_VR_DIR,
                    env=environment,
                    hold=HoldMode.ON_ERROR,
                    title=VIEWER_TITLE,
                )
        except (OSError, RuntimeError) as error:
            try:
                os.unlink(snapshot)
            except OSError:
                pass
            QMessageBox.critical(self, "Launch Error", str(error))


def main():
    application = QApplication.instance() or QApplication(sys.argv)
    try:
        configure_qt_application_fonts(application)
    except Exception as error:
        print(f"Warning: could not configure fonts: {error}")
    try:
        force_light_palette(application)
    except Exception as error:
        print(f"Warning: could not force light palette: {error}")
        application.setStyle("Fusion")

    for candidate in ("viewer_logo.ico", "viewer_logo.png"):
        icon_path = os.path.join(SRC_DIR, "bin", "logos", candidate)
        if os.path.exists(icon_path):
            application.setWindowIcon(QIcon(icon_path))
            break

    window = VRConfigGUI()
    show_window_in_front(window)
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
