"""KISS fold variants on 12 h of Burra35 (notch first): (a) stack-subtract all channels, no excision;
(b) stack-subtract all + excise +-0.2 s; (c) stack-subtract ey only + excise +-0.2 s. Metric: coherence with the remote."""
import sys, numpy as np
from pathlib import Path
exec(open(Path(sys.argv[1]) / "kiss_fold.py").read().split("lf = files(\"Burra35\")")[0])   # reuse helpers
lf = files("Burra35"); e0 = int(lf[1].stem); e1 = e0 + 8*5400
tl, hxl, hyl = series("Burra35", (e0, e1)); exs, eys = [], []
for f in lf:
    if e0 <= int(f.stem) < e1: a = load(f); exs.append(np.asarray(a["Ex"], float)); eys.append(np.asarray(a["Ey"], float))
ex, ey = np.concatenate(exs), np.concatenate(eys); n = len(ey)
tr, hxr, hyr = series("Burra54rr3", (e0, e1)); i0 = int(tl[0]-tr[0]); hxr = hxr[i0:i0+n]; hyr = hyr[i0:i0+n]
P = 12.0
raw = {"ex": ex, "ey": ey, "hx": hxl, "hy": hyl}; notched = {c: mains_notch(v, FS) for c, v in raw.items()}
variants = {
  "a: stack all, no cut":   dict(template=("ex","ey","hx","hy"), excise=(), excise_s=0.5),
  "b: stack all, cut 0.2s": dict(template=("ex","ey","hx","hy"), excise=("ex","ey","hx","hy"), excise_s=0.2),
  "c: stack ey, cut 0.2s":  dict(template=("ey",), excise=("ex","ey","hx","hy"), excise_s=0.2),
}
q = 10; fsd = FS/q
def coh(x, y, lo_s, hi_s):
    xd = decimate(x - x.mean(), q, ftype="fir", zero_phase=True); yd = decimate(y - y.mean(), q, ftype="fir", zero_phase=True)
    fq, sxy = csd(xd, yd, fs=fsd, nperseg=8192); _, sxx = welch(xd, fs=fsd, nperseg=8192); _, syy = welch(yd, fs=fsd, nperseg=8192)
    m = (fq >= 1/hi_s) & (fq <= 1/lo_s); return (np.abs(sxy[m])**2/(sxx[m]*syy[m])).mean()
results = {}
for name, kw in variants.items():
    out, _ = kiss_remove(notched, "ey", FS, P, **kw)
    rem_out, _ = kiss_remove({"hx": hxr, "hy": hyr, "ey": ey}, "ey", FS, P, template=(), excise=tuple(c for c in kw["excise"] if c in ("hx","hy")), excise_s=kw["excise_s"])
    results[name] = (out, rem_out)
bands = ((0.05,0.3),(0.3,2.0),(2.0,10.0),(10.0,15.0))
print(f"{'pair':14s} {'band':9s} {'raw':>5s} " + " ".join(f"{k[:1]:>5s}" for k in variants))
for lc, rc in (("hx","hx"),("hy","hy"),("ex","hy"),("ey","hx")):
    for lo, hi in bands:
        vals = [coh(results[k][0][lc], results[k][1][rc], lo, hi) for k in variants]
        print(f"{lc}-remote {rc:2s} {lo:>4}-{hi:<4} {coh(raw[lc], {'hx':hxr,'hy':hyr}[rc], lo, hi):5.2f} " + " ".join(f"{v:5.2f}" for v in vals))
print("variants:", *[f"{k}" for k in variants], sep="\n  ")
