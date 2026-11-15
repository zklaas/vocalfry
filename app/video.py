"""Still-image .mp4 export: a title card drawn with QPainter + the audio, via ffmpeg.

ffmpeg comes from the imageio-ffmpeg package in .venv (its bundled binary), or
a system ffmpeg if that's missing.
"""
from __future__ import annotations

import os
import shutil
import subprocess

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QImage, QPainter

SIZE = (1280, 720)
STYLES = {               # name: (background, title, description, accent)
    "Dark": ("#16161c", "#ffffff", "#c9c9d2", "#c8352b"),
    "Light": ("#f6f3ee", "#1d1d22", "#45454f", "#c8352b"),
    "Fry red": ("#c8352b", "#ffffff", "#ffe3a0", "#e8a923"),
}


class VideoError(Exception):
    pass


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:            # noqa: BLE001 - fall back to the system's
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
    raise VideoError("No ffmpeg found. Install it with:\n"
                     "  .venv/bin/pip install imageio-ffmpeg   (or: sudo apt install ffmpeg;"
                     " on macOS: brew install ffmpeg)")


def title_card(title: str, description: str, style: str = "Dark", size=SIZE) -> QImage:
    """The video's single frame: title large, description wrapped beneath."""
    w, h = size
    bg, fg, sub, accent = (QColor(c) for c in STYLES.get(style, STYLES["Dark"]))
    img = QImage(w, h, QImage.Format.Format_RGB32)
    img.fill(bg)
    qp = QPainter(img)
    qp.setRenderHint(QPainter.RenderHint.Antialiasing)
    qp.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    margin = w * 0.08
    box = QRectF(margin, h * 0.12, w - 2 * margin, h * 0.76)
    flags = Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap

    def fitted(text, px, bold, max_h):
        """A font no bigger than px whose wrapped text fits in max_h."""
        while True:
            f = QFont("Sans Serif")
            f.setPixelSize(max(10, int(px)))
            f.setBold(bold)
            qp.setFont(f)
            r = qp.boundingRect(QRectF(0, 0, box.width(), 10_000), flags, text)
            if r.height() <= max_h or px <= 10:
                return f, r.height()
            px *= 0.9

    title, description = title.strip(), description.strip()
    tf, th = fitted(title, h * 0.11, True, box.height() * (0.5 if description else 1)) if title else (None, 0)
    gap = h * 0.05 if title and description else 0
    df, dh = fitted(description, h * 0.045, False, box.height() - th - gap) if description else (None, 0)
    y = box.top() + (box.height() - th - gap - dh) / 2
    if title:
        qp.setFont(tf)
        qp.setPen(fg)
        qp.drawText(QRectF(box.left(), y, box.width(), th), flags, title)
        y += th
    if title and description:
        qp.fillRect(QRectF(w / 2 - w * 0.05, y + gap / 2 - 2, w * 0.1, 4), accent)
        y += gap
    if description:
        qp.setFont(df)
        qp.setPen(sub)
        qp.drawText(QRectF(box.left(), y, box.width(), dh), flags, description)
    qp.end()
    return img


def make_mp4(wav: str, image: str, out: str) -> None:
    """Encode the still image for the length of the audio (H.264 + AAC)."""
    cmd = [ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
           "-loop", "1", "-framerate", "25", "-i", image, "-i", wav,
           "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out]
    kw = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw)
    if p.returncode != 0:
        raise VideoError(p.stderr.strip() or f"ffmpeg failed ({p.returncode})")
