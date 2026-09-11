"""Is Burra57's coil contamination confined to the 12 s comb lines, or broadband?
Fails to inform if between-line coherence equals on-line coherence within noise."""
import numpy as np, sys
from pathlib import Path
from scipy.signal import welch, csd, decimate
sys.path.insert(0, str(Path(__file__).parent)); from timing_probe import files, load, series
exec(open(Path(__file__).parent / "cp_remove_proto2.py").read().split("# --- removal")[0].split("tl, hxl, hyl = series")[0])  # FS, PERIOD, L, file choice
lf = files("Burra57"); f = lf[len(lf)//2]; e0 = int(f.stem); e1 = e0 + 5400
tl, hxl, hyl = series("Burra57", (e0, e1)); a = load(f); ey = np.asarray(a["Ey"], float); n = len(hxl)
tr, hxr, hyr = series("Burra54rr3", (e0, e1)); i0 = int(tl[0]-tr[0]); hxr = hxr[i0:i0+n]; hyr = hyr[i0:i0+n]
# edges as in proto2
ref = ey - np.median(ey); sm = np.convolve(ref, np.ones(50)/50, mode="same"); mid = 0.5*(np.percentile(sm,5)+np.percentile(sm,95)); state = sm > mid
chg = np.flatnonzero(np.diff(state.astype(np.int8)) != 0) + 1; edges = [chg[0]]
for c in chg[1:]:
    if c - edges[-1] > int(1.0*FS): edges.append(c)
edges = np.array(edges)
q = 10; fsd = FS/q; nps = 8192
def spectra(x, y):
    xd = decimate(x - x.mean(), q, ftype="fir", zero_phase=True); yd = decimate(y - y.mean(), q, ftype="fir", zero_phase=True)
    fq, sxy = csd(xd, yd, fs=fsd, nperseg=nps); _, sxx = welch(xd, fs=fsd, nperseg=nps); _, syy = welch(yd, fs=fsd, nperseg=nps)
    return fq, np.abs(sxy)**2/(sxx*syy)
def report(label, x, y):
    fq, g = spectra(x, y); k = np.round(fq*PERIOD); online = np.abs(fq - k/PERIOD) < 0.012
    for lo, hi in ((0.3,2.0),(2.0,10.0)):
        m = (fq >= 1/hi) & (fq <= 1/lo)
        print(f"  {label:34s} {lo}-{hi} s: on-line bins {g[m & online].mean():.2f} ({(m&online).sum()} bins) | between-line bins {g[m & ~online].mean():.2f} ({(m&~online).sum()} bins)")
print("Burra57 hx vs remote hx, per-bin squared coherence:")
report("raw", hxl, hxr)
# excise +-1.5 s around every edge (both channels identically), linear interpolation across the gap
def excise(x, half_s=1.5):
    y = x.astype(float).copy(); w = int(half_s*FS)
    for e in edges:
        a0, a1 = max(0, e-w), min(n, e+w); y[a0:a1] = np.linspace(y[a0], y[a1-1], a1-a0)
    return y
hx_ex = excise(hxl); hxr_ex = excise(hxr)
report("edges excised +-1.5 s (interp)", hx_ex, hxr_ex)
hx_ex2 = excise(hxl, 0.5); hxr_ex2 = excise(hxr, 0.5)
report("edges excised +-0.5 s (interp)", hx_ex2, hxr_ex2)
print("control: Burra25 hy vs remote hy (no CP, 60 km):")
lf2 = files("Burra25"); f2 = lf2[8]; e0b = int(f2.stem); tl2, hx2, hy2 = series("Burra25", (e0b, e0b+5400)); tr2, hxr2, hyr2 = series("Burra54rr3", (e0b, e0b+5400)); j0 = int(tl2[0]-tr2[0]); m2 = len(hy2)
report("Burra25 hy raw", hy2, hyr2[j0:j0+m2])
