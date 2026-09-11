"""Combined CP recipe on one Burra57 file: E = 10-min running-median square-wave template subtracted,
then all channels: +-0.5 s around every switching edge replaced by linear interpolation.
Fails if local-vs-remote coherence in 0.3-2 s does not rise from ~0.3 toward the CP-free control (~0.8)."""
import numpy as np, sys
from pathlib import Path
from scipy.signal import welch, csd, decimate
sys.path.insert(0, str(Path(__file__).parent)); from timing_probe import files, load, series
FS = 1000.0; PERIOD = 12.0; L = int(PERIOD*FS)
lf = files("Burra57"); f = lf[len(lf)//2]; e0 = int(f.stem); e1 = e0 + 5400
tl, hxl, hyl = series("Burra57", (e0, e1)); a = load(f); ex = np.asarray(a["Ex"], float); ey = np.asarray(a["Ey"], float); n = len(hxl)
tr, hxr, hyr = series("Burra54rr3", (e0, e1)); i0 = int(tl[0]-tr[0]); hxr = hxr[i0:i0+n]; hyr = hyr[i0:i0+n]
ref = ey - np.median(ey); sm = np.convolve(ref, np.ones(50)/50, mode="same"); mid = 0.5*(np.percentile(sm,5)+np.percentile(sm,95)); state = sm > mid
chg = np.flatnonzero(np.diff(state.astype(np.int8)) != 0) + 1; edges = [chg[0]]
for c in chg[1:]:
    if c - edges[-1] > int(1.0*FS): edges.append(c)
edges = np.array(edges); rising = edges[state[np.minimum(edges+10, n-1)]]
prec = []
for r in rising:
    w0, w1 = max(0, r-100), min(n, r+100); idx = np.flatnonzero(ref[w0:w1] > mid)
    if len(idx): prec.append(w0 + idx[0])
good = [prec[0]]
for p_ in prec[1:]:
    k = round((p_ - good[-1]) / L)
    if k >= 1 and abs(p_ - good[-1] - k*L) < 0.3*FS: good.append(p_)
rise = np.array(good)
def template_subtract(x):
    x = x - np.median(x); idx = [r for r in rise if r + L <= n]; C = np.array([x[r:r+L] for r in idx]); y = x.copy()
    for k, r in enumerate(idx): y[r:r+L] -= np.median(C[max(0,k-25):k+26], axis=0)
    return y
def excise(x, half_s=0.5):
    y = x.astype(float).copy(); w = int(half_s*FS)
    for e in edges:
        a0, a1 = max(0, e-w), min(n, e+w); y[a0:a1] = np.linspace(y[a0], y[a1-1], a1-a0)
    return y
clean = {"ex": excise(template_subtract(ex)), "ey": excise(template_subtract(ey)), "hx": excise(hxl), "hy": excise(hyl)}
rem = {"hx": excise(hxr), "hy": excise(hyr)}   # remote excised identically so the gaps line up
raw = {"ex": ex, "ey": ey, "hx": hxl, "hy": hyl}; remraw = {"hx": hxr, "hy": hyr}
q = 10; fsd = FS/q
def coh(x, y, lo_s, hi_s):
    xd = decimate(x - x.mean(), q, ftype="fir", zero_phase=True); yd = decimate(y - y.mean(), q, ftype="fir", zero_phase=True)
    fq, sxy = csd(xd, yd, fs=fsd, nperseg=8192); _, sxx = welch(xd, fs=fsd, nperseg=8192); _, syy = welch(yd, fs=fsd, nperseg=8192)
    m = (fq >= 1/hi_s) & (fq <= 1/lo_s); return (np.abs(sxy[m])**2/(sxx[m]*syy[m])).mean()
print(f"edges {len(edges)}, excised {2*0.5*len(edges)/(n/FS)*100:.1f} % of the record")
print(f"{'pair':16s} {'band':10s} {'raw':>6s} {'recipe':>7s}")
for lc, rc in (("hx","hx"),("hy","hy"),("ex","hy"),("ey","hx")):
    for lo, hi in ((0.05,0.3),(0.3,2.0),(2.0,10.0),(10.0,15.0)):
        print(f"{lc}-remote {rc:2s}   {lo:>4}-{hi:<5} {coh(raw[lc], remraw[rc], lo, hi):6.2f} {coh(clean[lc], rem[rc], lo, hi):7.2f}")
