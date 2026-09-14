"""Welch PSD of a site's raw B423 data — quick look for mains lines etc.

Usage:
    python scripts/noise_psd.py <survey.yaml> <site> [out.png]

Uses one mid-deployment file (90 min) in raw counts; fine for locating
spectral lines even though uncalibrated.
"""

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import welch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mtproc.ingest import read_lemi423, select_files
from mtproc.survey import Survey


def main(survey_yaml: str, site: str, out_png: str | None = None) -> None:
    survey = Survey.from_yaml(survey_yaml)
    files = select_files(survey.site_dirs()[site])
    fn = files[len(files) // 2]  # mid-deployment
    run = read_lemi423(fn, station_id=site)
    fs = float(run.sample_rate)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    for comp, colour in [("ex", "C0"), ("ey", "C1"), ("hx", "C2"), ("hy", "C3")]:
        data = np.asarray(run.dataset[comp].data, dtype=float)
        data -= data.mean()
        f, pxx = welch(data, fs=fs, nperseg=2**16)
        axes[0].loglog(f[1:], pxx[1:], colour, lw=0.8, label=comp)
        zoom = (f >= 30) & (f <= 170)
        axes[1].semilogy(f[zoom], pxx[zoom], colour, lw=0.8, label=comp)

    for f0 in (50, 100, 150):
        axes[1].axvline(f0, color="0.4", ls=":", lw=0.8)
    axes[0].set_xlabel("frequency (Hz)")
    axes[0].set_ylabel(r"PSD (counts$^2$/Hz)")
    axes[0].set_title(f"{site} raw PSD ({fn.name}, {fs:.0f} Hz)")
    axes[1].set_xlabel("frequency (Hz)")
    axes[1].set_title("30–170 Hz zoom (dotted: 50/100/150 Hz)")
    axes[0].legend(fontsize=9)
    axes[0].grid(alpha=0.3)
    axes[1].grid(alpha=0.3)

    out = Path(out_png) if out_png else survey.workspace / "qc" / f"{site}_noise_psd.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")


if __name__ == "__main__":
    main(*sys.argv[1:])
