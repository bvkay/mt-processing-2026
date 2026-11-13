# Tests

This page says how to run a test and lists every file of `tests/` with what
it checks, grouped by subject.

## Running a test

Each file is a script. Run it on its own from the repository folder in the
`bbmt-2026` environment:

```bash
python tests/survey_unit.py
QT_QPA_PLATFORM=offscreen python tests/gui_smoke.py
```

- A pass exits 0, in most tests after a last line starting `PASS`. A failure exits non-zero with the failed check or a traceback.
- *window*: the test opens the window or one of its tabs. Use the second form, which opens it without a screen.
- *external*: the test reads recordings, archives, products or survey files that are not in the repository. These tests are local only: a clone of the repository cannot run them in full. Without them some tests leave that part out and say so; the others stop with an error.
- Most tests write under `mt_workbench_tests/` in the system temp folder. `MT_WORKBENCH_TEST_SCRATCH` names another folder to hold it.
- `_scratch.py` (the scratch folders) and `instrument_samples.py` (one-hour LEMI-424 and EDL samples cut from the recordings, *external*) are helpers, not tests.

## The window

- `gui_smoke.py`: every tab, on the Curnamona survey; screenshots in `surveys/curnamona_cube/work/qc`. *window*, *external*
- `gui_missing_workspace_unit.py`: a survey whose workspace folder does not exist. *window*
- `timeseries_build_unit.py`: Time Series tab: Build MTH5 on a burst site. *window*
- `process_tab_unit.py`: Process tab: masks switch, engine, band controls. *window*, *external*
- `process_station_list_unit.py`: Process tab: the station list. *window*, *external*
- `process_type_unit.py`: Process tab: processing type, the queued tensor command. *window*
- `edi_index_unit.py`: View EDIs: the list from `tf/index.json`. *window*
- `view_tensors_unit.py`: View tensors tab and the tensor figure. *window*
- `crosspower_masks_wait_unit.py`: Cross-powers tab: mask buttons while `masks.yaml` is read. *window*
- `crosspower_workers_unit.py`: Cross-powers tab: the worker count. *external*
- `crosspower_unit.py`: `mt_workbench.crosspower`: windows, bins, chunks, stacked impedance.
- `span_cache_unit.py`: record spans read for the window bars. *external*
- `windows_unit.py`: the windows offered for a record.
- `segment_unit.py`: spectra, spectrogram and coherence of a loaded window.
- `psd_ladder_unit.py`: the whole-spectrum PSD, with gaps.
- `basemap_unit.py`: `fetch_basemap.py`, without the network.

## The survey file

- `survey_unit.py`: `mt_workbench.survey`: site keys, presets, instrument detection.
- `new_survey_unit.py`: `new_survey.py` on synthetic, mixed-recorder and Curnamona folders. *external*
- `declination_unit.py`: `declination.py`: the IGRF fill, `--write`, `--check`.
- `instrument_pid_unit.py`: instrument registry DOIs, `survey.yaml` to products; `pidinst_lookup.py`.

## Ingest

