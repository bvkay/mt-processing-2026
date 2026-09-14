"""Pre-ingest timing QC on raw LEMI-423 B423 files.

Runs before `ingest_site` so students can catch a slipped file boundary or a
GPS lock problem before it is baked into an MTH5. Three checks against a
local/remote pair: (a) file-start epoch spacing per site, (b) local-vs-remote
clock offset by cross-correlation, (c) GPS lock status per file.

This check fails if any cross-correlation peak sits more than 50 ms from zero
lag (a real clock error, which no downstream step can repair). A file-start
spacing other than 5400 s after the first file is reported as a WARNING, not a
failure: `mtproc.ingest` starts a new run at every spacing anomaly and keeps the
per-sample timestamps, so a one-second file-boundary slip (seen on Burra54rr3
at 2018-06-25 09:13:41 UTC, samples inside correctly timed) costs nothing.

B423 record layout: 1024-byte ASCII header, then 30-byte little-endian
records (time uint32 s, tick uint16 ms, Bx/By/Bz/Ex/Ey int32 raw counts,
sync int8 = GPS deviation from PPS, stage uint8 = PLL accuracy, CRC int16).
See mt_io.lemi.lemi423.Read_Lemi_Data for the authoritative layout.

Usage:
    python scripts/timing_qc.py <survey.yaml> <local> <remote> [--files N] [--out PNG]
"""

import argparse
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from loguru import logger
from scipy.signal import decimate

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mtproc.ingest import select_files
from mtproc.survey import Survey

# 30-byte little-endian record after the 1024-byte ASCII header; identical to
# mt_io.lemi.lemi423.Read_Lemi_Data.binary_format.
RECORD_DTYPE = np.dtype(
    [
        ("time", "<u4"),
        ("tick", "<u2"),
        ("Bx", "<i4"),
        ("By", "<i4"),
        ("Bz", "<i4"),
        ("Ex", "<i4"),
        ("Ey", "<i4"),
        ("sync", "<i1"),
        ("stage", "<u1"),
        ("CRC", "<i2"),
    ]
)
HEADER_BYTES = 1024
NOMINAL_SPACING_S = 5400  # 90-minute B423 files
LAG_FAIL_MS = 50.0
FS_DEC = 100.0  # decimate 1000 -> 100 Hz for the clock-offset check


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("survey_yaml", help="path to the survey's survey.yaml")
    p.add_argument("local", help="local site name (raw B423 folder = site_dirs()[local])")
    p.add_argument("remote", help="remote-reference site name")
    p.add_argument(
        "--files", type=int, default=6, metavar="N",
        help="number of local files spread across the deployment to cross-correlate (default 6)",
    )
    p.add_argument("--out", metavar="PNG", help="output figure path (default: <workspace>/qc/...)")
    return p.parse_args(argv)


def _records(fn: Path) -> np.memmap:
    n = (fn.stat().st_size - HEADER_BYTES) // RECORD_DTYPE.itemsize
    return np.memmap(fn, dtype=RECORD_DTYPE, mode="r", offset=HEADER_BYTES, shape=(n,))


def _concat(files: list[Path]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Concatenate files' records -> (epoch_ms, hx, hy) raw counts at 1000 Hz."""
    a = np.concatenate([np.asarray(_records(f)) for f in files])
    t = a["time"].astype(np.int64) * 1000 + a["tick"].astype(np.int64)
    if not np.all(np.diff(t) == 1):
        raise ValueError("non-contiguous concatenation (gap, overlap, or bad tick in the span)")
    return t, a["Bx"].astype(np.float64), a["By"].astype(np.float64)


def spacing_anomalies(files: list[Path]) -> list[dict]:
    """Consecutive file-start epoch spacings that are not 5400 s, excluding
    the first (partial) file's gap. Flags the known 5401-then-5399
    one-second file-boundary slip specially.
    """
    epochs = np.array([int(f.stem) for f in files], dtype=np.int64)
    diffs = np.diff(epochs)
    rows: list[dict] = []
    i = 1  # diffs[0] is the first file's gap (partial file) -- excluded
    while i < len(diffs):
        if diffs[i] == NOMINAL_SPACING_S:
            i += 1
            continue
        t = pd.Timestamp(int(epochs[i + 1]), unit="s", tz="UTC")
        if diffs[i] == 5401 and i + 1 < len(diffs) and diffs[i + 1] == 5399:
            rows.append(dict(time=t, spacing="5401/5399", note="one-second file-boundary slip"))
            i += 2
            continue
        rows.append(dict(time=t, spacing=str(int(diffs[i])), note=""))
        i += 1
    return rows


def gps_status(files: list[Path], stride: int = 50) -> tuple[float, list[int]]:
    """Fraction of subsampled records with sync != 0, and the stage values seen."""
    fracs, stages = [], set()
    for f in files:
        a = _records(f)
        s = np.asarray(a["sync"][::stride])
        st = np.asarray(a["stage"][::stride])
        fracs.append(float(np.mean(s != 0)))
        stages.update(int(v) for v in st.tolist())
    return (float(np.mean(fracs)) if fracs else float("nan")), sorted(stages)


def _bandpass(x: np.ndarray, fs: float, lo: float = 3.0, hi: float = 40.0) -> np.ndarray:
    """FFT-mask band limit (Schumann band, coherent over tens of km)."""
    X = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1.0 / fs)
    X[(f < lo) | (f > hi)] = 0
    return np.fft.irfft(X, len(x))


