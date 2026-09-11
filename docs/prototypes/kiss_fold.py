"""KISS cathodic-protection removal: one period from the autocorrelation, fixed-grid stacking per
10-min window, median stack subtracted, +-0.5 s excised around the stacked cycle's own two edges.
Fails if it does not reach the detector method's coil coherence (~0.5-0.6 in 0.3-2 s at Burra35)."""
import sys, time, numpy as np
from pathlib import Path
from scipy.signal import welch, csd, decimate, butter, sosfiltfilt
sys.path.insert(0, "src"); sys.path.insert(0, str(Path(sys.argv[1])))
from bbmt.noise import mains_notch
from timing_probe import files, load, series
FS = 1000.0
def period_from_autocorr(ref, fs, nominal=12.0, cycles=50):
    """Period to ~0.1 ms: lag of the autocorrelation peak near `cycles` x nominal, divided by `cycles`."""
    r = np.asarray(ref, float); r = r - np.median(r)
    r = sosfiltfilt(butter(2, [1/200.0, 5.0], btype="band", fs=fs, output="sos"), r)
    q = 10; d = decimate(r, q, ftype="fir", zero_phase=True); fsd = fs/q            # 100 Hz: 10 ms resolution / 50 cycles = 0.2 ms
    d = d[: int(min(len(d), 3*3600*fsd))]
    lag0 = int(round(cycles*nominal*fsd)); span = int(round(0.5*fsd*cycles*0.01))     # search +-5 ms per cycle
    lags = np.arange(lag0-span, lag0+span+1); ac = np.array([np.dot(d[:-l], d[l:]) for l in lags])
    k = np.argmax(ac); lag = lags[k]
    if 0 < k < len(ac)-1:   # parabolic refinement
        y0, y1, y2 = ac[k-1], ac[k], ac[k+1]; lag = lags[k] + 0.5*(y0-y2)/(y0-2*y1+y2)
    return float(lag/fsd/cycles)
def circ_smooth(x, w=50):
    pad = np.concatenate([x[-w:], x, x[:w]]); return np.convolve(pad, np.ones(w)/w, mode="same")[w:-w]
def kiss_remove(chans, ref, fs, P, window_min=10, excise_s=0.5, template=("ey",), excise=("ex","ey","hx","hy")):
    out = {c: np.asarray(x, float).copy() for c, x in chans.items()}; n = len(out[ref]); L = int(round(P*fs)); win = int(window_min*60*fs); wexc = int(excise_s*fs)
    edges_seen = []
    for w0 in range(0, n, win):
        w1 = min(n, w0+win); ncyc = int((w1-w0)//(P*fs))
        if ncyc < 5: continue
        starts = w0 + np.round(np.arange(ncyc)*P*fs).astype(int); starts = starts[starts+L <= n]
        stack = np.median(np.stack([out[ref][s:s+L] for s in starts]), axis=0)
        sm = circ_smooth(stack); dd = np.abs(np.diff(np.concatenate([sm, sm[:1]])))
        e1 = int(np.argmax(dd)); dd2 = dd.copy(); lo, hi = max(0, e1-int(fs)), min(L, e1+int(fs)); dd2[lo:hi] = 0
        if e1 < int(fs): dd2[L-int(fs)+e1:] = 0
        e2 = int(np.argmax(dd2)); edges = sorted([e1, e2]); edges_seen.append(edges)
        for c in out:
            if c in template:
                t = np.median(np.stack([out[c][s:s+L] for s in starts]), axis=0); t -= np.median(t)
                for s in starts: out[c][s:s+L] -= t
            if c in excise:
                x = out[c]
                for s in starts:
                    for e in edges:
                        a0, a1 = max(0, s+e-wexc), min(n, s+e+wexc); x[a0:a1] = np.linspace(x[a0], x[a1-1], a1-a0)
    return out, np.array(edges_seen)
lf = files("Burra35"); e0 = int(lf[1].stem); e1 = e0 + 8*5400
tl, hxl, hyl = series("Burra35", (e0, e1)); exs, eys = [], []
for f in lf:
    if e0 <= int(f.stem) < e1: a = load(f); exs.append(np.asarray(a["Ex"], float)); eys.append(np.asarray(a["Ey"], float))
ex, ey = np.concatenate(exs), np.concatenate(eys); n = len(ey)
tr, hxr, hyr = series("Burra54rr3", (e0, e1)); i0 = int(tl[0]-tr[0]); hxr = hxr[i0:i0+n]; hyr = hyr[i0:i0+n]
t0 = time.time(); P = period_from_autocorr(ey, FS); print(f"period from autocorrelation: {P:.5f} s ({time.time()-t0:.0f} s)")
raw = {"ex": ex, "ey": ey, "hx": hxl, "hy": hyl}; notched = {c: mains_notch(v, FS) for c, v in raw.items()}
t0 = time.time(); out, edges = kiss_remove(notched, "ey", FS, P); print(f"kiss fold on 12 h: {time.time()-t0:.0f} s; template edges per window (s): median {np.median(edges, axis=0)/FS}, spread {np.ptp(edges, axis=0)/FS}")
rem_out, _ = kiss_remove({"hx": hxr, "hy": hyr, "ey": ey}, "ey", FS, P, template=(), excise=("hx","hy"))
q = 10; fsd = FS/q
def coh(x, y, lo_s, hi_s):
    xd = decimate(x - x.mean(), q, ftype="fir", zero_phase=True); yd = decimate(y - y.mean(), q, ftype="fir", zero_phase=True)
    fq, sxy = csd(xd, yd, fs=fsd, nperseg=8192); _, sxx = welch(xd, fs=fsd, nperseg=8192); _, syy = welch(yd, fs=fsd, nperseg=8192)
    m = (fq >= 1/hi_s) & (fq <= 1/lo_s); return (np.abs(sxy[m])**2/(sxx[m]*syy[m])).mean()
print(f"{'pair':16s} {'band':10s} {'raw':>6s} {'kiss':>6s}")
for lc, rc in (("hx","hx"),("hy","hy"),("ex","hy"),("ey","hx")):
    for lo, hi in ((0.05,0.3),(0.3,2.0),(2.0,10.0),(10.0,15.0)):
        print(f"{lc}-remote {rc:2s}   {lo:>4}-{hi:<5} {coh(raw[lc], {'hx':hxr,'hy':hyr}[rc], lo, hi):6.2f} {coh(out[lc], rem_out[rc], lo, hi):6.2f}")