- `ingest_unit.py`: `mt_workbench.ingest`: raw archive, variant, real LEMI-424 and EDL hours. *external*
- `ingest_site_cli_unit.py`: `ingest_site.py`: `--all`, `--parallel`, the DC level line. *external*
- `lemi424_ingest_unit.py`: LEMI-424 ingest: names, E sign, metadata. *external*
- `b423_cut_file_unit.py`: a LEMI-423 file cut short ends its run.
- `b423_rate_callers_unit.py`: the same cut-file rule in `psd_qc.py` and `profile_run.py`.
- `variant_held_open_unit.py`: a variant rebuilt while another program holds it open.
- `decimate_unit.py`: `decimate_site.py` and the derived 1 Hz site.
- `dc_level_unit.py`: `dc_level_check.py`: open inputs and saturated channels.
- `ingest_clock_offset_unit.py`: `clock_offset_s`: the time axes moved by the offset.
- `ingest_flip_h_unit.py`: `flip_h`: one coil reversed. *external*
- `ingest_swap_h_unit.py`: `swap_h`: hx and hy exchanged with their calibration.
- `ingest_swap_h_provenance_unit.py`: `swap_h`: the source each exchanged channel records.
- `ingest_swap_e_unit.py`: `swap_e`: the electric channels exchanged.
- `ingest_h_from_unit.py`: `h_from`: magnetics borrowed from a neighbour.
- `ingest_h_from_edl_unit.py`: `h_from` between EDL sites.
- `ingest_h_tilt_unit.py`: `h_tilt`: a tilted fluxgate corrected.
- `ingest_rot_h_unit.py`: `rot_h`: the fluxgate pair turned onto magnetic north.
- `ingest_rot_h_parts_unit.py`: `rot_h_parts`: a turn per part of the record.
- `h_azimuth_unit.py`: `h_azimuth.py`: the fluxgate azimuth and its `rot_h` write. *external*
- `rot_e_unit.py`: an electric pair laid off the axes, turned at ingest.
- `ingest_record_window_unit.py`: `record_window`: samples outside the window left out.
- `ingest_electric_gain_channel_unit.py`: `electric_gain_ex`, `electric_gain_ey`: a gain per electric channel.
- `ingest_edl_banks_swapped_unit.py`: `edl_banks_swapped`: magnetic and electric cables in each other's inputs.
- `ingest_edl_overlap_unit.py`: EDL restart files overlapping the file before.
- `edl_null_stamp_unit.py`: an EDL file with bytes and no samples.
- `edl_own_files_unit.py`: which files of an EDL folder are the station's.
- `edl_two_trace_unit.py`: an EDL first file holding a test run.
- `edl_unpack_unit.py`: `edl_unpack.py` on a synthetic zip.
- `observatory_unit.py`: `fetch_observatory.py`, without the network.
- `observatory_from_parquet_unit.py`: `observatory_from_parquet.py` on a synthetic record.
- `observatory_rot_h_unit.py`: `observatory_rot_h.py`: an observatory archive turned onto magnetic north.

## Phoenix, MTU-5A and Orange Box

- `phoenix_files_unit.py`: Phoenix files: names, start times, run plan, calibration file.
- `ingest_phoenix_unit.py`: Phoenix ingest on cuts of real recordings, bursts included. *external*
- `ingest_swap_e_phoenix_unit.py`: `swap_e` on a Phoenix site. *external*
- `phoenix_archive_unit.py`: the stamp correction read from a Phoenix archive. *external*
- `phoenix_h_polarity_check_unit.py`: the warning for an archive without the H polarity stage. *external*
- `burst_station_metadata_unit.py`: station metadata of a burst site with many runs.
- `mtu5a_unit.py`: the MTU-5A reader on synthetic files. *external*
- `orangebox_unit.py`: the Orange Box reader of mt-io. *external*
- `orangebox_ingest_unit.py`: Orange Box detection and ingest on synthetic files.
- `orangebox_h_from_unit.py`: `h_from` on Orange Box sites.
- `orangebox_lp_name_unit.py`: Orange Box files named `LP<n>-NNN.BIN`.

## Filters and masks

- `noise_unit.py`: the filter kinds on synthetic data.
- `noise_chunks_unit.py`: the mains filter in chunks equals one pass.
- `noise_template_unit.py`: the `template` filter kind.
- `filter_trial_unit.py`: `filter_trial.py`: metrics, figures, JSON.
- `line_scan_unit.py`: `line_scan.py`: narrow spectral lines.
- `line_noise_unit.py`: `line_noise_profile.py`: step, shift, burst and coherence measures.
- `masks_unit.py`: `masks.yaml` read and written; time masks cut from a run.
- `masks_cache_unit.py`: `masks.yaml` parsed once per change.
- `mask_scope_unit.py`: mask `scope`: local, both or remote.
- `mask_channels_unit.py`: mask `channels`, and the mask history.
- `band_masks_unit.py`: band-limited masks inside aurora.
- `process_rr_masks_file_unit.py`: `process_rr.py --masks-file`: masks from another file.
- `cluster_masks_unit.py`: `cluster_masks.py`: clusters of one band masked.
- `gate_masks_unit.py`: `gate_masks.py`: night masks, the burst detector.
- `stretch_masks_unit.py`: `stretch_masks.py`: masks outside the usable stretches of an electric line.

