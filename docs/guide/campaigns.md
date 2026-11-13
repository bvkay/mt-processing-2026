# Campaigns

This page covers `scripts/campaign.py`, which processes a whole line of
sites from a plan file: its stages, the keys of the plan, the memory gate
and the MANTLE runs.

## The command

```text
scripts/campaign.py <survey.yaml> <plan.yaml> [--stage 0,1,2,3] [--sites S ...] [--configs NAME[,NAME]] [--parallel N] [--max-runs N] [--dry-run] [--report]
```

Processing campaign over a line (plan YAML, e.g. `surveys/MT_Morocco_Atlas_Mountains/campaign_lineC.yaml`): stage 0 filtered variants, 1 every site rr every concurrent remote, 2 leave-one-out stacks (plain and coherence-weighted), 3 estimator/band options on each site's best remote, MANTLE among them (`mantle: [--engine, mantle, --mantle-max-hours, "72"]`, run with `--mantle-window clip`, its expected peak by window length; see [How a campaign runs](#how-a-campaign-runs)).

- per-site plan keys: `remotes: {SITE: REMOTE}` sets a site's stage 3 remote (reported as the best, ledger note "remote override"), `modes: {SITE: [xy]}` scores the site on those modes (summary "xy-only"), `windows: {SITE: {yx: [start, end], merge: true}}` adds a default run over the window (`<name>-default-yxwin`) and a merged product (`<name>-default-merged`, scripts/merge_modes.py's `merge_files`: xy from the full-record default, yx from the window) shown as the site's default in `summary.md`
- resumable (`ledger.csv`, with each product's engine from its sidecar), `--parallel` jobs behind a memory gate, products scored by `mt_workbench.quality` over their own periods (scores.csv gives each product's engine and period range: a MANTLE product stops near 1000 s) and plotted per site and line-wide into `<workspace>/campaign/<name>/`, `summary.md`
- `--report` redraws from the ledger

## How a campaign runs

`scripts/campaign.py` runs a plan (a YAML beside the survey, e.g.
`surveys/<survey>/campaign_lineA.yaml`) into
`<workspace>/campaign/<name>/`: stage 0 builds the filtered variants, stage 1
runs every site against every concurrent remote, stage 2 the leave-one-out
stacks, stage 3 each plan config on the site's best stage 1 remote (kept in
`best_remote.json`). Every run is a row of `ledger.csv`; a row done with the
same inputs (each site's filters hash and raw archive mtime, the masks
applied) is not run again, a failed one is. `--dry-run` prints every row
with its state, hours and, for a MANTLE row, its window and expected peak,
and writes nothing.

A MANTLE config (`--engine mantle`) is run with `--no-masks` and
`--mantle-window clip` unless its flags name `--mantle-window`: a pair whose
overlap is longer than the config's `--mantle-max-hours` (24 h without the
flag) or holds a gap is processed over the longest span both records cover,
its first `--mantle-max-hours` hours, where it would be refused. The row's
note gives the clip expected from the survey spans, then the one its sidecar
records. A MANTLE job is held at the memory gate by hours x
`runner.mantle_gb_per_hour` (1.25 GB; the line A runs peaked at 1.22 GB per
hour plus 0.2 GB) or its class figure, whichever is larger, and a job
expected above the machine's memory less `runner.min_available_gb` is marked
skipped with what it needs and what the machine has.

## The plan keys

| plan key | meaning |
|---|---|
| `name`, `description` | the campaign's folder and tag prefix (`<name>-<config>`), and its summary text |
| `sites`, `exclude: {SITE: reason}`, `groups: {G: [SITE ...]}` | the line in order, the sites left out with why, the deployment groups in processing order |
| `overlap: {min_fraction, min_hours}` | a remote overlaps the local by at least this share of its record or this many hours |
| `stages.stacks.weightings` | stack suffix to weighting (`u: none`, `w: coherence`) |
| `stages.options.configs: {NAME: [flags]}` | the stage 3 configs, process_rr.py flags each |
| `stages.options.tie_tolerance` | scores within this of the top count as a tie in the best-remote choice |
| `remotes`, `modes`, `windows` | per-site stage 3 remote, scored modes, and mode windows with an optional merge |
| `scoring: {pmin, pmax}` | the period window of the scores |
| `min_band_windows: N` | `--min-band-windows N` (a whole number, 0 or more) on every aurora rr job of stages 1, 2 and 3, the `windows:` runs too, after the runner's `--no-masks` and before a config's flags, so a config's own `--min-band-windows` wins; none on a MANTLE config; shown in the dry run (each job's options and the plan's line), the start log and summary.md; part of a job's inputs unless its config gives its own floor, so a change re-runs the rows; without the key, no flag and nothing in the inputs |
| `runner.minutes_per_job`, `runner.expected_peak_gb` | per kind or per config: the dry run's minutes and the memory gate's peak |
| `runner.min_available_gb`, `runner.peak_factor`, `runner.peak_percentile`, `runner.peak_recent` | the memory gate |
| `runner.parallel` | jobs at once when `--parallel` is not given; `gate` (the default) takes as many rr jobs as the memory gate admits with the memory available at start, at least 1; the runner logs that count and the rr peak it used (a dry run prints it) |
| `runner.mantle_gb_per_hour` | a MANTLE job's expected peak per hour of window (1.25) |
| `runner.deferred_configs: [NAME ...]` | stage 3 configs run only when `--configs` names them |
| `runner.move_products`, `runner.masks` | move products into the campaign's `tf/`; apply masks.yaml to every rr run |

## MANTLE over the whole common span

MANTLE over a site's whole common span, once the machine is free: add

```yaml
stages:
  options:
    configs:
      mantle_full: [--engine, mantle, --mantle-max-hours, "100"]
runner:
  deferred_configs: [mantle_full]
```

to the plan. The config is left out of every run of the campaign, and when
the other campaigns have ended

    python scripts/campaign.py <survey.yaml> <plan.yaml> --stage 3 --configs mantle_full --parallel 1

runs each site's best-remote pair over its whole common span (clipped only by
gaps and by the 100 h cap), one at a time, each held at the gate until its
memory is free. It reads the best remotes from `best_remote.json` and the
done rows from the ledger, so on a finished campaign nothing else runs; run
it with `--dry-run` first to see each row's hours, expected peak and the rows
too large for the machine.
