"""VocalFry main window (PyQt6)."""
from __future__ import annotations

import json
import math
import os
import random
import tempfile
import threading

import numpy as np
from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (QAction, QBrush, QColor, QFont, QIcon, QPainter,
                         QPainterPath, QPen)
from PyQt6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
                             QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                             QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QInputDialog,
                             QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
                             QMainWindow, QMessageBox, QPlainTextEdit,
                             QProgressDialog, QPushButton, QScrollArea,
                             QSlider, QSpinBox, QSplitter, QToolButton,
                             QVBoxLayout, QWidget)

from . import audio, config, dsp, params, presets, video
from .params import BY_KEY, GROUPS, PARAMS

SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
EXAMPLE_SCRIPT = os.path.join(SCRIPT_DIR, "why-a-duck.txt")
SCRIPT_STATE = os.path.join(presets.CONFIG_DIR, "script.json")    # text + font size, kept between runs

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ICON = os.path.join(HERE, "icons", "vocalfry.png")
SLIDER_STEPS = 1000

RED = QColor("#c8352b")
GOLD = QColor("#e8a923")


# ---------------------------------------------------------------- helpers
class Signals(QObject):
    analysed = pyqtSignal(object, str)      # Analysis or None, error text
    rendered = pyqtSignal(object, int)      # Result, job id
    progress = pyqtSignal(str)
    batch_step = pyqtSignal(int)
    batch_done = pyqtSignal(str)


def to_slider(p: params.Param, v: float) -> int:
    if p.log:
        lo, hi = math.log(p.lo), math.log(p.hi)
        f = (math.log(max(p.lo, v)) - lo) / (hi - lo)
    else:
        f = (v - p.lo) / (p.hi - p.lo)
    return int(round(max(0.0, min(1.0, f)) * SLIDER_STEPS))


def from_slider(p: params.Param, i: int) -> float:
    f = i / SLIDER_STEPS
    if p.log:
        v = math.exp(math.log(p.lo) + f * (math.log(p.hi) - math.log(p.lo)))
    else:
        v = p.lo + f * (p.hi - p.lo)
    return round(v, p.decimals)


# ---------------------------------------------------------------- controls
class ParamRow:
    """Label + slider + numeric field + reset button for one Param."""

    def __init__(self, p: params.Param, grid: QGridLayout, row: int, changed):
        self.p, self.changed, self._busy = p, changed, False
        self.neutral = p.default
        lab = QLabel(p.label)
        lab.setToolTip(p.tip)
        lab.setMinimumWidth(170)
        grid.addWidget(lab, row, 0)
        if p.key in params.TOGGLES:
            self.box = QCheckBox()
            self.box.setToolTip(p.tip)
            self.box.toggled.connect(lambda on: self._emit(1.0 if on else 0.0))
            grid.addWidget(self.box, row, 1, 1, 3)
            self.slider = self.spin = None
            return
        self.box = None
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, SLIDER_STEPS)
        self.slider.setToolTip(p.tip)
        self.slider.setMinimumWidth(140)
        self.spin = QDoubleSpinBox()
        self.spin.setRange(p.lo, p.hi)
        self.spin.setDecimals(p.decimals)
        self.spin.setSingleStep(10 ** -p.decimals if p.decimals else 1)
        self.spin.setSuffix(f" {p.unit}" if p.unit else "")
        self.spin.setKeyboardTracking(False)
        self.spin.setMinimumWidth(96)
        reset = QToolButton()
        reset.setText("↺")
        reset.setToolTip("Back to neutral")
        reset.clicked.connect(lambda: self._emit(self.neutral))
        self.slider.valueChanged.connect(lambda i: self._emit(from_slider(p, i)))
        self.spin.valueChanged.connect(lambda v: self._emit(v))
        grid.addWidget(self.slider, row, 1)
        grid.addWidget(self.spin, row, 2)
        grid.addWidget(reset, row, 3)

    def _emit(self, v: float):
        if not self._busy:
            self.changed(self.p.key, v)

    def set(self, v: float):
        self._busy = True
        try:
            if self.box is not None:
                self.box.setChecked(v >= 0.5)
            else:
                self.slider.setValue(to_slider(self.p, v))
                self.spin.setValue(v)
        finally:
            self._busy = False


class VoiceMap(QWidget):
    """Pitch x vocal-tract-length plane with the plausible-human band."""
    moved = pyqtSignal(float, float)          # pitch Hz, tract cm

    F_LO, F_HI, L_LO, L_HI = 50.0, 500.0, 8.0, 21.0
    # where each preset's label sits: (dx, dy, l = right of dot / r = left of it)
    LABELS = {"Adult man": (6, -5, "r"), "Elderly man": (6, 13, "l"),
              "Adult woman": (6, -5, "l"), "Elderly woman": (6, 4, "r"),
              "Teen": (6, 12, "l"), "Bright soprano": (6, -2, "l"),
              "Child": (6, -4, "l"), "Young child": (6, 14, "r"),
              "Deep bass": (6, -4, "l")}

    def __init__(self):
        super().__init__()
        self.setMinimumSize(300, 230)
        self.point = (120.0, 17.5)
        self.source = None
        self.presets: list[presets.Preset] = []     # dots = presets in presets/ with "map" on
        self.setToolTip("Drag to choose pitch and vocal-tract length together.\n"
                        "The shaded band is where real human voices lie.")

    def set_point(self, f0, tract, source=None):
        self.point = (f0, tract)
        if source is not None:
            self.source = source
        self.update()

    def _plot(self) -> QRectF:
        return QRectF(46, 10, self.width() - 58, self.height() - 44)

    def _xy(self, f0, L) -> QPointF:
        r = self._plot()
        fx = (math.log(f0) - math.log(self.F_LO)) / (math.log(self.F_HI) - math.log(self.F_LO))
        fy = (L - self.L_LO) / (self.L_HI - self.L_LO)
        return QPointF(r.left() + fx * r.width(), r.bottom() - fy * r.height())

    def _val(self, pt: QPointF):
        r = self._plot()
        fx = min(1, max(0, (pt.x() - r.left()) / r.width()))
        fy = min(1, max(0, (r.bottom() - pt.y()) / r.height()))
        f0 = math.exp(math.log(self.F_LO) + fx * (math.log(self.F_HI) - math.log(self.F_LO)))
        L = self.L_LO + fy * (self.L_HI - self.L_LO)
        return round(f0, 1), round(L, 1)

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        fg = pal.color(pal.ColorRole.WindowText)
        r = self._plot()
        qp.fillRect(r, pal.color(pal.ColorRole.Base))
        # band
        fs = [math.exp(math.log(70) + i * (math.log(450) - math.log(70)) / 60) for i in range(61)]
        path = QPainterPath(self._xy(fs[0], params.typical_tract(fs[0]) + params.BAND))
        for f in fs[1:]:
            path.lineTo(self._xy(f, params.typical_tract(f) + params.BAND))
        for f in reversed(fs):
            path.lineTo(self._xy(f, params.typical_tract(f) - params.BAND))
        path.closeSubpath()
        band = QColor(GOLD)
        band.setAlpha(70)
        qp.fillPath(path, band)
        qp.setPen(QPen(QColor(GOLD).darker(130), 1, Qt.PenStyle.DashLine))
        line = QPainterPath(self._xy(fs[0], params.typical_tract(fs[0])))
        for f in fs[1:]:
            line.lineTo(self._xy(f, params.typical_tract(f)))
        qp.drawPath(line)
        # grid + axes
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1.5))
        qp.setFont(small)
        grid = QColor(fg)
        grid.setAlpha(40)
        for f in (50, 100, 200, 300, 500):
            p = self._xy(f, self.L_LO)
            qp.setPen(QPen(grid))
            qp.drawLine(QPointF(p.x(), r.top()), QPointF(p.x(), r.bottom()))
            qp.setPen(fg)
            qp.drawText(QRectF(p.x() - 20, r.bottom() + 2, 40, 14),
                        Qt.AlignmentFlag.AlignCenter, str(f))
        for L in (9, 12, 15, 18, 21):
            p = self._xy(self.F_LO, L)
            qp.setPen(QPen(grid))
            qp.drawLine(QPointF(r.left(), p.y()), QPointF(r.right(), p.y()))
            qp.setPen(fg)
            qp.drawText(QRectF(2, p.y() - 7, 40, 14),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, f"{L}")
        qp.drawText(QRectF(r.left(), r.bottom() + 16, r.width(), 14),
                    Qt.AlignmentFlag.AlignCenter, "mean pitch (Hz)   ·   ↕ tract length (cm)")
        # preset dots
        for pre in self.presets:
            name, pr = pre.name, pre.values
            if "pitch_hz" in pr and "tract" in pr:
                p = self._xy(pr["pitch_hz"], pr["tract"])
                qp.setPen(QPen(fg, 1))
                qp.setBrush(Qt.BrushStyle.NoBrush)
                qp.drawEllipse(p, 3, 3)
                dx, dy, align = self.LABELS.get(name, (6, -4, "l"))
                w = qp.fontMetrics().horizontalAdvance(name)
                qp.drawText(QPointF(p.x() + (dx if align == "l" else -dx - w), p.y() + dy), name)
        if self.source:
            p = self._xy(*self.source)
            qp.setPen(QPen(fg, 1.5))
            qp.drawLine(QPointF(p.x() - 5, p.y() - 5), QPointF(p.x() + 5, p.y() + 5))
            qp.drawLine(QPointF(p.x() - 5, p.y() + 5), QPointF(p.x() + 5, p.y() - 5))
            w = qp.fontMetrics().horizontalAdvance("source")
            qp.drawText(QPointF(p.x() - 7 - w, p.y() + 14), "source")
        p = self._xy(*self.point)
        ok = params.plausible(*self.point)
        qp.setPen(QPen(QColor("white"), 2))
        qp.setBrush(QBrush(RED if ok else QColor("#7a2be0")))
        qp.drawEllipse(p, 7, 7)
        if not ok:
            qp.setPen(fg)
            qp.drawText(QRectF(r.left(), r.top() + 2, r.width() - 6, 14),
                        Qt.AlignmentFlag.AlignRight, "outside human range")

    def mousePressEvent(self, e):
        self.moved.emit(*self._val(e.position()))

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            self.moved.emit(*self._val(e.position()))