## MT processing and its products

- `process_rr_cli_unit.py`: `process_rr.py`: dry run, flags, sidecar, the three products. *external*
- `process_rr_pair_check_unit.py`: `process_rr.py --dry-run`: a missing archive, no common time.
- `process_rr_overlap_sidecar_unit.py`: the overlap per level in the sidecar; leaves two tagged products in that workspace. *external*
- `derived_sites_rr_unit.py`: derived 1 Hz sites in remote-reference runs and stacks.
- `survey_id_cut_unit.py`: a survey name over 30 characters.
- `bands_unit.py`: the band layout; too-narrow bands refused.
- `short_window_unit.py`: the `min_band_windows` floor and the zero-error guard. *external*
- `min_band_windows_engine_unit.py`: `min_band_windows` under aurora and MANTLE.
- `engine_mantle_unit.py`: the MANTLE engine; skipped without MANTLE.
- `mantle_window_unit.py`: the window of a `--mantle-window clip` run.
- `sidecar_versions_unit.py`: package versions and sources in the sidecar.
- `unknown_declination_unit.py`: an unknown declination left out, never written as 0.
- `products_zrot_unit.py`: `products: {zrot: declination | zero}`; the instrument INFO lines. *external*
- `products_zrot_round2_unit.py`: `zrot: zero` in XML, `merge_best.py`, `deliver_as_laid.py`.
- `products_geometry_unit.py`: dipole lengths and azimuths in the EDI.
- `xml_comment_keys_unit.py`: a run comment key with a dot, in the XML. *external*
- `hyphen_station_export_unit.py`: EDI and XML of a station name with a hyphen. *external*
- `compare_unit.py`: the phase-quadrant check. *external*
- `compare_imports_unit.py`: `mt_workbench.compare` imports matplotlib only to draw.
- `compare_unmerged_unit.py`: `compare_unmerged.py`: site names, one run end to end.
- `merge_modes_unit.py`: `merge_modes.py`: x row from one product, y row from another.
- `merge_best_unit.py`: `merge_best.py` on synthetic products.
- `merge_windows_unit.py`: `merge_windows.py`: short-window and long-window products joined by period.
- `deliver_as_laid_unit.py`: `deliver_as_laid.py`: a reversed electric line as laid.

## Stacks

- `virtual_unit.py`: the stacked remote, plain and coherence-weighted.
- `stack_calibration_unit.py`: the calibration a stack carries.
- `stack_identity_member_unit.py`: a stack member without a filter chain.
- `stack_pieces_unit.py`: `build_stack.py --min-piece-h`: the stack in pieces.
- `stack_median_unit.py`: the band median stack (`--quick`: without four other tests).
- `stacks_unit.py`: `stacks.yaml` recipes: saving, validation, members.
- `stack_recipe_cli_unit.py`: `process_intersite.py --stack`, `build_stack.py --recipe` (`--quick`: without five other tests). *external*
- `availability_model_unit.py`: Stacks tab: availability rows.
- `availability_chart_unit.py`: Stacks tab: availability chart. *window*
- `stack_check_unit.py`: Stacks tab: the member check. *window*
- `stacks_tab_unit.py`: Stacks tab and the recipe picker. *window*
- `stacks_tab_shots.py`: not a test: figures of the member check (`--out DIR`). *window*

## Inter-site tensors and the network datum

