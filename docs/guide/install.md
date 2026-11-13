# Install and the forked libraries

This page covers the conda environment, the five forked libraries
mt-workbench runs on, and the packages the window needs.

## The environment

```bash
conda env create -f environment.yml
conda activate bbmt-2026
```

`environment.yml` creates `bbmt-2026` (Python 3.11) and installs this package
(`mt-workbench`, import name `mt_workbench`) editable; every dependency, the GUI's
included, is listed once, in `pyproject.toml`.

## The stack: the mtproc-fixes forks

mt-workbench runs on the `mtproc-fixes` branches of five forks, `github.com/bvkay/`
aurora, mth5, mt-io, mt-metadata and mt-timeseries, which carry the fixes
logged in `docs/upstream_issues.md`. `pyproject.toml` names them by git URL
(`mth5 @ git+https://github.com/bvkay/mth5@mtproc-fixes`, ...); all five branches are on
GitHub, so a plain install resolves them. The forks carry their own names: branch `mtproc-fixes`, aurora version
`0.6.2+mtproc`. A local clone (a sibling of this repo) installs over the
package from GitHub, leaving every other dependency as it is:

```bash
pip install --no-deps ../mt-metadata ../mt-timeseries ../mt-io ../mth5 ../aurora
```

The `*_fork_unit.py` tests ([tests.md](tests.md)) check each fork (the clones, and whatever is
installed, reported side by side). mt-workbench patches none of the stock
packages at runtime; the forks fix these bugs at the source:

- mt-io (issues 1, 2, 6): the LEMI-120 coil chain of a LEMI-423 read with a
  `calibration_fn` (valid unit names, coil stage ahead of the linear stage)
  and four-digit LEMI-423 altitudes (`%Alt1060.0,m`);
- mth5 (issue 5): run summaries and kernel datasets open archives read-only;
- mt-timeseries (issue 17): a RunTS station lists its channels, with no
  phantom `auxiliary_default`.

On stock packages these are bugs: a LEMI-423 site with a
`calibration_fn` does not ingest (stock mt-io's coil response carries a unit
mt_metadata rejects), building a processing config fails while another
process (the GUI) holds an archive open and touches the archives'
modification times, a 10.00064 Hz Orange Box run is dated at 10 Hz, and an
observatory archive's station lists `auxiliary_default`.

## The packages of the window

The window's dependencies (`pyproject.toml`): `PySide6` and
`pyqtgraph` for the GUI itself, and `mtpy-v2` (2.1.4) for the View EDIs tab's
rho/phase and phase-tensor plots (induction arrows later), which also drags
in `contextily` + `xyzservices` (reused by `scripts/fetch_basemap.py`'s tile
fetch), `geopandas`, `rasterio`, `pyproj`, `simpeg`, `bokeh` and `panel`.
