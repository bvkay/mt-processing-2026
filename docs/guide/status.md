# Status

This page is the checklist of what is built (ticked) and what is open.

- [x] LEMI-423 ingest -> MTH5 (contiguous B423 files merged into long runs, a
      new run at any file-spacing anomaly; per-survey `channels` list drops the
      unconnected hz; per-survey `flip_reversed_dipoles` says whether a 180/270
      field-sheet azimuth means a reversed pair: true at Curnamona, false at Burra)
- [x] Aurora single-station / remote-reference wrapper -> EDI, with a
      processing window and an automatic impedance-phase-quadrant check
- [x] Comparison plots against legacy lemimt EDIs
- [x] Validation vs lemimt on a clean Curnamona Cube pair: D02 RR E08 matches
      the merged lemimt EDI over 0.005-~3000 s (rho and phase, both modes)
      with the lemimt-style 60-band scheme
- [x] Burra (noisy) first results: Burra35 RR Burra54rr3 matches lemimt
      0.005-1 s and 15-1000 s on its good-Ex window; Burra57 matches 15-1000 s;
      the 0.3-15 s cathodic-protection band is the open
      problem
- [x] Timing QC before ingest (`scripts/timing_qc.py`): no clock errors found
      at the Burra "Behind" sites; the one 1 s event is a remote file-boundary slip
- [x] Noise toolbox, first steps (`mt_workbench.noise`, `mt_workbench.ingest`; declared per
      site in `<survey>/filters.yaml`, applied at ingest in the listed order,
      provenance written into the archive): `replace` (borrow a magnetic
      channel from another site, with that site's coil calibration: the field
      crews' "replace magnetics" for a dead coil), `notch` (50 Hz + harmonics,
      zero-phase) and `cp` (cathodic protection: stack every cycle at the
      declared period in 10-min windows and subtract the median cycle from
      every channel, with no detection or cutting), declared by hand
      after looking at the QC figures.
- [x] Noise toolbox: `hp` and `lp` (zero-phase Butterworth), a
      `channels` list on `notch`, `mt_workbench.noise.apply_filters_arrays` (the one
      implementation; ingest delegates to it) and the Filter Data tab's
      live preview of the list on a loaded window.
- [ ] Noise toolbox, next: per-channel time masks, band schemes
- [ ] Band-placement experiment around mains: 50 Hz at band edge vs notched
      vs band centre (anchor option in bands.py), same data three ways
- [x] Stacked/synthetic remote references from multiple array sites: mean
      stack implemented and tested on D02 (found A07's dead hx in the process)
- [ ] Coherence-weighted stacking: per-member weights per time chunk and
      band group (0.1–1, 1–10, 10–100, 100–1000 s), then full per-band
      weighting at the Fourier-coefficient level; median stack as the
      robust baseline. Built: chunk-wise coherence weights
      (`mt_workbench.virtual`) and the band median (`mt_workbench.intersite`).
      Still open: per-band weighting at the Fourier-coefficient level.
- [x] Time-resolved coherence QC (`scripts/site_qc.py`, ported from the AusLAMP
      figures): whole-record overview, band coherence vs time, coherogram and
      spectrogram for Bx–Ey, By–Ex, Bx–By, Ex–Ey and the local-E vs remote-B
      pairs, the input for stack weights and time masks (next)
- [x] New-survey bootstrap from a raw folder (`scripts/new_survey.py`): B423
      headers -> `survey.yaml` via mt-io, `--site-table` merge, also reachable
      from the GUI's Metadata tab ("New survey...")
- [x] Channels recorded, per survey and per site: the presets in
      `mt_workbench.survey.CHANNEL_PRESETS` (LEMI-423: Ex Ey Bx By, + Bz,
      magnetics only, Bx By Bz; LEMI-424: E1-E4 Bx By Bz, E1 E2 Bx By Bz,
      Bx By Bz), `new_survey.py --channels` for the survey default, the
      Metadata tab's channels column for a site that differs
- [x] LEMI-424 and Earth Data PR6-24 (EDL) ingest and GUI (see
      [instruments.md](instruments.md)): the instrument detected per site folder,
      `instrument:` per site, the readers' own channel names in the archive
      and in every GUI view
- [x] Electric chain gain, EDL sites only (`electric_gain`):
      extra gain of the electric chain between the dipoles and the recorded
      values, beyond what the reader already models (the x10 terminal box),
      hardwired at the field terminal junction box, declared from the field
      notes when the PR6-24's own configs were not kept (Stuart Shelf 2009:
      10.0), `new_survey.py --electric-gain` for the survey default, the
      Metadata tab's `electric_gain` column for a site that differs
- [ ] An `electric_pair` setting saying which two of a LEMI-424's e1-e4 are
      Ex and Ey (aurora's LEMI12/LEMI34 nomenclature in `mt_workbench.process`); the
      GUI meanwhile pairs the first two electrics, E1 and E2
- [x] Desktop GUI (`src/mt_workbench/gui`): PySide6 + pyqtgraph
      launcher-and-viewer over the scripts and per-survey YAML, with QC,
      filter, processing and EDI tabs; see [gui.md](gui.md)
- [ ] Cross-power editor: the GUI's Cross-powers tab. Every STFT window's
      cross-powers are computed once (`mt_workbench.crosspower.compute_windows`), then per base
      chunk (10, 5, 2 or 1 min) and per decimation level on groups of base
      chunks long enough for 4 windows and 32 degrees of freedom, regrouped
      instantly without reading the archives, a window inside a larger store
      rounded out to whole minutes; |Z|, phase, coherence, |H| and |E|
      against time and the polar plane (log10 |Z| against phase per mode,
      the yx phase plus 180 deg wrapped to (-180, 180] as `cluster_masks.py`
      draws it, `mt_workbench.crosspower.mode_phase`, so a near-field source's yx
      cluster sits near 0 deg rather than across the +/-180 deg edges);
      masks per window and band saved per
      site as UTC intervals in `<survey>/masks.yaml`, `process_rr.py`
      applying the station's and the remote's of scope both (Process tab
      "apply masks.yaml"). Each entry's `scope` is `local` (the default,
      and what the tab, `cluster_masks.py` and `gate_masks.py` write: the
      mask applies when its site is the local of a pair, and the pairs
      that use the site as their remote keep those windows), `both`
      (also when its site is the remote) or `remote` (only when its site
      is the remote). An optional `channels` list (ex, ey, hx, hy, hz;
      every channel without it) says where the noise is: an entry naming
      only ex, ey or hz leaves out those TF rows alone as the local and
      nothing as the remote, one naming hx or hy leaves out whole windows.
      Entries taken out of use move to `masks_history.yaml`
      (`scripts/retire_masks.py`). Still open: the stacked editor
      estimate (`stack_impedance`, a window-count-weighted jackknife from
      5 groups) written as an EDI
- [ ] Burra in the GUI (93 sites, remotes filled per stage, `filters.yaml` for
      Burra35/57, timezone set; the config side is ready, untested in the GUI)
- [ ] EDL broadband (LEMI-120 coils on the PR6-24, `sensor_type="lemi120"`):
      only the Bartington long-period chain is wired
- [ ] Batch CLI
