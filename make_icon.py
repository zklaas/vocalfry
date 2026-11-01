#!/usr/bin/env python3
"""Draw the VocalFry icon: a stylised fry sleeve full of fries.

Uses Qt's painter offscreen, so it needs nothing beyond PyQt6.  Writes
icons/vocalfry.png (512 px) plus 256/128/64/48 px copies; run
./install-desktop.sh afterwards to refresh the dash icon.
"""
from __future__ import annotations

import os
import random
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import (QBrush, QColor, QGuiApplication, QImage,
                         QLinearGradient, QPainter, QPainterPath, QPen)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "icons")
S = 512


def sleeve_front() -> QPainterPath:
    """Front panel: tapers to the base, top edge dips in a wide U."""
    p = QPainterPath(QPointF(92, 214))
    p.cubicTo(QPointF(170, 330), QPointF(342, 330), QPointF(420, 214))
    p.lineTo(QPointF(372, 482))
    p.quadTo(QPointF(256, 500), QPointF(140, 482))
    p.closeSubpath()
    return p


def draw(qp: QPainter) -> None:
    qp.setRenderHint(QPainter.RenderHint.Antialiasing)
    # back panel of the sleeve (seen above the front's dip)
    back = QPainterPath(QPointF(104, 150))
    back.quadTo(QPointF(256, 120), QPointF(408, 150))
    back.lineTo(QPointF(420, 214))
    back.lineTo(QPointF(92, 214))
    back.closeSubpath()
    qp.setPen(Qt.PenStyle.NoPen)
    qp.setBrush(QColor("#8f1f1a"))
    qp.drawPath(back)

    # fries: fanned golden sticks, back row first
    rng = random.Random(7)
    gold = [QColor("#f7c948"), QColor("#f2b631"), QColor("#fad46a"), QColor("#eaa628")]
    rows = [(26, 118, 9, 300), (22, 150, 8, 285), (18, 182, 7, 270)]
    for w, top, count, base in rows:
        for i in range(count):
            fx = 128 + i * (256 / (count - 1)) + rng.uniform(-6, 6)
            ang = (fx - 256) / 256 * 14 + rng.uniform(-3, 3)
            h = base - top + rng.uniform(-18, 22)
            qp.save()
            qp.translate(fx, base)
            qp.rotate(ang)
            body = QRectF(-w / 2, -h, w, h + 60)
            g = QLinearGradient(QPointF(-w / 2, 0), QPointF(w / 2, 0))
            c = rng.choice(gold)
            g.setColorAt(0, c.lighter(112))
            g.setColorAt(1, c.darker(118))
            qp.setBrush(QBrush(g))
            qp.setPen(QPen(QColor("#b9781a"), 3))
            qp.drawRoundedRect(body, 5, 5)
            # toasty tip
            qp.setPen(Qt.PenStyle.NoPen)
            qp.setBrush(QColor(196, 120, 30, 120))
            qp.drawRoundedRect(QRectF(-w / 2 + 2, -h + 1, w - 4, 10), 4, 4)
            qp.restore()

    # front panel
    front = sleeve_front()
    g = QLinearGradient(QPointF(92, 0), QPointF(420, 0))
    g.setColorAt(0, QColor("#b8261e"))
    g.setColorAt(0.45, QColor("#e2382b"))
    g.setColorAt(1, QColor("#a82219"))
    qp.setBrush(QBrush(g))
    qp.setPen(QPen(QColor("#6e1410"), 6))
    qp.drawPath(front)
    # rim highlight along the dip
    rim = QPainterPath(QPointF(100, 222))
    rim.cubicTo(QPointF(174, 334), QPointF(338, 334), QPointF(412, 222))
    qp.setPen(QPen(QColor(255, 255, 255, 110), 6, cap=Qt.PenCapStyle.RoundCap))
    qp.setBrush(Qt.BrushStyle.NoBrush)
    qp.drawPath(rim)

    # emblem: a white voice waveform across the sleeve
    wave = QPainterPath()
    xs = list(range(170, 343, 3))
    import math
    for j, x in enumerate(xs):
        t = (x - 170) / 172
        env = math.sin(math.pi * t) ** 1.4
        y = 400 + 34 * env * math.sin(2 * math.pi * 3.2 * t) * math.cos(2 * math.pi * 0.9 * t + 0.4)
        (wave.moveTo if j == 0 else wave.lineTo)(QPointF(x, y))
    qp.setPen(QPen(QColor("#fff6e0"), 11, cap=Qt.PenCapStyle.RoundCap,
                   join=Qt.PenJoinStyle.RoundJoin))
    qp.drawPath(wave)


def write_ico(path, images):
    """A Windows .ico holding PNG-compressed images (sizes up to 256)."""
    import struct
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice
    blobs = []
    for im in images:
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        im.save(buf, "PNG")
        blobs.append((im.width(), bytes(ba)))
    entries, data, offset = b"", b"", 6 + 16 * len(blobs)
    for w, png in blobs:
        entries += struct.pack("<BBBBHHII", w % 256, w % 256, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    with open(path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(blobs)) + entries + data)


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841 - needed for QPainter
    os.makedirs(OUT, exist_ok=True)
    img = QImage(S, S, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    qp = QPainter(img)
    draw(qp)
    qp.end()
    img.save(os.path.join(OUT, "vocalfry.png"))
    for size in (256, 128, 64, 48):
        img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                   Qt.TransformationMode.SmoothTransformation).save(
            os.path.join(OUT, f"vocalfry-{size}.png"))
    write_ico(os.path.join(OUT, "vocalfry.ico"),
              [img.scaled(n, n, Qt.AspectRatioMode.KeepAspectRatio,
                          Qt.TransformationMode.SmoothTransformation) for n in (256, 64, 48, 32, 16)])
    print("wrote", os.path.join(OUT, "vocalfry.png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
