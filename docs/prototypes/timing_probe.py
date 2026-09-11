"""Diagnose the field-sheet 'Behind' timing flag from the raw data.
This test fails to be informative if the hx-hx cross-correlation between a
local site and the remote has no clear peak; it detects a clock error if the
peak sits away from zero lag by more than a few samples at 10 Hz."""
import numpy as np, pandas as pd
from pathlib import Path
from collections import Counter
from scipy.signal import decimate
ROOT = Path(r"E:/MT_Timeseries_DATA/MT_Burra_2017-2020")
dt = np.dtype([("time","<u4"),("tick","<u2"),("Bx","<i4"),("By","<i4"),("Bz","<i4"),("Ex","<i4"),("Ey","<i4"),("sync","<i1"),("stage","<u1"),("CRC","<i2")])
def files(site): return sorted((ROOT/site).glob("*.B423"), key=lambda p:int(p.stem))
def load(fn):
    n=(fn.stat().st_size-1024)//30
    return np.memmap(fn, dtype=dt, mode="r", offset=1024, shape=(n,))
def gps_probe(site, idx):
    fn = files(site)[idx]; a = load(fn)
    t = a["time"].astype(np.int64)*1000 + a["tick"].astype(np.int64); d=np.diff(t)
    print(f"{site}/{fn.name}: n={len(a)} first={pd.to_datetime(int(t[0]),unit='ms',utc=True)} dt==1ms {np.mean(d==1)*100:.3f}% "
          f"sync={dict(Counter(a['sync'][::101].tolist()))} stage={dict(Counter(a['stage'][::101].tolist()))}")
def series(site, epochs_needed):
    """concatenate the site's files covering the requested epoch span -> (t_ms array start, hx, hy) at 1000 Hz"""
    fs = [f for f in files(site) if int(f.stem)+5400 > epochs_needed[0] and int(f.stem) < epochs_needed[1]]
    parts=[load(f) for f in fs]
    a=np.concatenate([np.asarray(p) for p in parts])
    t=a["time"].astype(np.int64)*1000+a["tick"].astype(np.int64)
    assert np.all(np.diff(t)==1), f"{site}: non-contiguous concatenation"
    return t, a["Bx"].astype(np.float64), a["By"].astype(np.float64)
def xcorr_lag(local, remote, comp, max_lag_s=1500, q=100):
    lf = files(local); mid = lf[len(lf)//2]; e0=int(mid.stem); e1=e0+5400
    tl, hxl, hyl = series(local, (e0,e1))
    tr, hxr, hyr = series(remote, (e0-max_lag_s-60, e1+max_lag_s+60))
    xl = hxl if comp=="hx" else hyl; xr = hxr if comp=="hx" else hyr
    # decimate 1000 -> 10 Hz in two FIR stages
    def dec(x): 
        for qq in (10, q//10): x = decimate(x, qq, ftype="fir", zero_phase=True)
        return x
    xl=dec(xl-xl.mean()); xr=dec(xr-xr.mean()); fs=1000/q
    # align nominal grids: remote index of local start
    i0 = int(round((tl[0]-tr[0])/1000*fs))
    L=len(xl); ml=int(max_lag_s*fs)
    lags=np.arange(-ml, ml+1); cc=np.empty(len(lags))
    xl=(xl-xl.mean())/xl.std()
    for k,lag in enumerate(lags):
        seg = xr[i0+lag:i0+lag+L]
        seg=(seg-seg.mean())/seg.std()
        cc[k]=np.dot(xl,seg)/L
    kbest=np.argmax(np.abs(cc)); lag_s=lags[kbest]/fs
    print(f"{local} vs {remote} {comp}: file {mid.name} ({pd.to_datetime(e0,unit='s',utc=True)}), "
          f"peak |r|={abs(cc[kbest]):.3f} at lag {lag_s:+.1f} s (r at zero lag {cc[ml]:+.3f}); "
          f"2nd-best |r| away from peak: {np.max(np.abs(np.delete(cc, slice(max(0,kbest-50),kbest+50)))):.3f}")
    return lags/fs, cc

if __name__ == "__main__":
    for site, idx in [("Burra57", 8), ("Burra54rr3", 40), ("Burra25", 15)]:
        gps_probe(site, idx)
    print("--- cross-correlation vs remote (10 Hz, lags to +-1500 s) ---")
    for local in ("Burra35", "Burra25", "Burra57"):
        for comp in ("hx", "hy"):
            try: xcorr_lag(local, "Burra54rr3", comp)
            except Exception as e: print(f"{local} {comp}: FAILED {e!r}")