- `intersite_unit.py`: `process_intersite.py`: a known telluric tensor and delay recovered.
- `intersite_errors_unit.py`: stated errors against scatter; the Huber estimate.
- `intersite_coherence_unit.py`: coherence columns, plain and weighted.
- `intersite_flags_unit.py`: flag columns; a flag never removes a period.
- `intersite_frames_unit.py`: site frames recorded, not applied.
- `intersite_masks_unit.py`: `masks.yaml` in tensor runs.
- `intersite_runs_unit.py`: each run calibrated with its own chain.
- `intersite_delay_scan_unit.py`: the delay scan of the timing check.
- `intersite_bursts_unit.py`: burst sites in a tensor run.
- `intersite_stack_unit.py`: `--remote-stack`: the band stack as reference.
- `intersite_basestack_unit.py`: `--base-stack E`: electric stack as base.
- `intersite_basestack_h_unit.py`: `--base-stack H`: magnetic stack as base.
- `intersite_stack_edge_unit.py`: stack members ending near the edges of the window.
- `merge_tensor_bands_unit.py`: `merge_tensor_bands.py`: burst and continuous products joined.
- `network_unit.py`: `mt_workbench.network`: the datum on synthetic networks.
- `solve_datum_unit.py`: `solve_datum.py` on synthetic pair products.

## Campaigns

- `campaign_unit.py`: `campaign.py`: plan, stages, resume, dry run, runner. *external*
- `campaign_first_pass_unit.py`: remote rules and plan keys of a first pass.
- `campaign_overlap_gate_unit.py`: the stage 1 overlap gate.
- `campaign_stage_flags_unit.py`: plan keys `stages.remotes.flags`, `stages.stacks.flags`.
- `campaign_config_flags_resume_unit.py`: resume after the flags of a stage 3 config change.
- `campaign_window_merge_unit.py`: plan key `window_merge`.
- `campaign_gate_unit.py`: jobs the memory gate starts by default.
- `campaign_memory_refusal_unit.py`: a memory gate the machine cannot meet.
- `campaign_variant_dry_run_unit.py`: stage 0 dry run over built variants.
- `quality_unit.py`: `mt_workbench.quality`: the score of a product.
- `quality_coverage_unit.py`: the coverage form of the score (`scoring.quadrant_term`).
- `quality_window_coverage_unit.py`: window coverage in the score (`scoring.coverage`).
- `health_windows_unit.py`: `health_windows.py`: a window per mode from the health table.

## Site health and the shared centre electrode

- `health_unit.py`: the health table on synthetic records.
- `health_rot_e_unit.py`: the health table where ingest turned the electric pair.
- `health_qld_crosscheck.py`: the health table against the code it was ported from. *external*
- `shared_centre_test_unit.py`: `shared_centre_test.py`: a noisy shared centre electrode.
- `diagonal_site_unit.py`: `diagonal_site.py`: the diagonal electric line of a site.
- `diagonal_site_rot_e_unit.py`: `diagonal_site.py` where ingest turned the pair.
- `site_qc_calibration_unit.py`: `site_qc.py`: the tolerance of its calibration check.

## The notebook, the QC folder and profiling

- `harvest_notes_unit.py`: `harvest_notes.py` on a synthetic notebook.
- `organise_qc_unit.py`: `organise_qc.py` on a synthetic `qc` folder.
- `profile_unit.py`: `profile_run.py`: log phases, sampler, trace stage.

## The forked libraries

Each test compares a fork ([install.md](install.md)) with the stock package.
The fork is its clone in the folder `MT_WORKBENCH_FORKS` names or, for
aurora and mt-io, the installed package. With no fork found, the fork checks
are reported as skipped.

- `mth5_fork_unit.py`: the mth5, mt-metadata and mt-timeseries forks.
- `aurora_fork_unit.py`: the aurora fork against stored stock results.
- `mtio_fork_unit.py`: the mt-io fork on synthetic files.
