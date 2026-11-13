# Install and the forked libraries

This page covers the conda environment, the five forked libraries
mt-workbench runs on, and the packages the window needs.

## The environment

```bash
conda env create -f environment.yml
conda activate bbmt-2026
```

`environment.yml` creates `bbmt-2026` (Python 3.11) and installs this package
(`mt-workbench`, import name `mt_workbench`) editable. Every dependency, the
window's included, is listed once, in `pyproject.toml`.

## The stack: the mtproc-fixes forks

mt-workbench runs on the `mtproc-fixes` branches of five forks,
`github.com/bvkay/` aurora, mth5, mt-io, mt-metadata and mt-timeseries, which
carry the fixes logged in `docs/upstream_issues.md`. `pyproject.toml` names each fork by git
URL (`mth5 @ git+https://github.com/bvkay/mth5@mtproc-fixes`, ...), so a
plain install fetches them. The aurora fork reports the version
`0.6.2+mtproc`.

A local clone of a fork, a sibling of this repository, installs over the
package from GitHub and leaves every other dependency as it is:

```bash
pip install --no-deps ../mt-metadata ../mt-timeseries ../mt-io ../mth5 ../aurora
```

The `*_fork_unit.py` tests ([tests.md](tests.md)) check the forks: the
clones and whatever is installed, reported side by side. Among the fixes:

| fork | issue | what the fork fixes |
|---|---|---|
| mt-io | 1, 2 | the LEMI-120 coil chain of a LEMI-423 read with a `calibration_fn`: valid unit names, the coil stage ahead of the linear stage. On the stock package such a site does not ingest |
| mt-io | 6 | four-digit LEMI-423 altitudes (`%Alt1060.0,m`) |
| mth5 | 5 | run summaries and kernel datasets open archives read-only. On the stock package a processing config cannot be built while another program (the window) holds an archive open, and a run touches the archives' modification times |
| mt-timeseries | 10 | a sample rate that is not a whole number is kept. On the stock package a 10.00064 Hz Orange Box run is dated at 10 Hz |
| mt-timeseries | 17 | a run's station lists its channels, with no phantom `auxiliary_default` |

## The packages of the window

`PySide6` and `pyqtgraph` draw the window. `mtpy-v2` draws the resistivity,
phase and phase-tensor plots of the View EDIs tab. It also brings in
`contextily` and `xyzservices`, which `scripts/fetch_basemap.py` uses to
fetch map tiles, and `geopandas`, `rasterio`, `pyproj`, `simpeg`, `bokeh` and
`panel`.