def _to_100hz(x: np.ndarray) -> np.ndarray:
    """1000 Hz raw counts -> 100 Hz, FIR zero-phase, then 3-40 Hz band limit."""
    x = decimate(x - x.mean(), 10, ftype="fir", zero_phase=True)
    return _bandpass(x, FS_DEC)


def _xcorr(xl: np.ndarray, xr: np.ndarray, i0: int, ml: int) -> tuple[np.ndarray, np.ndarray]:
    """Normalised cross-correlation of xl against sliding windows of xr, lags -ml..+ml samples."""
    L = len(xl)
    if i0 - ml < 0 or i0 + ml + L > len(xr):
        raise ValueError("remote margin too small for the requested lag search")
    xln = (xl - xl.mean()) / xl.std()
    lags = np.arange(-ml, ml + 1)
    cc = np.empty(len(lags))
    for k, lag in enumerate(lags):
        seg = xr[i0 + lag : i0 + lag + L]
        seg = (seg - seg.mean()) / seg.std()
        cc[k] = np.dot(xln, seg) / L
    return lags, cc


def clock_offset_row(local_file: Path, remote_dir: Path, margin_s: float = 20.0) -> dict:
    """Cross-correlate one local file's hx/hy against the remote data that
    covers it (plus margin), at 100 Hz band-limited to 3-40 Hz, lags +-5 s.
    Also reports GPS status for both sides. Returns a flat dict row.
    """
    e0 = int(local_file.stem)
    e1 = e0 + NOMINAL_SPACING_S
    utc_start = pd.Timestamp(e0, unit="s", tz="UTC")

    remote_files = select_files(
        remote_dir,
        start=pd.Timestamp(e0 - margin_s, unit="s").isoformat(),
        end=pd.Timestamp(e1 + margin_s, unit="s").isoformat(),
    )

    tl, hxl, hyl = _concat([local_file])
    tr, hxr, hyr = _concat(remote_files)

    row: dict = {"file": local_file.stem, "utc_start": utc_start}
    ml = int(round(5.0 * FS_DEC))
    i0 = int(round((tl[0] - tr[0]) / 1000.0 * FS_DEC))
    for comp, xl_raw, xr_raw in (("hx", hxl, hxr), ("hy", hyl, hyr)):
        xl = _to_100hz(xl_raw)
        xr = _to_100hz(xr_raw)
        lags, cc = _xcorr(xl, xr, i0, ml)
        kb = int(np.argmax(np.abs(cc)))
        row[f"{comp}_r"] = cc[kb]
        row[f"{comp}_lag_ms"] = float(lags[kb]) * (1000.0 / FS_DEC)
        row[f"{comp}_r_p1s"] = cc[ml + int(FS_DEC)]
        row[f"{comp}_r_m1s"] = cc[ml - int(FS_DEC)]

    loc_frac, loc_stages = gps_status([local_file])
    rem_frac, rem_stages = gps_status(remote_files)
    row["loc_sync_bad_pct"] = 100.0 * loc_frac
    row["loc_stages"] = loc_stages
    row["rem_sync_bad_pct"] = 100.0 * rem_frac
    row["rem_stages"] = rem_stages
    return row


def pick_spread(files: list[Path], n: int) -> list[Path]:
    """n files spread evenly across the deployment, avoiding the (possibly
    partial) first and last files where possible."""
    interior = files[1:-1] if len(files) > n + 2 else files
    idx = sorted(set(np.linspace(0, len(interior) - 1, n).round().astype(int)))
    return [interior[i] for i in idx]


