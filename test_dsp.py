"""VocalFry tests:  .venv/bin/python -m unittest test_dsp"""
import os
import struct
import tempfile
import unittest

import numpy as np

from app import audio, dsp, params, presets

HERE = os.path.dirname(os.path.abspath(__file__))
SAMPLE = os.path.join(HERE, "samples", "Front_Center.wav")


class Params(unittest.TestCase):
    def test_typical_tract_monotone_and_inverse(self):
        for f in (80, 120, 200, 300, 420):
            self.assertAlmostEqual(params.typical_tract(params.f0_for_tract(params.typical_tract(f))),
                                   params.typical_tract(f), places=3)
        self.assertGreater(params.typical_tract(100), params.typical_tract(300))

    def test_clamps_land_in_band(self):
        self.assertTrue(params.plausible(300, params.clamp_tract(300, 18)))
        self.assertTrue(params.plausible(params.clamp_pitch(400, 17.5), 17.5))

    def test_random_speakers_plausible(self):
        import random
        n = params.neutral_settings(150)
        r = random.Random(3)
        for _ in range(200):
            s = params.random_speaker(n, r)
            self.assertTrue(params.plausible(s["pitch_hz"], s["tract"]), s)

    def test_random_speakers_unconstrained_cover_plane(self):
        import random
        n = params.neutral_settings(150)
        r = random.Random(4)
        ss = [params.random_speaker(n, r, human=False) for _ in range(400)]
        f0 = [s["pitch_hz"] for s in ss]
        L = [s["tract"] for s in ss]
        self.assertLess(min(f0), 70)
        self.assertGreater(max(f0), 420)
        self.assertLess(min(L), 9)
        self.assertGreater(max(L), 20)
        self.assertGreater(sum(not params.plausible(a, b) for a, b in zip(f0, L)), 100)


class Warp(unittest.TestCase):
    def test_formants_scale_with_tract(self):
        fs, K = 16000, 513
        fr = np.arange(K) * fs / 1024
        log = sum(np.exp(-((fr - p) / 80) ** 2) for p in (500, 1500, 2500))[None, :]
        s = params.neutral_settings(120, 17.5)
        out = dsp._warp(log, fr, dict(s, tract=14.0))[0]
        peak = fr[np.argmax(out[:60])]
        self.assertAlmostEqual(peak, 500 * 17.5 / 14.0, delta=20)


