"""Ben's order: 50 Hz + harmonics zero-phase notch first, then CP edges on the cleaner series.
Compares coherence with the remote for (a) raw, (b) CP recipe on raw, (c) notch then CP recipe.
Fails to support the order if (c) is not at least as good as (b) on the coils and better on the electrics."""
import numpy as np, sys
from pathlib import Path
from scipy.signal import welch, csd, decimate, iirnotch, sosfiltfilt, tf2sos
sys.path.insert(0, str(Path(__file__).parent)); from timing_probe import files, load, series
FS = 1000.0; PERIOD = 12.0; L = int(PERIOD*FS)
lf = files("Burra57"); f = lf[len(lf)//2]; e0 = int(f.stem); e1 = e0 + 5400
tl, hxl, hyl = series("Burra57", (e0, e1)); a = load(f); ex = np.asarray(a["Ex"], float); ey = np.asarray(a["Ey"], float); n = len(hxl)
tr, hxr, hyr = series("Burra54rr3", (e0, e1)); i0 = int(tl[0]-tr[0]); hxr = hxr[i0:i0+n]; hyr = hyr[i0:i0+n]
def mains_notch(x, f0=50.0, n_harm=9, q=30.0):
    """zero-phase comb of IIR notches at f0..n_harm*f0 below Nyquist"""
    y = x - np.median(x)
    for k in range(1, n_harm+1):
        fk = k*f0
        if fk >= FS/2: break
        b, a_ = iirnotch(fk, q, fs=FS); y = sosfiltfilt(tf2sos(b, a_), y)
    return y
def edges_from(ref):
    ref = ref - np.median(ref); sm = np.convolve(ref, np.ones(50)/50, mode="same"); mid = 0.5*(np.percentile(sm,5)+np.percentile(sm,95)); state = sm > mid
    chg = np.flatnonzero(np.diff(state.astype(np.int8)) != 0) + 1; ed = [chg[0]]
    for c in chg[1:]:
        if c - ed[-1] > int(1.0*FS): ed.append(c)
    ed = np.array(ed); rising = ed[state[np.minimum(ed+10, n-1)]]; prec = []
    for r in rising:
        w0, w1 = max(0, r-100), min(n, r+100); idx = np.flatnonzero(ref[w0:w1] > mid)
        if len(idx): prec.append(w0 + idx[0])
    good = [prec[0]]
    for p_ in prec[1:]:
        k = round((p_ - good[-1]) / L)
        if k >= 1 and abs(p_ - good[-1] - k*L) < 0.3*FS: good.append(p_)
    return ed, np.array(good)
def template_subtract(x, rise):
    x = x - np.median(x); idx = [r for r in rise if r + L <= n]; C = np.array([x[r:r+L] for r in idx]); y = x.copy()
    for k, r in enumerate(idx): y[r:r+L] -= np.median(C[max(0,k-25):k+26], axis=0)
    return y
def excise(x, ed, half_s=0.5):
    y = x.astype(float).copy(); w = int(half_s*FS)
    for e in ed:
        a0, a1 = max(0, e-w), min(n, e+w); y[a0:a1] = np.linspace(y[a0], y[a1-1], a1-a0)
    return y
q = 10; fsd = FS/q
def coh(x, y, lo_s, hi_s):
    xd = decimate(x - x.mean(), q, ftype="fir", zero_phase=True); yd = decimate(y - y.mean(), q, ftype="fir", zero_phase=True)
    fq, sxy = csd(xd, yd, fs=fsd, nperseg=8192); _, sxx = welch(xd, fs=fsd, nperseg=8192); _, syy = welch(yd, fs=fsd, nperseg=8192)
    m = (fq >= 1/hi_s) & (fq <= 1/lo_s); return (np.abs(sxy[m])**2/(sxx[m]*syy[m])).mean()
def recipe(chans, remote, tag):
    ed, rise = edges_from(chans["ey"]); sp = np.diff(rise)/FS
    out = {"ex": excise(template_subtract(chans["ex"], rise), ed), "ey": excise(template_subtract(chans["ey"], rise), ed),
           "hx": excise(chans["hx"], ed), "hy": excise(chans["hy"], ed)}
    rem = {k: excise(v, ed) for k, v in remote.items()}
    print(f"[{tag}] edges {len(ed)}, rising kept {len(rise)}, spacing MAD {np.median(np.abs(sp-np.median(sp)))*1000:.1f} ms")
    return out, rem
raw = {"ex": ex, "ey": ey, "hx": hxl, "hy": hyl}; remraw = {"hx": hxr, "hy": hyr}
notched = {k: mains_notch(v) for k, v in raw.items()}; remnotched = {k: mains_notch(v) for k, v in remraw.items()}
b_out, b_rem = recipe(raw, remraw, "CP on raw"); c_out, c_rem = recipe(notched, remnotched, "notch then CP")
print(f"{'pair':16s} {'band':10s} {'raw':>6s} {'notch':>6s} {'CP':>6s} {'notch+CP':>9s}")
for lc, rc in (("hx","hx"),("hy","hy"),("ex","hy"),("ey","hx")):
    for lo, hi in ((0.05,0.3),(0.3,2.0),(2.0,10.0)):
        print(f"{lc}-remote {rc:2s}   {lo:>4}-{hi:<5} {coh(raw[lc], remraw[rc], lo, hi):6.2f} {coh(notched[lc], remnotched[rc], lo, hi):6.2f} {coh(b_out[lc], b_rem[rc], lo, hi):6.2f} {coh(c_out[lc], c_rem[rc], lo, hi):9.2f}")