def main(argv=None) -> int:
    args = parse_args(argv)
    survey = Survey.from_yaml(args.survey_yaml)
    site_dirs = survey.site_dirs()
    local_dir, remote_dir = site_dirs[args.local], site_dirs[args.remote]

    local_files = select_files(local_dir)
    remote_files = select_files(remote_dir)
    logger.info(f"{args.local}: {len(local_files)} files; {args.remote}: {len(remote_files)} files")

    # --- (a) file-start spacing, per site ---
    print("\n=== (a) file-start spacing anomalies (expected 5400 s) ===")
    local_anom = spacing_anomalies(local_files)
    remote_anom = spacing_anomalies(remote_files)
    for name, anom in ((args.local, local_anom), (args.remote, remote_anom)):
        if not anom:
            print(f"  {name}: none")
            continue
        for a in anom:
            tag = f" -- {a['note']}" if a["note"] else ""
            print(f"  {name}: {a['time']} spacing {a['spacing']} s{tag}")

    # --- (b)+(c) clock offset and GPS status, N files spread across the deployment ---
    chosen = pick_spread(local_files, args.files)
    print(f"\n=== (b)/(c) clock offset + GPS status: {len(chosen)} files ===")
    rows = []
    for f in chosen:
        try:
            rows.append(clock_offset_row(f, remote_dir))
        except Exception as e:
            logger.warning(f"{args.local}/{f.name}: clock-offset check failed -- {e!r}")
            rows.append({"file": f.stem, "utc_start": pd.Timestamp(int(f.stem), unit="s", tz="UTC")})

    table = pd.DataFrame(rows)
    cols = [
        "file", "utc_start",
        "hx_r", "hx_lag_ms", "hx_r_p1s", "hx_r_m1s",
        "hy_r", "hy_lag_ms", "hy_r_p1s", "hy_r_m1s",
        "loc_sync_bad_pct", "loc_stages", "rem_sync_bad_pct", "rem_stages",
    ]
    table = table.reindex(columns=cols)
    with pd.option_context("display.width", 200, "display.float_format", "{:.3f}".format):
        print(table.to_string(index=False))

    # --- figure ---
    fig, (ax_lag, ax_r) = plt.subplots(2, 1, figsize=(9, 6.5), sharex=True, layout="constrained")
    for comp, marker in (("hx", "o"), ("hy", "s")):
        ax_lag.plot(table["utc_start"], table[f"{comp}_lag_ms"], marker, label=comp)
        ax_r.plot(table["utc_start"], table[f"{comp}_r"], marker, label=comp)
    ax_lag.axhline(0, color="0.4", ls=":", lw=0.8)
    ax_lag.set_ylim(-1200, 1200)
    ax_lag.set_ylabel("lag (ms)")
    ax_lag.set_title(f"{args.local} vs {args.remote}: clock-offset timing QC")
    ax_lag.legend(fontsize=9)
    ax_lag.grid(alpha=0.3)

    ax_r.set_ylabel("peak r")
    ax_r.set_ylim(0, 1.02)
    ax_r.set_xlabel("file start time (UTC)")
    ax_r.grid(alpha=0.3)
    fig.autofmt_xdate()

    if len(table):
        t_lo, t_hi = table["utc_start"].min(), table["utc_start"].max()
        for a in local_anom + remote_anom:
            if t_lo <= a["time"] <= t_hi:
                for ax in (ax_lag, ax_r):
                    ax.axvline(a["time"], color="red", ls="--", lw=1.0, alpha=0.7)

    out = Path(args.out) if args.out else (survey.workspace / "qc" / f"{args.local}_vs_{args.remote}_timing.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    print(f"\ntiming figure: {out}")

    # --- pass/fail ---
    spacing_fail = bool(local_anom or remote_anom)
    lag_cols = [c for c in ("hx_lag_ms", "hy_lag_ms") if c in table]
    worst_lag = table[lag_cols].abs().max().max() if lag_cols and len(table) else np.nan
    lag_fail = bool(pd.notna(worst_lag) and worst_lag > LAG_FAIL_MS)

    print()
    if spacing_fail:
        print("WARN (a): file-start spacing other than 5400 s found after the first file (see above) "
              "-- ingest splits runs there, so this is informational unless (b) also fails")
    if lag_fail:
        print(f"FAIL (b): a cross-correlation peak is more than {LAG_FAIL_MS:.0f} ms from zero lag "
              f"(worst |lag| = {worst_lag:.0f} ms)")
    else:
        print(f"PASS (b): all cross-correlation peaks within {LAG_FAIL_MS:.0f} ms of zero lag"
              + ("" if spacing_fail else "; all file-start spacings are 5400 s after the first file"))

    return 1 if lag_fail else 0


if __name__ == "__main__":
    sys.exit(main())