class Audio(unittest.TestCase):
    def _wav(self, tag, bits, payload, fs=8000):
        fmt = struct.pack("<HHIIHH", tag, 1, fs, fs * bits // 8, bits // 8, bits)
        data = b"RIFF" + struct.pack("<I", 36 + len(payload)) + b"WAVE"
        data += b"fmt " + struct.pack("<I", 16) + fmt + b"data" + struct.pack("<I", len(payload)) + payload
        f = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        f.write(data)
        f.close()
        return f.name

    def test_float_and_24bit(self):
        p = self._wav(3, 32, np.array([0.5, -0.25], "<f4").tobytes())
        x, fs = audio.read_wav(p)
        self.assertEqual(fs, 8000)
        np.testing.assert_allclose(x, [0.5, -0.25])
        p = self._wav(1, 24, bytes([0, 0, 0x40, 0, 0, 0xC0]))
        x, _ = audio.read_wav(p)
        np.testing.assert_allclose(x, [0.5, -0.5])

    def test_roundtrip(self):
        y = np.sin(np.linspace(0, 50, 4000)) * 0.5
        p = tempfile.mktemp(suffix=".wav")
        audio.write_wav(p, y, 16000)
        x, fs = audio.read_wav(p)
        self.assertEqual((fs, len(x)), (16000, 4000))
        self.assertLess(np.abs(x - y).max(), 1e-4)


@unittest.skipUnless(os.path.exists(SAMPLE), "sample missing")
class Render(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        x, fs = audio.read_wav(SAMPLE)
        cls.a = dsp.analyse(x, fs)
        cls.n = params.neutral_settings(cls.a.mean_f0)

    def mean_f0(self, r):
        v = r.f0 > 0
        return float(np.exp(np.log(r.f0[v]).mean()))

    def test_neutral_keeps_length_and_pitch(self):
        r = dsp.render(self.a, self.n)
        self.assertAlmostEqual(len(r.y) / self.a.fs, self.a.duration, delta=0.02)
        orig = float(np.exp(np.log(self.a.f0[self.a.f0 > 0]).mean()))
        self.assertAlmostEqual(self.mean_f0(r), orig, delta=2)

    def test_every_preset(self):
        found = presets.discover()
        self.assertGreaterEqual(len(found), 14)
        for p in found:
            r = dsp.render(self.a, presets.apply(p.values, self.n))
            self.assertFalse(np.isnan(r.y).any(), p.name)
            self.assertLessEqual(np.abs(r.y).max(), 0.99, p.name)

    def test_pitch_target_and_bypass(self):
        s = dict(self.n, pitch_hz=300)
        self.assertAlmostEqual(self.mean_f0(dsp.render(self.a, s)), 300, delta=8)
        s["on_pitch"] = False
        orig = float(np.exp(np.log(self.a.f0[self.a.f0 > 0]).mean()))
        self.assertAlmostEqual(self.mean_f0(dsp.render(self.a, s)), orig, delta=2)

    def test_keep_key_whole_octaves(self):
        src = self.a.mean_f0
        self.assertAlmostEqual(dsp.key_pitch(src * 0.64, src), src / 2)      # -7.7 st -> -1 octave
        self.assertAlmostEqual(dsp.key_pitch(src * 1.27, src), src)          # +4.1 st -> no change
        self.assertAlmostEqual(dsp.key_pitch(src * 2.5, src), src * 2)
        s = dict(presets.apply(presets.find("Child").values, self.n), keep_key=1, declination=-2, fry=30,
                 rate=100, pause=100)                                    # timing as Boxapella holds it
        e = dsp.effective(s, self.a)
        self.assertEqual((e["pitch_range"], e["declination"], e["fry"]), (100.0, 0.0, 0.0))
        # every voiced frame moves by exactly the same whole number of octaves
        r = dsp.render(self.a, s)
        both = (r.f0 > 0) & (self.a.f0 > 0)
        shift = np.log2(r.f0[both] / self.a.f0[both])
        self.assertLess(np.abs(shift - np.round(shift)).max(), 1e-6)

    def test_keep_key_survives_presets_but_isnt_saved(self):
        out = params.keep_cleanup(presets.apply(presets.find("Child").values, self.n),
                                  dict(self.n, keep_key=1))
        self.assertEqual(out["keep_key"], 1)
        self.assertNotIn("keep_key", presets.from_settings("x", "x.json", out).values)

    def test_rate_and_whisper(self):
        r = dsp.render(self.a, dict(self.n, rate=50))
        self.assertAlmostEqual(len(r.y) / self.a.fs, self.a.duration * 2, delta=0.05)
        self.assertFalse((dsp.render(self.a, dict(self.n, whisper=1)).f0 > 0).any())


NOISY = os.path.join(HERE, "samples", "noisy_test.wav")


@unittest.skipUnless(os.path.exists(NOISY), "sample missing")
class CleanUp(unittest.TestCase):
    """noisy_test.wav = Front_Center.wav + room tone with a 70 Hz thud at
    +0.25 s and a noise-burst scrape at +0.6 s after the speech."""

    @classmethod
    def setUpClass(cls):
        x, cls.fs = audio.read_wav(NOISY)
        cls.a = dsp.analyse(x, cls.fs)
        cls.n = params.neutral_settings(cls.a.mean_f0)
        cls.L = 1.428

    def db(self, y, t0, t1):
        seg = y[int(t0 * self.fs):int(t1 * self.fs)]
        return 20 * np.log10(np.sqrt(np.mean(seg ** 2)) + 1e-12)

    def test_thud_and_scrape_removed_speech_kept(self):
        dry = dsp.render(self.a, self.n).y
        r = dsp.render(self.a, dict(self.n, declick=40))
        L = self.L
        self.assertLess(self.db(r.y, L + .25, L + .37), self.db(dry, L + .25, L + .37) - 30)
        self.assertLess(self.db(r.y, L + .6, L + .66), self.db(dry, L + .6, L + .66) - 30)
        self.assertAlmostEqual(self.db(r.y, 0, L), self.db(dry, 0, L), delta=1.0)
        self.assertEqual(r.events, 2)

    def test_speech_voicing_not_flagged(self):
        noise, _, _ = dsp.noise_frames(self.a, 200)
        speech = int(self.L * 1000 / dsp.FRAME_MS)
        self.assertFalse((noise[:speech] & (self.a.f0[:speech] > 0)).any())

    def test_highpass(self):
        fs = 16000
        t = np.arange(fs) / fs
        lo, hi = np.sin(2 * np.pi * 40 * t), np.sin(2 * np.pi * 1000 * t)
        self.assertLess(np.std(dsp.highpass(lo, fs, 150)), 0.1 * np.std(lo))
        self.assertGreater(np.std(dsp.highpass(hi, fs, 150)), 0.99 * np.std(hi))

    def test_presets_keep_cleanup(self):
        s = dict(self.n, declick=30, rumble=80)
        out = params.keep_cleanup(presets.apply(presets.find("Child").values, self.n), s)
        self.assertEqual((out["declick"], out["rumble"]), (30, 80))


class Join(unittest.TestCase):
    def test_gap_lengths_and_order(self):
        a, b = np.full(1000, 0.5), np.full(500, -0.5)
        y, fs = audio.join_clips([(a, 8000), (b, 8000)], gap_ms=100)
        self.assertEqual((len(y), fs), (1000 + 800 + 500, 8000))
        self.assertAlmostEqual(y[500], 0.5)
        self.assertTrue((y[1000:1800] == 0).all())
        self.assertAlmostEqual(y[-100], -0.5)
        self.assertAlmostEqual(y[-1], -0.5)
        self.assertLess(abs(y[999]), 0.01)          # seam faded, no click

    def test_crossfade_overlaps_equal_power(self):
        a, b = np.full(1000, 0.5), np.full(1000, 0.5)
        y, _ = audio.join_clips([(a, 1000), (b, 1000)], gap_ms=300, crossfade_ms=200)
        self.assertEqual(len(y), 1800)
        self.assertTrue((y[800:1000] >= 0.49).all())    # cos+sin >= 1 keeps level up

    def test_resamples_to_first_rate(self):
        y, fs = audio.join_clips([(np.zeros(16000), 16000), (np.zeros(44100), 44100)])
        self.assertEqual((fs, len(y)), (16000, 32000))

    def test_cli_join(self):
        import vocalfry
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "j.wav")
            self.assertEqual(vocalfry.main(["join", out, SAMPLE, SAMPLE, "--gap", "250"]), 0)
            x, fs = audio.read_wav(SAMPLE)
            y, fs2 = audio.read_wav(out)
            self.assertEqual((fs2, len(y)), (fs, 2 * len(x) + round(0.25 * fs)))


class Trim(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        x, fs = audio.read_wav(SAMPLE)
        cls.a = dsp.analyse(x, fs)

    def test_trim_slices_frames_and_samples(self):
        a = self.a
        t = dsp.trim(a, 40, a.frames - 30)
        self.assertEqual(t.frames, a.frames - 70)
        self.assertEqual(len(t.sp), t.frames)
        self.assertEqual(len(t.silent), t.frames)
        self.assertAlmostEqual(t.duration, t.frames * dsp.FRAME_MS / 1000, delta=0.006)
        hop = a.fs * dsp.FRAME_MS / 1000
        self.assertTrue(np.array_equal(t.x[:50], a.x[round(40 * hop):round(40 * hop) + 50]))
        self.assertEqual(t.mean_f0, a.mean_f0)
        self.assertIs(dsp.trim(a, 0, a.frames), a)

    def test_render_trimmed(self):
        t = dsp.trim(self.a, 60, 200)
        r = dsp.render(t, params.neutral_settings(self.a.mean_f0))
        self.assertAlmostEqual(len(r.y) / t.fs, t.duration, delta=0.02)


class Config(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.old = presets.CONFIG_DIR
        presets.CONFIG_DIR = os.path.join(self.d.name, "cfg")

    def tearDown(self):
        presets.CONFIG_DIR = self.old
        self.d.cleanup()

    def test_take_numbers(self):
        from app import config
        f = self.d.name
        self.assertEqual(os.path.basename(config.next_take(f, "Cocoanuts")), "Cocoanuts-1.wav")
        for n in (1, 2, 7):
            open(os.path.join(f, f"Cocoanuts-{n}.wav"), "w").close()
        open(os.path.join(f, "Cocoanuts-x.wav"), "w").close()
        self.assertEqual(os.path.basename(config.next_take(f, "Cocoanuts")), "Cocoanuts-8.wav")
        self.assertEqual(os.path.basename(config.next_take(f, "Other")), "Other-1.wav")
        self.assertEqual(config.clean_name(' a/b: "c" '), "a - b - c")

    def test_default_voice(self):
        from app import config
        self.assertIsNone(config.default_voice())
        path = os.path.join(self.d.name, "me.json")
        presets.save(presets.Preset("Me", path, False, {"pitch_hz": 99}))
        config.set_default_voice(path)
        self.assertEqual(config.default_voice().values, {"pitch_hz": 99})
        os.remove(path)
        self.assertIsNone(config.default_voice())     # missing file = no default
        config.set_default_voice(None)
        self.assertIsNone(config.get("default_voice"))


class Video(unittest.TestCase):
    def test_mp4_matches_audio(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6.QtGui import QGuiApplication
        app = QGuiApplication.instance() or QGuiApplication([])     # noqa: F841 - fonts need it
        from app import video
        import subprocess
        img = video.title_card("Why a Duck?", "A long description " * 30, "Light")
        self.assertEqual((img.width(), img.height()), video.SIZE)
        with tempfile.TemporaryDirectory() as d:
            png, wav, mp4 = (os.path.join(d, n) for n in ("c.png", "a.wav", "v.mp4"))
            img.save(png)
            audio.write_wav(wav, np.zeros(16000 * 2), 16000)
            video.make_mp4(wav, png, mp4)
            info = subprocess.run([video.ffmpeg_exe(), "-hide_banner", "-i", mp4],
                                  capture_output=True, text=True).stderr
            self.assertIn("Duration: 00:00:02.0", info)
            self.assertIn("h264", info)
            self.assertIn("aac", info)


class PresetFiles(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.TemporaryDirectory()
        self.old = presets.PRESET_DIR, presets.CONFIG_DIR, presets.KNOWN
        presets.PRESET_DIR = os.path.join(self.d.name, "presets")
        presets.CONFIG_DIR = os.path.join(self.d.name, "cfg")
        presets.KNOWN = os.path.join(presets.CONFIG_DIR, "known_presets.json")
        os.makedirs(presets.PRESET_DIR)

    def tearDown(self):
        presets.PRESET_DIR, presets.CONFIG_DIR, presets.KNOWN = self.old
        self.d.cleanup()

    def test_shipped_presets_stay_out_of_menu(self):
        presets.PRESET_DIR = self.old[0]
        self.assertTrue(presets.discover())
        shipped = [p for p in presets.discover() if os.path.dirname(p.path) == self.old[0]
                   and os.path.basename(p.path)[:2].isdigit()]        # 01-… to 14-…, not the user's own
        self.assertEqual(len(shipped), 14)
        self.assertFalse(any(p.menu for p in shipped))

    def test_menu_flag_controls_menu(self):
        path = os.path.join(presets.PRESET_DIR, "a.json")
        presets.save(presets.Preset("Robot", path, False, {"pitch_range": 0}))
        with open(os.path.join(presets.PRESET_DIR, "b.json"), "w") as f:
            f.write('{"preset": "No flag", "settings": {"tilt": 2}}')   # missing flag = off
        self.assertEqual([p.name for p in presets.discover()], ["Robot", "No flag"])
        self.assertEqual(presets.menu(), [])
        presets.set_menu(path, True)
        self.assertEqual([p.name for p in presets.menu()], ["Robot"])
        self.assertEqual(presets.load(path).values, {"pitch_range": 0})

    def test_in_folder_ignores_menu_and_outside_files(self):
        presets.save(presets.Preset("In", os.path.join(presets.PRESET_DIR, "in.json"), False, {}))
        out = os.path.join(self.d.name, "out.json")
        presets.save(presets.Preset("Out", out, True, {}))
        presets.remember(out)
        self.assertEqual([p.name for p in presets.in_folder()], ["In"])

    def test_map_flag(self):
        a = os.path.join(presets.PRESET_DIR, "a.json")
        presets.save(presets.Preset("Shown", a, False, {}))
        with open(os.path.join(presets.PRESET_DIR, "b.json"), "w") as f:
            f.write('{"preset": "Old file", "settings": {}}')      # no "map" = shown
        self.assertEqual([p.name for p in presets.on_map()], ["Shown", "Old file"])
        presets.set_flag(a, "map", False)
        self.assertEqual([p.name for p in presets.on_map()], ["Old file"])
        self.assertFalse(presets.load(a).map)

    def test_outside_file_remembered(self):
        path = os.path.join(self.d.name, "elsewhere.json")
        presets.save(presets.Preset("Far", path, True, {"tilt": 1}))
        self.assertEqual(presets.menu(), [])          # not known yet
        presets.remember(path)
        self.assertEqual([p.name for p in presets.menu()], ["Far"])

    def test_from_settings_skips_recording_facts(self):
        n = params.neutral_settings(150)
        p = presets.from_settings("Me", "x.json", dict(n, declick=40, pitch_hz=222))
        self.assertEqual(p.values["pitch_hz"], 222)
        self.assertNotIn("src_tract", p.values)
        self.assertNotIn("declick", p.values)
        self.assertEqual(presets.apply(p.values, n)["pitch_hz"], 222)


if __name__ == "__main__":
    unittest.main()
