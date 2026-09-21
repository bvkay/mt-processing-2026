"""Unit test for `mtproc.timefreq.narrow_lines` and `scripts/line_scan.py`'s archive scan.

    python tests/line_scan_unit.py

A synthetic 1000 Hz, 20-minute record: pink-ish noise plus a stable 50 Hz
line (+40 dB, calibrated -- see CALIBRATION below), stable 37.4 and 62.55 Hz
lines (+10 dB each), and a line that wanders linearly 44.0 -> 46.0 Hz over
the whole record.

**This test fails if** `narrow_lines` misses 37.4 or 62.55 Hz (within 0.1 Hz);
reports the wandering line as a single narrow line above 6 dB (checked as:
the number of reported lines in the 43.5-46.5 Hz band is exactly 1 -- 0 or
>=2 both pass, since either means the wander was not conflated into one
narrow tone; this test also fails if it comes back *empty*, which would just
mean the calibration is too weak to test anything at all); does not flag
50 Hz as a mains harmonic; or reports any line where none was added (checked
on a quiet noise-only stretch, see NO-FALSE-POSITIVE STRETCH LENGTH below).
It also fails if the archive-scan round trip (`scripts/line_scan.py`'s
`scan_archive` on a tiny fake MTH5 built with mth5's own API) does not
recover the injected 50 Hz line with the right site/run/channel/mains-flag
labels, byte-for-byte through a CSV round trip.

CALIBRATION. "+40 dB" / "+10 dB" are targets for what `narrow_lines` itself
measures, not for the sinusoid's amplitude relative to the noise's
time-domain variance (those are different units: `narrow_lines` measures a
spectral-density excess in dB, the noise's total variance is spread very
unevenly across a 0.05 Hz-resolution 5-500 Hz band). AMP_* below were
derived once with a one-off calibration script (inject a unit-amplitude
tone, read back the measured excess dB from `narrow_lines` with
`min_db=-1e9` so nothing is filtered, then scale by the exact
`20*log10(amp)` the excess must move by) against this file's exact NOISE_SEED
pink-noise draw, then hardcoded here so the test itself makes no extra
`narrow_lines` calls and stays fast and deterministic.

NO-FALSE-POSITIVE STRETCH LENGTH. The task this test was written against
asked for "a 20-s band of pure noise: no line above 6 dB". At the default
resolution (`nperseg = round(fs / 0.05) = 20000` samples = 20 s at 1000 Hz),
a literal 20 s array is exactly **one** Welch segment -- a plain periodogram,
not an average of several -- so every bin is a 2-degree-of-freedom
chi-squared draw with no variance reduction at all. Measured directly: 30
independent 20 s pink-noise draws gave a spurious line on site
****30/30**** of them, ~300 spurious lines each. That is not a bug in
`narrow_lines` (its floor and threshold logic is doing exactly what it is
told); it is a property of calling it on too short a stretch, i.e. this is a
real, useful limit on how it must be used, not a reason to weaken the check
-- `scripts/line_scan.py`'s real per-hour calls have ~360x this many samples
per call (3600 s of data => ~359 segments) and see nothing like this rate.
Measuring the duration actually needed: 0/20 false positives at 120 s
(11 segments) and longer, still ~1/20 at 90 s (8 segments), 14/20 at 60 s (5
segments). So the no-false-positive check below uses a 120 s quiet stretch
-- long enough for the check to be meaningful, short enough to stay fast --
and this paragraph is the record of why 20 s literally could not be used.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from mtproc.timefreq import narrow_lines  # noqa: E402

FS = 1000.0
RECORD_MINUTES = 20.0
NOISE_SEED = 7
QUIET_SEED = 101
QUIET_SECONDS = 120.0  # see NO-FALSE-POSITIVE STRETCH LENGTH above
MIN_DB = 6.0

# calibrated so narrow_lines(..., min_db=-1e9) measures ~40 / ~10 / ~10 dB
# excess for these three lines against this file's NOISE_SEED draw -- see
# CALIBRATION above
AMP_50 = 1.496302
AMP_37_4 = 0.054976
AMP_62_55 = 0.042265
# calibrated the same way against a stationary 45 Hz tone (~24 dB target);
# actually wandering, its measured excess at any one bin comes out lower
# (smeared) -- that smearing is exactly what this test checks for
AMP_WANDER = 0.252532


def pink_noise(n: int, seed: int, exponent: float = 1.0) -> np.ndarray:
    """Unit-std ~1/f noise: white noise shaped by 1/f**(exponent/2) in the FFT domain."""
    rng = np.random.default_rng(seed)
    white = rng.standard_normal(n)
    spec = np.fft.rfft(white)
    freqs = np.fft.rfftfreq(n, 1.0 / FS)
    scale = np.ones_like(freqs)
    scale[1:] = 1.0 / (freqs[1:] ** (exponent / 2.0))
    spec *= scale
    out = np.fft.irfft(spec, n)
    return out / out.std()


def make_signal(minutes: float, seed: int) -> np.ndarray:
    n = int(minutes * 60 * FS)
    t = np.arange(n) / FS
    x = pink_noise(n, seed)
    x += AMP_50 * np.sin(2 * np.pi * 50.0 * t)
    x += AMP_37_4 * np.sin(2 * np.pi * 37.4 * t)
    x += AMP_62_55 * np.sin(2 * np.pi * 62.55 * t)
    f_wander = 44.0 + (46.0 - 44.0) * (t / t[-1])
    phase = 2 * np.pi * np.cumsum(f_wander) / FS
    x += AMP_WANDER * np.sin(phase)
    return x


SIGNAL = make_signal(RECORD_MINUTES, NOISE_SEED)


def _near(lines: list[tuple[float, float, bool]], f0: float, tol: float = 0.1):
    hits = [line for line in lines if abs(line[0] - f0) <= tol]
    return hits[0] if hits else None


def test_detects_stable_lines_and_flags_mains() -> None:
    lines = narrow_lines(SIGNAL, FS, 5.0, 500.0, min_db=MIN_DB)

    hit_50 = _near(lines, 50.0)
    assert hit_50 is not None, "50 Hz line missed"
    assert hit_50[2] is True, f"50 Hz not flagged as a mains harmonic: {hit_50}"

    hit_374 = _near(lines, 37.4)
    assert hit_374 is not None, "37.4 Hz line missed (within 0.1 Hz)"
    assert hit_374[2] is False, f"37.4 Hz wrongly flagged as a mains harmonic: {hit_374}"

    hit_6255 = _near(lines, 62.55)
    assert hit_6255 is not None, "62.55 Hz line missed (within 0.1 Hz)"
    assert hit_6255[2] is False, f"62.55 Hz wrongly flagged as a mains harmonic: {hit_6255}"

    print(
        f"  50 Hz {hit_50[1]:+.1f} dB (mains), 37.4 Hz {hit_374[1]:+.1f} dB, "
        f"62.55 Hz {hit_6255[1]:+.1f} dB -- all within 0.1 Hz, mains flag correct"
    )


def test_wandering_line_not_reported_as_a_single_line() -> None:
    lines = narrow_lines(SIGNAL, FS, 5.0, 500.0, min_db=MIN_DB)
    wander_hits = [line for line in lines if 43.5 <= line[0] <= 46.5]
    assert wander_hits, "wandering 44-46 Hz line not detected at all -- calibration too weak to test"
    assert len(wander_hits) != 1, (
        f"wandering line reported as a single narrow line: {wander_hits} -- "
        f"a 44->46 Hz sweep should be smeared into several weaker lines or none, not one"
    )
    print(f"  wandering line -> {len(wander_hits)} reported line(s) (not 1): {wander_hits}")


def test_no_false_positive_on_quiet_noise() -> None:
    """See NO-FALSE-POSITIVE STRETCH LENGTH in the module docstring for why 120 s, not 20 s."""
    quiet = pink_noise(int(QUIET_SECONDS * FS), QUIET_SEED)
    lines = narrow_lines(quiet, FS, 5.0, 500.0, min_db=MIN_DB)
    assert lines == [], f"line(s) reported in a {QUIET_SECONDS:g} s pure-noise stretch: {lines}"
    print(f"  {QUIET_SECONDS:g} s pure noise, no injected line -> 0 lines reported")


def test_narrow_lines_falsifies_with_min_db_30() -> None:
    """A sanity check that the min_db=6 checks above are not vacuous.

    At min_db=30, the 37.4 Hz line (~+10 dB by calibration) must NOT survive
    -- if it did, `min_db` would not be doing anything and the earlier
    tests could not actually fail. This is the same falsification the task
    asked to be demonstrated by hand (raise min_db to 30, show the 37.4 Hz
    check fails, then restore); it is kept here, permanently, as a passing
    test in its own right -- it fails if 37.4 Hz survives raising min_db to 30.
    """
    lines = narrow_lines(SIGNAL, FS, 5.0, 500.0, min_db=30.0)
    hit_374 = _near(lines, 37.4)
    assert hit_374 is None, f"37.4 Hz survived min_db=30 -- min_db is not filtering: {hit_374}"
    hit_50 = _near(lines, 50.0)
    assert hit_50 is not None, "50 Hz (+40 dB) should still survive min_db=30"
    print(f"  min_db=30: 37.4 Hz correctly dropped, 50 Hz survives ({hit_50[1]:+.1f} dB)")


# ---------------------------------------------------------------- CSV round trip on a tiny fake MTH5


def test_scan_archive_csv_round_trip() -> None:
    """`scripts/line_scan.py`'s `scan_archive` on a two-channel, one-run fake MTH5.

    Built with mth5's own ChannelTS/RunTS API (the same pattern
    `tests/virtual_unit.py` uses), 12 minutes at 1000 Hz -- long enough to
    clear the 10-minute trailing-block floor as the record's only (partial)
    hour block, short enough to build and scan in well under a second.
    hx carries a +40ish dB 50 Hz line; hy carries none. Fails if the written
    CSV does not round-trip site/run/channel/hour/frequency/mains-flag for
    that line back out, on the right channel only.
    """
    try:
        from mth5.mth5 import MTH5
        from mth5.timeseries import ChannelTS, RunTS
    except Exception as exc:  # pragma: no cover -- mth5 not importable
        print(f"  SKIP: mth5 API not available ({exc!r})")
        return

    from line_scan import scan_archive  # noqa: E402  (scripts/ on sys.path above)

    survey_name = "SYNTH_LINE_SCAN"
    site = "X01"
    minutes = 12.0
    n = int(minutes * 60 * FS)
    t = np.arange(n) / FS
    rng = np.random.default_rng(5)
    hx = 1000.0 * rng.standard_normal(n) + 45000.0 * np.sin(2 * np.pi * 50.0 * t)
    hy = 1000.0 * rng.standard_normal(n)
    start = pd.Timestamp("2023-09-19T00:00:00")

    with tempfile.TemporaryDirectory() as tmp:
        h5_path = Path(tmp) / f"{site}.h5"
        m = MTH5(file_version="0.2.0")
        m.open_mth5(h5_path, mode="w")
        try:
            m.add_survey(survey_name)
            station = m.add_station(site, survey=survey_name)
            chans = [
                ChannelTS(channel_type="magnetic", data=np.asarray(data), channel_metadata={
                    "magnetic": {"component": c, "sample_rate": FS, "time_period.start": start.isoformat()}
                })
                for c, data in (("hx", hx), ("hy", hy))
            ]
            run = RunTS(chans, run_metadata={"id": "sr1000_0001", "sample_rate": FS},
                        station_metadata={"id": site})
            station.add_run("sr1000_0001").from_runts(run)
        finally:
            m.close_mth5()

        rows, hours_scanned, channels_present = scan_archive(
            h5_path, survey_name, site, ["hx", "hy", "ex", "ey"], hours_step=1.0,
            fmin=5.0, fmax=500.0, min_db=MIN_DB,
        )
        assert hours_scanned == 1, f"expected 1 (trailing-partial) hour block, got {hours_scanned}"
        assert channels_present == ["hx", "hy"], channels_present

        csv_path = Path(tmp) / f"lines_{site}.csv"
        df = pd.DataFrame(rows, columns=["site", "run", "channel", "hour_start_utc", "f_hz", "excess_db", "mains_harmonic"])
        df.to_csv(csv_path, index=False)
        back = pd.read_csv(csv_path)

        hx_rows = back[back["channel"] == "hx"]
        assert len(hx_rows) == 1, f"expected exactly 1 line on hx, got {len(hx_rows)}: {hx_rows}"
        row = hx_rows.iloc[0]
        assert row["site"] == site
        assert row["run"] == "sr1000_0001"
        assert abs(float(row["f_hz"]) - 50.0) <= 0.1, row["f_hz"]
        assert float(row["excess_db"]) >= MIN_DB
        assert bool(row["mains_harmonic"]) is True
        # mth5 stores time_period.start UTC-localized ("+00:00"); start here is naive
        assert pd.Timestamp(row["hour_start_utc"]) == start.tz_localize("UTC"), row["hour_start_utc"]

        hy_rows = back[back["channel"] == "hy"]
        assert len(hy_rows) == 0, f"expected no line on the quiet hy channel, got {hy_rows}"

        print(f"  CSV round trip: hx 50 Hz line recovered ({row['excess_db']:+.1f} dB, mains=True), hy empty")


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    print(__doc__.split("**This test fails if**")[1].split("CALIBRATION.")[0].strip())
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  line_scan_unit ({len(tests)} tests)")