class Contour(QWidget):
    """Original vs processed pitch track, with start/end trim handles.

    The x axis is the original recording's time; the processed track is drawn
    from the start handle on."""
    trimmed = pyqtSignal(int, int)          # start, end frame (end exclusive)
    MIN_FRAMES = 20                         # 100 ms

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(130)
        self.setMouseTracking(True)
        self.orig = self.out = self.cleaned = None
        self.events = 0
        self.trim = (0, 0)
        self.drag = None                    # 0 = start handle, 1 = end handle
        self.menu_actions = []              # (text, slot) for the right-click menu
        self.setToolTip("Drag the handles at either end to trim the recording.\n"
                        "Right-click to reset the trim or save the trimmed original.")

    def set_tracks(self, orig, out, cleaned=None, events=0):
        new = orig is not None and orig is not self.orig
        self.orig, self.out, self.cleaned, self.events = orig, out, cleaned, events
        if orig is None:
            self.trim = (0, 0)
        elif new:
            self.trim = (0, len(orig))
        self.update()

    def set_trim(self, start, end):
        self.trim = (start, end)
        self.update()

    # ---- geometry
    def _rect(self) -> QRectF:
        return QRectF(46, 6, self.width() - 56, self.height() - 26)

    def _n(self):
        n = len(self.orig) if self.orig is not None else 0
        if self.out is not None:
            n = max(n, self.trim[0] + len(self.out))
        return max(n, 1)

    def _fx(self, frame):
        r = self._rect()
        return r.left() + frame / self._n() * r.width()

    def _frame(self, x):
        r = self._rect()
        return round((x - r.left()) / r.width() * self._n())

    def _handle_at(self, x):
        if self.orig is None:
            return None
        d = [abs(x - self._fx(f)) for f in self.trim]
        i = 0 if d[0] <= d[1] else 1
        return i if d[i] <= 7 else None

    # ---- mouse
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.drag = self._handle_at(e.position().x())

    def mouseMoveEvent(self, e):
        x = e.position().x()
        if self.drag is None:
            self.setCursor(Qt.CursorShape.SizeHorCursor if self._handle_at(x) is not None
                           else Qt.CursorShape.ArrowCursor)
            return
        total = len(self.orig)
        f = min(max(self._frame(x), 0), total)
        s, t = self.trim
        if self.drag == 0:
            s = min(f, t - self.MIN_FRAMES)
        else:
            t = max(f, s + self.MIN_FRAMES)
        self.trim = (max(0, s), min(total, t))
        self.update()

    def mouseReleaseEvent(self, e):
        if self.drag is not None:
            self.drag = None
            self.trimmed.emit(*self.trim)

    def mouseDoubleClickEvent(self, e):
        if self._handle_at(e.position().x()) is not None and self.orig is not None:
            self.trim = (0, len(self.orig))
            self.update()
            self.trimmed.emit(*self.trim)

    def contextMenuEvent(self, e):
        if self.orig is None or not self.menu_actions:
            return
        m = QMenu(self)
        for text, slot in self.menu_actions:
            m.addAction(text).triggered.connect(slot)
        m.exec(e.globalPos())

    def paintEvent(self, _):
        qp = QPainter(self)
        qp.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        fg = pal.color(pal.ColorRole.WindowText)
        r = self._rect()
        qp.fillRect(r, pal.color(pal.ColorRole.Base))
        lo, hi = math.log(25), math.log(1000)

        def y(f):
            return r.bottom() - (math.log(f) - lo) / (hi - lo) * r.height()
        small = QFont(self.font())
        small.setPointSizeF(max(7.0, small.pointSizeF() - 1.5))
        qp.setFont(small)
        grid = QColor(fg)
        grid.setAlpha(40)
        for f in (50, 100, 200, 400, 800):
            qp.setPen(QPen(grid))
            qp.drawLine(QPointF(r.left(), y(f)), QPointF(r.right(), y(f)))
            qp.setPen(fg)
            qp.drawText(QRectF(2, y(f) - 7, 40, 14),
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, str(f))
        tracks = [t for t in (self.orig, self.out) if t is not None]
        if not tracks:
            qp.setPen(fg)
            qp.drawText(r, Qt.AlignmentFlag.AlignCenter, "Open or record a voice to begin")
            return
        n = self._n()
        off = self.trim[0]                  # processed track starts at the start handle
        secs = (len(self.orig) if self.orig is not None else n) * dsp.FRAME_MS / 1000
        if self.cleaned is not None and self.cleaned.any():
            shade = QColor(GOLD)
            shade.setAlpha(60)
            c, m, i = self.cleaned, len(self.cleaned), 0
            while i < m:
                if c[i]:
                    k = i
                    while k < m and c[k]:
                        k += 1
                    qp.fillRect(QRectF(r.left() + (off + i) / n * r.width(), r.top(),
                                       max(1.0, (k - i) / n * r.width()), r.height()), shade)
                    i = k
                else:
                    i += 1
        qp.setPen(fg)
        note = f"{self.events} stray noise{'s' if self.events != 1 else ''} turned down (gold)   " \
            if self.cleaned is not None and self.cleaned.any() else ""
        s0, s1 = self.trim
        cut = ""
        if self.orig is not None and (s0, s1) != (0, len(self.orig)):
            ms = dsp.FRAME_MS / 1000
            cut = f"kept {s0 * ms:.2f}–{s1 * ms:.2f} s of "
        qp.drawText(QRectF(r.left(), r.bottom() + 3, r.width(), 14),
                    Qt.AlignmentFlag.AlignRight,
                    f"{note}{cut}{secs:.1f} s   pitch (Hz): grey = original, red = processed")
        for t, col, w, o in ((self.orig, QColor(128, 128, 128, 170), 1.2, 0), (self.out, RED, 1.8, off)):
            if t is None:
                continue
            qp.setPen(QPen(col, w))
            step = max(1, len(t) // 1500)
            path, pen_down = QPainterPath(), False
            for i in range(0, len(t), step):
                f = t[i]
                if f <= 0:
                    pen_down = False
                    continue
                pt = QPointF(r.left() + (o + i) / n * r.width(), y(min(1000, max(25, f))))
                if pen_down:
                    path.lineTo(pt)
                else:
                    path.moveTo(pt)
                    pen_down = True
            qp.drawPath(path)
        if self.orig is not None:
            dim = QColor(fg)
            dim.setAlpha(55)
            x0, x1 = self._fx(s0), self._fx(s1)
            qp.fillRect(QRectF(r.left(), r.top(), x0 - r.left(), r.height()), dim)
            qp.fillRect(QRectF(x1, r.top(), r.right() - x1, r.height()), dim)
            for x in (x0, x1):
                qp.setPen(QPen(GOLD.darker(130), 2))
                qp.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
                qp.setBrush(GOLD)
                tab = QPainterPath()
                tab.addRoundedRect(QRectF(x - 5, r.top(), 10, 14), 3, 3)
                qp.drawPath(tab)


# ---------------------------------------------------------------- batch dialog
class BatchDialog(QDialog):
    def __init__(self, parent, folder):
        super().__init__(parent)
        self.setWindowTitle("Batch export random speakers")
        form = QFormLayout(self)
        self.count = QSpinBox()
        self.count.setRange(1, 500)
        self.count.setValue(10)
        self.seed = QSpinBox()
        self.seed.setRange(0, 999999)
        self.seed.setValue(random.randint(1, 99999))
        self.folder = QLineEdit(folder)
        browse = QPushButton("…")
        browse.clicked.connect(self._browse)
        row = QHBoxLayout()
        row.addWidget(self.folder)
        row.addWidget(browse)
        form.addRow("Number of speakers", self.count)
        form.addRow("Random seed", self.seed)
        form.addRow("Output folder", row)
        self.groups = {}
        for g, label in GROUPS:
            if g not in params.VOICE_GROUPS:
                continue
            cb = QCheckBox(label)
            cb.setChecked(True)
            self.groups[g] = cb
            form.addRow("Randomise" if g == params.VOICE_GROUPS[0] else "", cb)
        note = QLabel("Every speaker stays inside the plausible human range.\n"
                      "Clean-up settings are applied to every speaker as they are now.\n"
                      "Writes speaker_NNN.wav plus speakers.json with each one's settings.")
        note.setWordWrap(True)
        form.addRow(note)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        form.addRow(bb)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Output folder", self.folder.text())
        if d:
            self.folder.setText(d)


# ---------------------------------------------------------------- preset file
class PresetDialog(QDialog):
    """One preset file: what it sets, apply it, and its show-in-menu flag."""

    def __init__(self, parent: "MainWindow", p: presets.Preset, just_saved=False):
        super().__init__(parent)
        self.main, self.p = parent, p
        self.setWindowTitle(f"Preset — {p.name}")
        v = QVBoxLayout(self)
        head = QLabel(f"<b>{p.name}</b><br><small>{p.path}</small>")
        head.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        v.addWidget(head)
        lines = []
        for k, val in p.values.items():
            if k in BY_KEY:
                q = BY_KEY[k]
                lines.append(f"{q.label}: {val:g} {q.unit}".rstrip())
            elif k.startswith("on_") and not val:
                lines.append(f"{k[3:].capitalize()} group bypassed")
        body = QLabel("\n".join(lines) if lines else "(sets nothing — neutral voice)")
        v.addWidget(body)
        self.menu = QCheckBox("Show in the Preset menu")
        self.menu.setToolTip("Stored in the preset file itself as \"menu\"")
        self.menu.setChecked(p.menu)
        self.menu.toggled.connect(self._menu)
        v.addWidget(self.menu)
        self.on_map = QCheckBox("Show on the voice map")
        self.on_map.setToolTip("Stored in the preset file as \"map\". Only presets saved in the\n"
                               "presets folder that set pitch and tract length can appear.")
        self.on_map.setChecked(p.map)
        self.on_map.toggled.connect(self._map)
        v.addWidget(self.on_map)
        dv = config.default_voice()
        self.default = QCheckBox("Use as my voice for every new recording")
        self.default.setToolTip("Applied whenever you record or open a file (clean-up settings are kept).\n"
                                "Only one preset can be the default voice.")
        self.default.setChecked(dv is not None and dv.path == p.path)
        self.default.toggled.connect(self._default)
        v.addWidget(self.default)
        bb = QDialogButtonBox()
        if not just_saved:
            apply_b = bb.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
            apply_b.clicked.connect(self._apply)
        bb.addButton(QDialogButtonBox.StandardButton.Close).clicked.connect(self.reject)
        v.addWidget(bb)

    def _menu(self, on):
        try:
            presets.set_menu(self.p.path, on)
        except presets.PresetError as e:
            QMessageBox.warning(self, "VocalFry", str(e))
            self.menu.blockSignals(True)
            self.menu.setChecked(not on)
            self.menu.blockSignals(False)
            return
        self.p.menu = on
        presets.remember(self.p.path)
        self.main._refresh_presets()
        self.main.statusBar().showMessage(f"{self.p.name} {'added to' if on else 'removed from'} the Preset menu")

    def _map(self, on):
        try:
            presets.set_flag(self.p.path, "map", on)
        except presets.PresetError as e:
            QMessageBox.warning(self, "VocalFry", str(e))
            self.on_map.blockSignals(True)
            self.on_map.setChecked(not on)
            self.on_map.blockSignals(False)
            return
        self.p.map = on
        self.main._refresh_presets()
        self.main.statusBar().showMessage(f"{self.p.name} {'shown on' if on else 'hidden from'} the voice map")

    def _default(self, on):
        if on:
            config.set_default_voice(self.p.path)
            presets.remember(self.p.path)
        else:
            config.set_default_voice(None)
        self.main._refresh_presets()
        self.main.statusBar().showMessage(f"{self.p.name} is now your voice for new recordings" if on
                                          else "No default voice: new recordings start neutral")

    def _apply(self):
        presets.remember(self.p.path)
        self.main._apply_preset(self.p)
        self.accept()


# ---------------------------------------------------------------- video export
class VideoDialog(QDialog):
    """Turn the joined clips into an .mp4: one still frame with a title and description."""
    done_sig = pyqtSignal(str, str)         # output path, error ("" = fine)

    def __init__(self, parent: "JoinDialog", y, fs, name=""):
        super().__init__(parent)
        self.join, self.y, self.fs = parent, y, fs
        self.setWindowTitle("Export video")
        v = QVBoxLayout(self)
        form = QFormLayout()
        self.title = QLineEdit(config.get("video_title", name))
        self.title.setPlaceholderText("Title")
        self.desc = QPlainTextEdit(config.get("video_desc", ""))
        self.desc.setPlaceholderText("Description (optional; wraps to fit)")
        self.desc.setFixedHeight(90)
        self.style = QComboBox()
        self.style.addItems(list(video.STYLES))
        self.style.setCurrentText(config.get("video_style", "Dark"))
        form.addRow("Title", self.title)
        form.addRow("Description", self.desc)
        form.addRow("Style", self.style)
        v.addLayout(form)
        self.preview = QLabel()
        self.preview.setFixedSize(480, 270)
        self.preview.setFrameShape(QLabel.Shape.Box)
        v.addWidget(self.preview, 0, Qt.AlignmentFlag.AlignHCenter)
        v.addWidget(QLabel(f"{len(y) / fs:.1f} s of audio · 1280 × 720 H.264 + AAC"))
        bb = QDialogButtonBox()
        self.go = bb.addButton("Save video…", QDialogButtonBox.ButtonRole.AcceptRole)
        self.go.clicked.connect(self._export)
        bb.addButton(QDialogButtonBox.StandardButton.Close).clicked.connect(self.reject)
        v.addWidget(bb)
        for sig in (self.title.textChanged, self.desc.textChanged, self.style.currentTextChanged):
            sig.connect(self._preview)
        self.done_sig.connect(self._finished)
        self.name = name
        self._preview()

    def _card(self):
        return video.title_card(self.title.text(), self.desc.toPlainText(), self.style.currentText())

    def _preview(self, *_):
        from PyQt6.QtGui import QPixmap
        self.preview.setPixmap(QPixmap.fromImage(self._card()).scaled(
            self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

    def _export(self):
        stem = config.clean_name(self.title.text().strip() or self.name or "voice")
        start = os.path.join(config.work_dir(), stem + ".mp4")
        out, _ = QFileDialog.getSaveFileName(self, "Save video", start, "MP4 video (*.mp4)")
        if not out:
            return
        if not out.lower().endswith(".mp4"):
            out += ".mp4"
        config.put("video_title", self.title.text())
        config.put("video_desc", self.desc.toPlainText())
        config.put("video_style", self.style.currentText())
        tmp = self.join.main.tmp
        img, wav = os.path.join(tmp, "card.png"), os.path.join(tmp, "video-audio.wav")
        self._card().save(img)
        audio.write_wav(wav, self.y, self.fs)
        self.go.setEnabled(False)
        self.go.setText("Encoding…")

        def work():
            try:
                video.make_mp4(wav, img, out)
                self.done_sig.emit(out, "")
            except (video.VideoError, OSError) as e:
                self.done_sig.emit(out, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _finished(self, out, err):
        self.go.setEnabled(True)
        self.go.setText("Save video…")
        if err:
            QMessageBox.warning(self, "VocalFry", f"Could not make the video:\n{err}")
            return
        self.join.main.statusBar().showMessage(f"Saved video {out} ({os.path.getsize(out) / 1e6:.1f} MB)")
        self.accept()


# ---------------------------------------------------------------- append clips
class JoinDialog(QDialog):
    """Append saved WAV clips (and the current voice) end to end into one file."""
    voiced = pyqtSignal(int, object, str)      # clip index, samples or None, preset name / error

    def __init__(self, parent: "MainWindow"):
        super().__init__(parent)
        self.main = parent
        self.setWindowTitle("Append clips")
        self.resize(780, 480)
        self.clips: list[tuple[str, np.ndarray, int]] = []     # label, samples, rate
        self.paths: list[str] = []                              # file each clip came from, if any
        self.player = audio.Player()
        v = QVBoxLayout(self)
        v.addWidget(QLabel("Clips are joined top to bottom. Drag or use ▲▼ to reorder."))
        mid = QHBoxLayout()
        self.list = QListWidget()
        self.list.setDragDropMode(QListWidget.DragDropMode.InternalMove)
        self.list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self.list.model().rowsMoved.connect(self._reordered)
        self.list.itemSelectionChanged.connect(self._update)
        mid.addWidget(self.list, 1)
        side = QVBoxLayout()

        def btn(text, slot, tip=""):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            side.addWidget(b)
            return b
        btn("Add files…", self._add_files, "Add saved WAV clips")
        self.add_out = btn("Add processed voice", lambda: self._add_current("out"),
                           "Add the voice as currently rendered")
        self.add_src = btn("Add original", lambda: self._add_current("src"),
                           "Add the unprocessed recording")
        btn("Remove", self._remove)
        btn("▲ Up", lambda: self._move(-1))
        btn("▼ Down", lambda: self._move(1))
        side.addStretch(1)
        mid.addLayout(side)
        v.addLayout(mid, 1)

        # put a preset voice on clips that were saved without it
        vrow = QHBoxLayout()
        vrow.addWidget(QLabel("Voice:"))
        self.voice = QComboBox()
        self.voice.setToolTip("Preset to apply to the selected clips (menu presets first)")
        found = presets.discover()
        for p in sorted(found, key=lambda p: not p.menu):
            self.voice.addItem(p.name, p.path)
        vrow.addWidget(self.voice, 1)
        vrow.addWidget(QLabel("your tract"))
        self.src_tract = QDoubleSpinBox()
        lo = BY_KEY["src_tract"]
        self.src_tract.setRange(lo.lo - 0.1, lo.hi)
        self.src_tract.setSingleStep(0.1)
        self.src_tract.setDecimals(1)
        self.src_tract.setSuffix(" cm")
        self.src_tract.setSpecialValueText("guess per clip")
        self.src_tract.setValue(parent.settings["src_tract"] if parent.analysis is not None else lo.lo - 0.1)
        self.src_tract.setToolTip("Your natural vocal-tract length. VocalFry otherwise guesses it from\n"
                                  "each clip's pitch, which goes wrong if you spoke the clip high or low.\n"
                                  "Starts at the editor's Source tract length when a recording is open.")
        vrow.addWidget(self.src_tract)
        self.voice_b = QPushButton("Apply voice to selected")
        self.voice_b.setToolTip("Reshape the selected clips into this voice (clean-up as in the editor).\n"
                                "Each result replaces its clip here and is saved to the voice-work\n"
                                "folder as CLIP-PRESET.wav; the clip's own file is left alone.")
        self.voice_b.clicked.connect(self._apply_voice)
        vrow.addWidget(self.voice_b)
        v.addLayout(vrow)
        self.voiced.connect(self._on_voiced)
        self.busy = 0

        form = QFormLayout()
        self.gap = QDoubleSpinBox()
        self.gap.setRange(0, 10000)
        self.gap.setDecimals(0)
        self.gap.setSuffix(" ms")
        self.gap.setToolTip("Silence inserted between clips")
        self.fade = QDoubleSpinBox()
        self.fade.setRange(0, 2000)
        self.fade.setDecimals(0)
        self.fade.setSuffix(" ms")
        self.fade.setToolTip("Overlap neighbouring clips by this much with a smooth fade\n"
                             "(0 = butt them together, or leave the gap above)")
        self.gap.valueChanged.connect(self._update)
        self.fade.valueChanged.connect(self._update)
        form.addRow("Gap between clips", self.gap)
        form.addRow("Crossfade", self.fade)
        self.name = QLineEdit(config.get("take_name", ""))
        self.name.setPlaceholderText("e.g. Cocoanuts")
        self.name.setToolTip("Takes are saved as NAME-1.wav, NAME-2.wav, … in the voice-work folder")
        self.name.textChanged.connect(self._update)
        form.addRow("Take name", self.name)
        self.next_lab = QLabel()
        self.next_lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        form.addRow("", self.next_lab)
        v.addLayout(form)
        self.total = QLabel()
        v.addWidget(self.total)

        row = QHBoxLayout()
        self.play_b = QPushButton("▶ Play joined")
        self.play_b.clicked.connect(self._play)
        stop = QPushButton("■ Stop")
        stop.clicked.connect(self.player.stop)
        self.take_b = QPushButton("Save take")
        self.take_b.setToolTip("Save as the next numbered take in the voice-work folder")
        self.take_b.setDefault(True)
        self.take_b.clicked.connect(self._save_take)
        self.save_b = QPushButton("Save as…")
        self.save_b.setToolTip("Save the joined clips under any name or folder")
        self.save_b.clicked.connect(self._save)
        self.video_b = QPushButton("Export video…")
        self.video_b.setToolTip("Save the joined clips as an .mp4 with a title and description on screen")
        self.video_b.clicked.connect(self._video)
        self.edit_b = QPushButton("Open in editor")
        self.edit_b.setToolTip("Load the joined clip into VocalFry to reshape it as one recording")
        self.edit_b.clicked.connect(self._open_in_editor)
        close = QPushButton("Close")
        close.clicked.connect(self.reject)
        for b in (self.play_b, stop, self.take_b, self.save_b, self.video_b, self.edit_b):
            row.addWidget(b)
        row.addStretch(1)
        row.addWidget(close)
        v.addLayout(row)
        self._update()

    # ---- list
    def _add(self, label, x, fs, path=""):
        self.clips.append((label, x, fs))
        self.paths.append(path)
        it = QListWidgetItem(f"{label}  —  {len(x) / fs:.2f} s, {fs} Hz")
        it.setData(Qt.ItemDataRole.UserRole, len(self.clips) - 1)
        self.list.addItem(it)
        self.list.setCurrentItem(it)
        self._update()

    def _add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Add clips", config.work_dir(),
                                                "WAV audio (*.wav);;All files (*)")
        for p in paths:
            try:
                x, fs = audio.read_wav(p)
            except (OSError, audio.AudioError) as e:
                QMessageBox.warning(self, "VocalFry", f"Could not read {p}:\n{e}")
                continue
            self._add(os.path.basename(p), x, fs, p)

    def _add_current(self, which):
        m = self.main
        if m.analysis is None or (which == "out" and m.result is None):
            return
        name = os.path.splitext(os.path.basename(m.src_path))[0]
        if which == "out":
            self._add(f"{name} (processed)", m.result.y.copy(), m.analysis.fs)
        else:
            self._add(f"{name} (original)", m.clip().x.copy(), m.analysis.fs)

    # ---- apply a preset voice
    def _apply_voice(self):
        items = self.list.selectedItems()
        path = self.voice.currentData()
        if not items or not path:
            return
        try:
            pre = presets.load(path)
        except presets.PresetError as e:
            QMessageBox.warning(self, "VocalFry", str(e))
            return
        st = self.src_tract.value()
        st = None if st < BY_KEY["src_tract"].lo else st
        clean = self.main.settings
        for it in items:
            i = it.data(Qt.ItemDataRole.UserRole)
            _, x, fs = self.clips[i]
            it.setText(it.text() + "   ⏳ " + pre.name)
            self.busy += 1

            def work(i=i, x=x, fs=fs):
                try:
                    a = dsp.analyse(x, fs)
                    s = params.keep_cleanup(presets.apply(pre.values, params.neutral_settings(a.mean_f0, st)), clean)
                    self.voiced.emit(i, dsp.render(a, s).y, pre.name)
                except Exception as e:      # noqa: BLE001 - shown to the user
                    self.voiced.emit(i, None, str(e))
            threading.Thread(target=work, daemon=True).start()
        self._update()

    def _on_voiced(self, i, y, name):
        self.busy -= 1
        label, _, fs = self.clips[i]
        base = label.split("  [")[0]
        it = next(self.list.item(r) for r in range(self.list.count())
                  if self.list.item(r).data(Qt.ItemDataRole.UserRole) == i)
        if y is None:
            it.setText(f"{base}  —  {len(self.clips[i][1]) / fs:.2f} s, {fs} Hz")
            QMessageBox.warning(self, "VocalFry", f"Could not apply the voice to {base}:\n{name}")
        else:
            stem = os.path.splitext(base)[0]
            out = os.path.join(config.work_dir(), f"{stem}-{config.clean_name(name)}.wav")
            try:
                audio.write_wav(out, y, fs)
                saved = f"saved {os.path.basename(out)}"
            except OSError as e:
                saved = f"not saved: {e}"
            self.clips[i] = (f"{base}  [{name}]", y, fs)
            it.setText(f"{base}  [{name}]  —  {len(y) / fs:.2f} s, {fs} Hz")
            self.main.statusBar().showMessage(f"{base}: applied {name}, {saved}")
        self._update()

    def _remove(self):
        r = self.list.currentRow()
        if r >= 0:
            self.list.takeItem(r)
            self._update()

    def _move(self, d):
        r = self.list.currentRow()
        if r < 0 or not 0 <= r + d < self.list.count():
            return
        it = self.list.takeItem(r)
        self.list.insertItem(r + d, it)
        self.list.setCurrentRow(r + d)
        self._update()

    def _reordered(self, *_):
        self._update()

    def _ordered(self):
        return [self.clips[self.list.item(i).data(Qt.ItemDataRole.UserRole)]
                for i in range(self.list.count())]

    def _joined(self):
        clips = self._ordered()
        if not clips:
            return None, 0
        return audio.join_clips([(x, fs) for _, x, fs in clips], self.gap.value(), self.fade.value())

    def _update(self, *_):
        m = self.main
        self.add_out.setEnabled(m.result is not None)
        self.add_src.setEnabled(m.analysis is not None)
        clips = self._ordered()
        name = self.name.text().strip()
        self.next_lab.setText(f"Next take: <b>{os.path.basename(config.next_take(config.WORK_DIR, name))}</b>"
                              f" in {config.WORK_DIR}" if name else "Give the take a name to save numbered takes.")
        for b in (self.play_b, self.save_b, self.video_b, self.edit_b):
            b.setEnabled(len(clips) > 0)
        self.take_b.setEnabled(len(clips) > 0 and bool(name) and not self.busy)
        self.voice_b.setEnabled(bool(self.list.selectedItems()) and self.voice.count() > 0)
        for b in (self.play_b, self.save_b, self.video_b, self.edit_b):
            b.setEnabled(b.isEnabled() and not self.busy)
        if not clips:
            self.total.setText("No clips yet.")
            return
        fs = clips[0][2]
        n = len(clips)
        secs = sum(len(x) / r for _, x, r in clips)
        if self.fade.value() > 0:
            secs -= (n - 1) * self.fade.value() / 1000
        else:
            secs += (n - 1) * self.gap.value() / 1000
        rates = {r for _, _, r in clips}
        note = f" (other rates resampled to {fs} Hz)" if len(rates) > 1 else ""
        self.total.setText(f"{n} clip{'s' * (n != 1)} → about {max(secs, 0):.2f} s at {fs} Hz{note}")

    # ---- output
    def _write_tmp(self):
        y, fs = self._joined()
        if y is None:
            return None
        path = os.path.join(self.main.tmp, f"joined-{random.randint(1000, 9999)}.wav")
        audio.write_wav(path, y, fs)
        return path

    def _play(self):
        self.main.player.stop()
        path = self._write_tmp()
        if path:
            try:
                self.player.play(path)
            except audio.AudioError as e:
                QMessageBox.warning(self, "VocalFry", str(e))

    def _save(self):
        y, fs = self._joined()
        if y is None:
            return
        name = self.name.text().strip()
        start = config.next_take(config.work_dir(), name) if name else \
            os.path.join(config.work_dir(), "joined.wav")
        p, _ = QFileDialog.getSaveFileName(self, "Save joined clips", start, "WAV audio (*.wav)")
        if p:
            if not p.lower().endswith(".wav"):
                p += ".wav"
            audio.write_wav(p, y, fs)
            self.main.statusBar().showMessage(f"Saved {p} ({len(y) / fs:.1f} s)")

    def _save_take(self):
        name = self.name.text().strip()
        y, fs = self._joined()
        if y is None or not name:
            return
        p = config.next_take(config.work_dir(), name)
        try:
            audio.write_wav(p, y, fs)
        except OSError as e:
            QMessageBox.warning(self, "VocalFry", f"Could not save {p}:\n{e}")
            return
        config.put("take_name", name)
        self.main.statusBar().showMessage(f"Saved take {os.path.basename(p)} ({len(y) / fs:.1f} s) in {config.WORK_DIR}")
        self._update()

    def _video(self):
        y, fs = self._joined()
        if y is not None:
            VideoDialog(self, y, fs, self.name.text().strip()).exec()

    def _open_in_editor(self):
        path = self._write_tmp()
        if path:
            self.player.stop()
            self.main.open_file(path)
            self.accept()

    def done(self, r):
        self.player.stop()
        super().done(r)


# ---------------------------------------------------------------- script panel
class ScriptPanel(QWidget):
    """A text box with lines to read aloud while recording."""

    def __init__(self, parent: "MainWindow"):
        super().__init__(parent)
        self.main = parent
        self.path = ""
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 4)
        bar = QHBoxLayout()

        def btn(text, slot, tip):
            b = QToolButton()
            b.setText(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            bar.addWidget(b)
        btn("Open…", self._open, "Open a script (.txt)")
        btn("Save…", self._save, "Save this script as a text file")
        btn("Example", self._example, "Put back the example script")
        bar.addStretch(1)
        bar.addWidget(QLabel("Size"))
        self.size = QSpinBox()
        self.size.setRange(8, 48)
        self.size.setValue(15)
        self.size.setToolTip("Text size (Ctrl+wheel over the text works too)")
        self.size.valueChanged.connect(self._font)
        bar.addWidget(self.size)
        v.addLayout(bar)
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("Type or paste something to read while you record…")
        self.text.wheelEvent = self._wheel
        v.addWidget(self.text, 1)
        self.save_timer = QTimer(self, singleShot=True, interval=800)
        self.save_timer.timeout.connect(self.store)
        self._restore()
        self.text.textChanged.connect(self.save_timer.start)

    def _font(self, pt):
        f = self.text.font()
        f.setPointSize(pt)
        self.text.setFont(f)
        self.save_timer.start()

    def _wheel(self, e):
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.size.setValue(self.size.value() + (1 if e.angleDelta().y() > 0 else -1))
        else:
            QPlainTextEdit.wheelEvent(self.text, e)

    def _read(self, path):
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                return f.read()
        except OSError as e:
            QMessageBox.warning(self, "VocalFry", f"Could not read {path}:\n{e}")
            return None

    def _restore(self):
        try:
            with open(SCRIPT_STATE) as f:
                st = json.load(f)
            self.text.setPlainText(str(st.get("text", "")))
            self.size.setValue(int(st.get("size", 15)))
            self.path = str(st.get("path", ""))
        except (OSError, ValueError, TypeError, AttributeError):
            self._example()
        self._font(self.size.value())

    def store(self):
        try:
            os.makedirs(os.path.dirname(SCRIPT_STATE), exist_ok=True)
            with open(SCRIPT_STATE, "w") as f:
                json.dump({"text": self.text.toPlainText(), "size": self.size.value(),
                           "path": self.path}, f)
        except OSError:
            pass

    def _example(self):
        t = self._read(EXAMPLE_SCRIPT) if os.path.exists(EXAMPLE_SCRIPT) else None
        if t is not None:
            self.text.setPlainText(t)
            self.path = ""

    def _open(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open script", os.path.dirname(self.path) or SCRIPT_DIR,
                                           "Text (*.txt);;All files (*)")
        t = self._read(p) if p else None
        if t is not None:
            self.text.setPlainText(t)
            self.path = p

    def _save(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save script", self.path or os.path.expanduser("~/script.txt"),
                                           "Text (*.txt)")
        if not p:
            return
        if not os.path.splitext(p)[1]:
            p += ".txt"
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(self.text.toPlainText())
        except OSError as e:
            QMessageBox.warning(self, "VocalFry", f"Could not save {p}:\n{e}")
            return
        self.path = p
        self.store()
        self.main.statusBar().showMessage(f"Saved script to {p}")


class ScriptWindow(QWidget):
    closed = pyqtSignal()

    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.Window)

    def closeEvent(self, e):
        self.closed.emit()
        super().closeEvent(e)


# ---------------------------------------------------------------- main window
class MainWindow(QMainWindow):
    def __init__(self, path: str | None = None, boxapella_out: str = "", settings_file: str = "",
                 keep_key: bool = False):
        super().__init__()
        # Opened by Boxapella on one take: "Send to Boxapella" writes the voice
        # to boxapella_out; settings_file (a preset or saved settings) is applied
        # once the recording has been analysed, and keep_key turns Keep key on.
        self.boxapella_out = boxapella_out
        self._initial_settings = settings_file
        self._initial_keep_key = keep_key
        self.setWindowTitle("VocalFry")
        if os.path.exists(ICON):
            self.setWindowIcon(QIcon(ICON))
        self.sig = Signals()
        self.sig.analysed.connect(self._on_analysed)
        self.sig.rendered.connect(self._on_rendered)
        self.sig.progress.connect(lambda t: self.statusBar().showMessage(t))
        self.analysis: dsp.Analysis | None = None
        self.trim = (0, 0)                  # kept frames [start, end) of the analysis
        self.result: dsp.Result | None = None
        self.src_path = ""
        self.neutral = params.neutral_settings()
        self.settings = dict(self.neutral)
        self.player, self.recorder = audio.Player(), audio.Recorder()
        self.tmp = tempfile.mkdtemp(prefix="vocalfry-")
        self.job = 0
        self.rendering = False
        self.dirty = False
        self.render_timer = QTimer(self, singleShot=True, interval=220)
        self.render_timer.timeout.connect(self._render)
        self._play_when_done = False
        self._build()
        self._refresh_presets()
        self._sync_controls()
        if path:
            self.open_file(path)

    # ---- layout
    def _build(self):
        tb = self.addToolBar("Main")
        tb.setMovable(False)

        def act(text, slot, tip="", key=None):
            a = QAction(text, self)
            a.setToolTip(tip or text)
            if key:
                a.setShortcut(key)
            a.triggered.connect(slot)
            tb.addAction(a)
            return a
        act("Open…", self._open_dialog, "Open a WAV recording", "Ctrl+O")
        self.rec_act = act("● Record", self._toggle_record, "Record from the microphone", "Ctrl+R")
        tb.addSeparator()
        self.play_src = act("▶ Original", lambda: self._play("src"), "Play the original (A)", "A")
        self.play_out = act("▶ Processed", lambda: self._play("out"), "Play the processed voice (B)", "B")
        act("■ Stop", self._stop, "Stop playback (Esc)", "Esc")
        tb.addSeparator()
        act("Save voice…", self._save_audio, "Save the processed voice as WAV", "Ctrl+S")
        if self.boxapella_out:
            act("⮐ Send to Boxapella", self._send_to_boxapella,
                "Use this voice for the take in Boxapella (whole take, timing kept)", "Ctrl+Return")
        act("Append clips…", self._join, "Join saved WAV clips end to end", "Ctrl+J")
        act("Batch…", self._batch, "Export many random plausible speakers")
        tb.addSeparator()
        # A plain top-level window, so the desktop draws its title bar and moves it
        # (on Wayland a floating dock's Qt-drawn title bar can't be dragged).
        self.script_win = ScriptWindow(self)
        self.script_win.setWindowTitle("VocalFry — Script")
        if os.path.exists(ICON):
            self.script_win.setWindowIcon(QIcon(ICON))
        self.script = ScriptPanel(self)
        QVBoxLayout(self.script_win).addWidget(self.script)
        self.script_win.layout().setContentsMargins(0, 0, 0, 0)
        self.script_win.resize(590, 530)      # half the width, twice the height of the old bottom strip
        sa = QAction("📜 Script", self, checkable=True)
        sa.setToolTip("Show or hide the script to read from (Ctrl+T)")
        sa.setShortcut("Ctrl+T")
        sa.toggled.connect(self.script_win.setVisible)
        self.script_win.closed.connect(lambda: sa.setChecked(False))
        self.script_act = sa
        tb.addAction(sa)
        tb.addSeparator()
        act("Load settings…", self._load_settings, "Load slider settings (.json)")
        act("Save settings…", self._save_settings, "Save slider settings (.json)")

        split = QSplitter()
        self.setCentralWidget(split)

        # left: controls
        left = QWidget()
        lv = QVBoxLayout(left)
        top = QHBoxLayout()
        self.preset = QComboBox()
        self.preset.setToolTip("Presets whose file says to show them in this menu")
        self.preset.activated.connect(self._preset)
        open_pre = QPushButton("Open preset…")
        open_pre.setToolTip("Open a preset file: apply it, and choose whether it\nappears in the Preset menu")
        open_pre.clicked.connect(self._open_preset)
        save_pre = QPushButton("Save preset…")
        save_pre.setToolTip("Save the current voice as a preset file")
        save_pre.clicked.connect(self._save_preset)
        rnd = QPushButton("🎲 Random speaker")
        rnd.setToolTip("A random voice: inside the plausible human range while\n"
                       "Keep within human range is ticked, anywhere on the map when not")
        rnd.clicked.connect(self._random)
        reset = QPushButton("Reset all")
        reset.clicked.connect(self._reset_all)
        top.addWidget(self.preset, 1)
        top.addWidget(open_pre)
        top.addWidget(save_pre)
        lv.addLayout(top)
        top2 = QHBoxLayout()
        top2.addWidget(rnd)
        top2.addWidget(reset)
        top2.addStretch(1)
        self.default_lab = QLabel()
        self.default_lab.setToolTip("Applied to every new recording or opened file")
        top2.addWidget(self.default_lab)
        lv.addLayout(top2)

        self.rows: dict[str, ParamRow] = {}
        self.group_boxes: dict[str, QGroupBox] = {}
        for g, label in GROUPS:
            box = QGroupBox(label)
            box.setCheckable(True)
            box.setChecked(True)
            box.setToolTip("Untick to bypass this whole group")
            box.toggled.connect(lambda on, g=g: self._group(g, on))
            grid = QGridLayout(box)
            grid.setColumnStretch(1, 1)
            for i, p in enumerate(q for q in PARAMS if q.group == g):
                self.rows[p.key] = ParamRow(p, grid, i, self._changed)
            if g == "tract":
                self.ratio_lab = QLabel()
                grid.addWidget(self.ratio_lab, grid.rowCount(), 0, 1, 4)
            self.group_boxes[g] = box
            lv.addWidget(box)
        lv.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(left)
        scroll.setMinimumWidth(470)
        split.addWidget(scroll)

        # right: map, contour, info
        right = QWidget()
        rv = QVBoxLayout(right)
        self.map = VoiceMap()
        self.map.moved.connect(self._map_moved)
        rv.addWidget(self.map, 3)
        opts = QHBoxLayout()
        self.link = QCheckBox("Keep within human range")
        self.link.setToolTip("Pitch and tract length pull each other along so the\n"
                             "combination stays inside the shaded band.")
        self.link.setChecked(True)
        self.audition = QCheckBox("Play after each change")
        self.audition.setChecked(True)
        opts.addWidget(self.link)
        opts.addWidget(self.audition)
        opts.addStretch(1)
        rv.addLayout(opts)
        self.contour = Contour()
        self.contour.trimmed.connect(self._trimmed)
        self.contour.menu_actions = [("Reset trim", self._reset_trim),
                                     ("Save trimmed original…", self._save_trimmed_src)]
        rv.addWidget(self.contour, 2)
        self.info = QLabel("No recording loaded.")
        self.info.setWordWrap(True)
        rv.addWidget(self.info)
        split.addWidget(right)
        split.setSizes([520, 560])
        self.resize(1180, 760)
        self.statusBar().showMessage("Open a WAV file or record your voice.")

    # ---- settings <-> controls
    def _sync_controls(self):
        for k, row in self.rows.items():
            row.neutral = self.neutral[k]
            row.set(self.settings[k])
        for g, box in self.group_boxes.items():
            box.blockSignals(True)
            box.setChecked(self.settings.get("on_" + g, True))
            box.blockSignals(False)
        s = self.settings
        r = s["src_tract"] / s["tract"]
        self.ratio_lab.setText(f"Formant scaling ×{r:.2f}  "
                               f"({'higher / smaller' if r > 1.005 else 'lower / larger' if r < 0.995 else 'unchanged'})")
        src = (self.analysis.mean_f0, s["src_tract"]) if self.analysis else None
        self.map.set_point(s["pitch_hz"], s["tract"], src)

    def _changed(self, key, v):
        s = self.settings
        s[key] = params.clamp(key, v)
        if self.link.isChecked():
            if key == "pitch_hz":
                s["tract"] = round(params.clamp_tract(s["pitch_hz"], s["tract"]), 1)
            elif key == "tract":
                s["pitch_hz"] = round(params.clamp_pitch(s["pitch_hz"], s["tract"]), 1)
        self._sync_controls()
        self._schedule()

    def _map_moved(self, f0, L):
        s = self.settings
        s["pitch_hz"], s["tract"] = params.clamp("pitch_hz", f0), params.clamp("tract", L)
        if self.link.isChecked():
            s["tract"] = round(params.clamp_tract(s["pitch_hz"], s["tract"]), 1)
        self._sync_controls()
        self._schedule()

    def _group(self, g, on):
        self.settings["on_" + g] = on
        self._schedule()

    def _refresh_presets(self):
        self.menu_presets = presets.menu()
        self.preset.clear()
        self.preset.addItem("Preset…" if self.menu_presets else "Preset… (none in menu)")
        dv = config.default_voice()
        for p in self.menu_presets:
            self.preset.addItem(("★ " if dv and dv.path == p.path else "") + p.name)
            self.preset.setItemData(self.preset.count() - 1, p.path, Qt.ItemDataRole.ToolTipRole)
        self.map.presets = presets.on_map()
        self.default_lab.setText(f"★ Default voice: <b>{dv.name}</b>" if dv else
                                 "No default voice (Open preset… to choose one)")
        self.map.update()

    def _preset(self, i):
        self.preset.setCurrentIndex(0)
        if i <= 0:
            return
        p = self.menu_presets[i - 1]
        try:
            p = presets.load(p.path)        # pick up edits made since the menu was built
        except presets.PresetError as e:
            QMessageBox.warning(self, "VocalFry", str(e))
            self._refresh_presets()
            return
        self._apply_preset(p)

    def _apply_preset(self, p: presets.Preset):
        self.settings = params.keep_cleanup(presets.apply(p.values, self.neutral), self.settings)
        self.statusBar().showMessage(f"Preset: {p.name}")
        self._sync_controls()
        self._schedule()

    def _open_preset(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open preset", presets.PRESET_DIR,
                                              "VocalFry presets (*.json);;All files (*)")
        if not path:
            return
        try:
            p = presets.load(path)
        except presets.PresetError as e:
            QMessageBox.warning(self, "VocalFry", str(e))
            return
        presets.remember(path)          # its own "menu" flag now counts
        self._refresh_presets()
        PresetDialog(self, p).exec()

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "Save preset", "Preset name:")
        name = name.strip()
        if not ok or not name:
            return
        fn = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "preset"
        path, _ = QFileDialog.getSaveFileName(self, "Save preset", os.path.join(presets.PRESET_DIR, fn + ".json"),
                                              "VocalFry presets (*.json)")
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        p = presets.from_settings(name, path, self.settings)
        try:
            presets.save(p)
        except OSError as e:
            QMessageBox.warning(self, "VocalFry", f"Could not save {path}:\n{e}")
            return
        presets.remember(path)
        self.statusBar().showMessage(f"Saved preset {name} to {path}")
        PresetDialog(self, p, just_saved=True).exec()

    def _random(self):
        seed = random.randint(1, 999999)
        self.settings = params.keep_cleanup(
            params.random_speaker(self.neutral, random.Random(seed), human=self.link.isChecked()),
            self.settings)
        where = "" if self.link.isChecked() else ", anywhere on the map"
        self.statusBar().showMessage(f"Random speaker (seed {seed}{where})")
        self._sync_controls()
        self._schedule()

    def _reset_all(self):
        src = self.settings["src_tract"]
        self.settings = params.keep_cleanup(dict(self.neutral, src_tract=src, tract=src), self.settings)
        self._sync_controls()
        self._schedule()

    # ---- loading
    def _open_dialog(self):
        p, _ = QFileDialog.getOpenFileName(self, "Open recording", os.path.dirname(self.src_path) or os.path.expanduser("~"),
                                           "WAV audio (*.wav);;All files (*)")
        if p:
            self.open_file(p)

    def open_file(self, path):
        try:
            x, fs = audio.read_wav(path)
        except (OSError, audio.AudioError) as e:
            QMessageBox.warning(self, "VocalFry", f"Could not read {path}:\n{e}")
            return
        self.player.stop()
        self.src_path = path
        self.analysis = self.result = None
        self.contour.set_tracks(None, None)
        self.setWindowTitle(f"VocalFry — {os.path.basename(path)}")
        self.statusBar().showMessage(f"Analysing {os.path.basename(path)} ({len(x) / fs:.1f} s)…")

        def work():
            try:
                a = dsp.analyse(x, fs, self.sig.progress.emit)
                self.sig.analysed.emit(a, "")
            except Exception as e:      # noqa: BLE001 - shown to the user
                self.sig.analysed.emit(None, str(e))
        threading.Thread(target=work, daemon=True).start()

    def _on_analysed(self, a, err):
        if a is None:
            QMessageBox.warning(self, "VocalFry", f"Analysis failed:\n{err}")
            return
        self.analysis = a
        self.trim = (0, a.frames)
        self._drop_src_cache()
        keep, old_neutral = dict(self.settings), self.neutral
        self.neutral = params.neutral_settings(a.mean_f0)
        voiced = float((a.f0 > 0).mean() * 100)
        self.info.setText(f"<b>{os.path.basename(self.src_path)}</b> — {a.duration:.1f} s at {a.fs} Hz · "
                          f"mean pitch {a.mean_f0:.0f} Hz · voiced {voiced:.0f}% · "
                          f"estimated tract {self.neutral['src_tract']} cm (from pitch; adjust "
                          f"<i>Source tract length</i> if you know better)")
        # A fresh file takes the default voice if there is one. Otherwise the voice
        # dialled in so far carries over: pitch and tract length only if they were
        # moved off the last recording's neutral (else they follow the new one),
        # every other control as it is. Source tract length belongs to the file.
        dv = config.default_voice()
        self.settings = dict(self.neutral)
        if dv:
            self.settings = params.keep_cleanup(presets.apply(dv.values, self.neutral), keep)
        else:
            for k, v in keep.items():
                if k == "src_tract":
                    continue
                if k in ("pitch_hz", "tract") and v == old_neutral.get(k):
                    continue
                self.settings[k] = v
        if self._initial_settings:
            self._apply_settings_file(self._initial_settings)
            self._initial_settings = ""
        if self._initial_keep_key:
            self.settings["keep_key"] = 1.0
            self._initial_keep_key = False
        self.contour.set_tracks(a.f0, None)
        self._sync_controls()
        if self.boxapella_out:
            self.statusBar().showMessage("Shape the voice, then press ⮐ Send to Boxapella (Ctrl+Enter).")
            self._schedule(play=False)
            return
        self.statusBar().showMessage(f"Ready, in your default voice ({dv.name})." if dv else
                                     "Ready. Move a slider, pick a preset or roll a random speaker.")
        self._schedule(play=False)

    # ---- trimming
    def clip(self) -> dsp.Analysis:
        """The analysis cut to the trim handles."""
        return dsp.trim(self.analysis, *self.trim)

    def _drop_src_cache(self):
        try:
            os.remove(os.path.join(self.tmp, "src.wav"))
        except OSError:
            pass

    def _trimmed(self, start, end):
        if self.analysis is None or (start, end) == self.trim:
            return
        self.trim = (start, end)
        self._drop_src_cache()
        ms = dsp.FRAME_MS / 1000
        self.statusBar().showMessage(f"Trimmed to {start * ms:.2f}–{end * ms:.2f} s "
                                     f"({(end - start) * ms:.2f} s of {self.analysis.duration:.2f} s)")
        self._schedule()

    def _reset_trim(self):
        if self.analysis is not None:
            self.contour.set_trim(0, self.analysis.frames)
            self._trimmed(0, self.analysis.frames)

    def _save_trimmed_src(self):
        if self.analysis is None:
            return
        p, _ = QFileDialog.getSaveFileName(self, "Save trimmed original", self._default_out("-trimmed.wav"),
                                           "WAV audio (*.wav)")
        if p:
            if not p.lower().endswith(".wav"):
                p += ".wav"
            c = self.clip()
            audio.write_wav(p, c.x, c.fs)
            self.statusBar().showMessage(f"Saved {p} ({c.duration:.2f} s)")

    # ---- rendering
    def _schedule(self, play=True):
        if self.analysis is None:
            return
        self._play_when_done = play and self.audition.isChecked()
        self.render_timer.start()

    def _render(self):
        if self.analysis is None:
            return
        if self.rendering:
            self.dirty = True
            return
        self.rendering, self.dirty = True, False
        self.job += 1
        job, a, s = self.job, self.clip(), dict(self.settings)
        self.statusBar().showMessage("Rendering…")

        def work():
            try:
                res = dsp.render(a, s)
            except Exception as e:      # noqa: BLE001
                res = e
            self.sig.rendered.emit(res, job)
        threading.Thread(target=work, daemon=True).start()

    def _on_rendered(self, res, job):
        self.rendering = False
        if isinstance(res, Exception):
            self.statusBar().showMessage(f"Render failed: {res}")
        else:
            self.result = res
            audio.write_wav(os.path.join(self.tmp, "out.wav"), res.y, self.analysis.fs)
            self.contour.set_tracks(self.analysis.f0, res.f0, res.cleaned, res.events)
            self.statusBar().showMessage(f"Rendered {len(res.y) / self.analysis.fs:.1f} s.")
        if self.dirty:
            self._render()
        elif self._play_when_done and not isinstance(res, Exception):
            self._play("out")

    # ---- playback / recording
    def _play(self, which):
        if self.analysis is None:
            return
        if which == "src":
            path = os.path.join(self.tmp, "src.wav")
            if not os.path.exists(path):
                audio.write_wav(path, self.clip().x, self.analysis.fs)
        else:
            path = os.path.join(self.tmp, "out.wav")
            if self.result is None or not os.path.exists(path):
                return
        try:
            self.player.play(path)
        except audio.AudioError as e:
            QMessageBox.warning(self, "VocalFry", str(e))

    def _stop(self):
        self.player.stop()

    def _toggle_record(self):
        if self.recorder.recording():
            path = self.recorder.stop()
            self.rec_act.setText("● Record")
            if os.path.exists(path) and os.path.getsize(path) > 1000:
                self.open_file(path)
            else:
                self.statusBar().showMessage("Nothing was recorded.")
            return
        self.player.stop()
        path = os.path.join(self.tmp, f"recording-{random.randint(1000, 9999)}.wav")
        try:
            self.recorder.start(path)
        except audio.AudioError as e:
            QMessageBox.warning(self, "VocalFry", str(e))
            return
        self.rec_act.setText("■ Stop recording")
        self.statusBar().showMessage("Recording… press Stop recording (Ctrl+R) when done.")

    # ---- saving
    def _default_out(self, suffix):
        base = os.path.splitext(os.path.basename(self.src_path or "voice"))[0]
        return os.path.join(config.work_dir(), base + suffix)

    def _save_audio(self):
        if self.result is None:
            return
        p, _ = QFileDialog.getSaveFileName(self, "Save processed voice", self._default_out("-vocalfry.wav"),
                                           "WAV audio (*.wav)")
        if p:
            if not p.lower().endswith(".wav"):
                p += ".wav"
            audio.write_wav(p, self.result.y, self.analysis.fs)
            self.statusBar().showMessage(f"Saved {p}")

    def _apply_settings_file(self, path):
        """A preset file (pitch/tract absolute, rest neutral) or saved settings."""
        try:
            with open(path) as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "VocalFry", f"Could not read {path}:\n{e}")
            return
        if "preset" in data:
            self.settings = params.keep_cleanup(presets.apply(data.get("settings", {}), self.neutral),
                                                self.settings)
            return
        self.settings = dict(self.neutral)
        for k, v in data.get("settings", data).items():
            if k in BY_KEY:
                self.settings[k] = params.clamp(k, v)
            elif k.startswith("on_"):
                self.settings[k] = bool(v)

    def _send_to_boxapella(self):
        """Render the whole take (no trim, speaking rate and pauses kept, so it stays
        in sync with the video) and write it plus its settings for Boxapella."""
        if self.analysis is None:
            return
        s = dict(self.settings, rate=100.0, pause=100.0)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            y = dsp.render(self.analysis, s).y
            n = len(self.analysis.x)            # exactly the take's length
            y = np.pad(y, (0, max(0, n - len(y))))[:n]
            out = self.boxapella_out
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
            with open(os.path.splitext(out)[0] + ".voice.json", "w") as f:
                json.dump({"vocalfry": 1, "settings": s}, f, indent=2)
            tmp = out[:-4] + ".sending.wav"
            audio.write_wav(tmp, y, self.analysis.fs)
            os.replace(tmp, out)
        except Exception as e:      # noqa: BLE001 - shown to the user
            QApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "VocalFry", f"Could not send the voice:\n{e}")
            return
        QApplication.restoreOverrideCursor()
        self.statusBar().showMessage(f"Sent to Boxapella ({os.path.basename(out)}). "
                                     "Keep shaping and send again, or close VocalFry.")

    def _save_settings(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save settings", self._default_out("-voice.json"),
                                           "VocalFry settings (*.json)")
        if p:
            with open(p, "w") as f:
                json.dump({"vocalfry": 1, "settings": self.settings}, f, indent=2)
            self.statusBar().showMessage(f"Saved {p}")

    def _load_settings(self):
        p, _ = QFileDialog.getOpenFileName(self, "Load settings", os.path.dirname(self.src_path) or os.path.expanduser("~"),
                                           "VocalFry settings (*.json)")
        if not p:
            return
        try:
            with open(p) as f:
                data = json.load(f)
            loaded = data.get("settings", data)
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, "VocalFry", f"Could not read {p}:\n{e}")
            return
        for k, v in loaded.items():
            if k in BY_KEY:
                self.settings[k] = params.clamp(k, v)
            elif k.startswith("on_"):
                self.settings[k] = bool(v)
        self._sync_controls()
        self._schedule()

    def _join(self):
        self.player.stop()
        JoinDialog(self).exec()

    def _batch(self):
        if self.analysis is None:
            QMessageBox.information(self, "VocalFry", "Open or record a voice first.")
            return
        dlg = BatchDialog(self, self._default_out("-speakers"))
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        n, seed, folder = dlg.count.value(), dlg.seed.value(), dlg.folder.text()
        which = {g for g, cb in dlg.groups.items() if cb.isChecked()}
        prog = QProgressDialog("Rendering speakers…", "Cancel", 0, n, self)
        prog.setWindowModality(Qt.WindowModality.WindowModal)
        prog.setMinimumDuration(0)
        cancel = threading.Event()
        prog.canceled.connect(cancel.set)
        self.sig.batch_step.connect(prog.setValue)

        def finished(msg):
            prog.close()
            self.sig.batch_step.disconnect(prog.setValue)
            self.sig.batch_done.disconnect(finished)
            self.statusBar().showMessage(msg)
        self.sig.batch_done.connect(finished)
        a = self.clip()
        neutral = params.keep_cleanup(dict(self.neutral, src_tract=self.settings["src_tract"]), self.settings)

        def work():
            try:
                done = export_batch(a, neutral, n, seed, folder, which,
                                    step=self.sig.batch_step.emit, cancel=cancel)
                self.sig.batch_done.emit(f"Exported {done} speakers to {folder}")
            except Exception as e:      # noqa: BLE001
                self.sig.batch_done.emit(f"Batch failed: {e}")
        threading.Thread(target=work, daemon=True).start()

    def closeEvent(self, e):
        self.script.store()
        self.script_win.close()
        self.player.stop()
        self.recorder.stop()
        super().closeEvent(e)


def export_batch(a, neutral, n, seed, folder, which=None, step=None, cancel=None) -> int:
    """Render n random plausible speakers into folder; returns the count written."""
    os.makedirs(folder, exist_ok=True)
    rng = random.Random(seed)
    index = []
    for i in range(n):
        if cancel is not None and cancel.is_set():
            break
        s = params.random_speaker(neutral, rng, which)
        name = f"speaker_{i + 1:03d}.wav"
        audio.write_wav(os.path.join(folder, name), dsp.render(a, s, seed=seed + i).y, a.fs)
        index.append({"file": name, "settings": s})
        if step:
            step(i + 1)
    with open(os.path.join(folder, "speakers.json"), "w") as f:
        json.dump({"vocalfry": 1, "seed": seed, "speakers": index}, f, indent=2)
    return len(index)


def run(path: str | None = None, boxapella_out: str = "", settings_file: str = "",
        keep_key: bool = False) -> int:
    app = QApplication.instance() or QApplication([])
    app.setApplicationName("VocalFry")
    app.setDesktopFileName("vocalfry")
    w = MainWindow(path, boxapella_out, settings_file, keep_key)
    w.show()
    return app.exec()
