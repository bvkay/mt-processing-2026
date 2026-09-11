"""Prototype v2: CP removal by edge-locked, 10-min running median template with per-cycle fine alignment.
Fails if Ey/hx comb lines do not drop by >20 dB or local-vs-remote hx/hy coherence in 0.3-2 s does not rise."""
import numpy as np, sys, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
from pathlib import Path
from scipy.signal import welch, csd, decimate
sys.path.insert(0, str(Path(__file__).parent)); from timing_probe import files, load, series
FS = 1000.0; PERIOD = 12.0; L = int(PERIOD*FS)
lf = files("Burra57"); f = lf[len(lf)//2]; e0 = int(f.stem); e1 = e0 + 5400
tl, hxl, hyl = series("Burra57", (e0, e1)); a = load(f)
ex = np.asarray(a["Ex"], float); ey = np.asarray(a["Ey"], float); n = len(ex)
# --- edges: coarse from two-level state of smoothed Ey, then precise mid-level crossing on the raw trace
ref = ey - np.median(ey); sm = np.convolve(ref, np.ones(50)/50, mode="same")
lo, hi = np.percentile(sm, 5), np.percentile(sm, 95); mid = 0.5*(lo+hi); state = sm > mid
chg = np.flatnonzero(np.diff(state.astype(np.int8)) != 0) + 1
coarse = []
for c in chg:
    if not coarse or c - coarse[-1] > int(1.0*FS): coarse.append(c)
coarse = np.array(coarse); rising = coarse[state[np.minimum(coarse+10, n-1)]]
# precise: within +-100 ms find the first raw sample above mid (rising)
prec = []
for r in rising:
    w0, w1 = max(0, r-100), min(n, r+100); seg = ref[w0:w1]
    idx = np.flatnonzero(seg > mid)
    if len(idx): prec.append(w0 + idx[0])
prec = np.array(prec)
# periodicity filter: keep edges within 0.3 s of the running 12 s grid
good = [prec[0]]
for p_ in prec[1:]:
    k = round((p_ - good[-1]) / L)
    if k >= 1 and abs(p_ - good[-1] - k*L) < 0.3*FS: good.append(p_)
rise = np.array(good); sp = np.diff(rise)/FS
print(f"rising edges kept {len(rise)}/{len(prec)}; spacing median {np.median(sp):.4f} s, MAD {np.median(np.abs(sp-np.median(sp)))*1000:.1f} ms, min {sp.min():.3f} max {sp.max():.3f}")
# --- removal: running median template over +-25 cycles (~10 min); optional per-cycle fine alignment (+-20 ms)
def remove(x, fine=False):
    x = x - np.median(x); cyc_idx = [r for r in rise if r + L <= n]
    C = np.array([x[r:r+L] for r in cyc_idx]); y = x.copy(); K = 25
    for k, r in enumerate(cyc_idx):
        tmpl = np.median(C[max(0, k-K):k+K+1], axis=0)
        seg = y[r:r+L]
        if fine:
            best, blag = None, 0
            for lag in range(-20, 21, 2):
                t2 = np.roll(tmpl, lag); e = np.sum((seg - t2)**2)
                if best is None or e < best: best, blag = e, lag
            tmpl = np.roll(tmpl, blag)
        seg -= tmpl
    return y, np.median(C, axis=0)
res = {}
for name, x, fine in (("ex", ex, False), ("ey", ey, False), ("hx", hxl, True), ("hy", hyl, True)):
    y, t = remove(x, fine); res[name] = (x - np.median(x), y, t)
def psd(x):
    z = decimate(decimate(x, 10, ftype="fir", zero_phase=True), 10, ftype="fir", zero_phase=True)
    return welch(z, fs=10.0, nperseg=2**14)
for comp in ("ey", "hx"):
    fr, p0 = psd(res[comp][0]); _, p1 = psd(res[comp][1]); drop = []
    for k in range(1, 30):
        i = np.argmin(np.abs(fr - k/PERIOD)); drop.append(10*np.log10(p0[i]/p1[i]))
    print(f"{comp}: comb lines 1..29 median drop {np.median(drop):.1f} dB (min {np.min(drop):.1f})")
tr, hxr, hyr = series("Burra54rr3", (e0, e1)); i0 = int(tl[0]-tr[0]); hxr = hxr[i0:i0+n]; hyr = hyr[i0:i0+n]
def coh(x, y, lo_s, hi_s):
    q = 10; xd = decimate(x - x.mean(), q, ftype="fir", zero_phase=True); yd = decimate(y - y.mean(), q, ftype="fir", zero_phase=True)
    fq, sxy = csd(xd, yd, fs=FS/q, nperseg=8192); _, sxx = welch(xd, fs=FS/q, nperseg=8192); _, syy = welch(yd, fs=FS/q, nperseg=8192)
    m = (fq >= 1/hi_s) & (fq <= 1/lo_s); return (np.abs(sxy[m])**2/(sxx[m]*syy[m])).mean()
print("local-vs-remote gamma2 (per-bin mean)  raw -> cleaned")
for band in ((0.3, 2.0), (2.0, 10.0), (10.0, 15.0), (0.05, 0.3)):
    row = []
    for comp, rem in (("hx", hxr), ("hy", hyr)):
        row.append(f"{comp} {coh(res[comp][0], rem, *band):.3f} -> {coh(res[comp][1], rem, *band):.3f}")
    print(f"  {band[0]:>4}-{band[1]:<4} s: " + " | ".join(row))
fig, ax = plt.subplots(3, 2, figsize=(16, 10), layout="constrained"); t = np.arange(60*1000)/FS; s = slice(rise[10], rise[10]+60000)
for row, comp in enumerate(("ey", "hx")):
    ax[row, 0].plot(t, res[comp][0][s], lw=0.4, color="0.5", label="raw"); ax[row, 0].plot(t, res[comp][1][s], lw=0.5, color="C3", label="CP removed")
    ax[row, 0].set_title(f"Burra57 {comp}: 60 s"); ax[row, 0].legend(loc="upper right"); ax[row, 0].set_ylabel("counts (median removed)")
    ax[row, 1].plot(np.arange(L)/FS, res[comp][2], lw=0.6); ax[row, 1].set_title(f"{comp}: folded 12 s template"); ax[row, 1].set_xlabel("s from rising edge")
for col, comp in enumerate(("ey", "hx")):
    fr, p0 = psd(res[comp][0]); _, p1 = psd(res[comp][1])
    ax[2, col].loglog(fr[1:], p0[1:], color="0.5", lw=0.7, label=f"raw {comp}"); ax[2, col].loglog(fr[1:], p1[1:], color="C3", lw=0.7, label=f"cleaned {comp}"); ax[2, col].legend(); ax[2, col].set_xlabel("Hz"); ax[2, col].set_title(f"{comp} PSD (10 Hz decimated)")
out = Path(sys.argv[1]) / "cp_remove_proto2.png"; fig.savefig(out, dpi=110); print(out)
