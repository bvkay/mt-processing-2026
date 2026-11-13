# Campaigns

This page covers `scripts/campaign.py`, which runs every remote, the stacks
and a set of estimator options for each site of a line from a plan file,
and scores the products. Each product is one `process_rr.py` run
([commands.md](commands.md)).

## The command

```text
scripts/campaign.py <survey.yaml> <plan.yaml> [--stage 0,1,2,3] [--sites S ...] [--configs NAME[,NAME]] [--parallel N] [--max-runs N] [--allow-raw] [--dry-run] [--report]
```

- `--dry-run` prints every job with its state and hours and runs none. Do
  this first. It writes `refused_remotes.csv`, the remotes the overlap
  rule refused, and with `stages.remotes.max_candidates`
  `beyond_cap_remotes.csv`.
- `--stage`, `--sites` and `--configs` limit a run to those stages, local
  sites and stage 3 configs.
- `--report` redraws the scores, figures and summary from the ledger.
- `--allow-raw` is for a trial: its rows are marked provisional and run
  again next time.

## What a campaign runs

- Stage 0: the filtered variant of every site.
- Stage 1: every site against every eligible remote, default settings.
- Stage 2: per site, a stack of its nearest remotes, plain (`STK_<site>u`)
  and coherence-weighted (`STK_<site>w`), and the site against each.
- Stage 3: per site, on its best stage 1 remote (kept in
  `best_remote.json`), one run per config of the plan.

Stage 0 runs for every site first, then stages 1 to 3 group by group. A
remote is eligible when its record overlaps the local's by
`overlap.min_fraction` of the local record and by `overlap.min_hours`. A
site that lends the local its magnetics, the local's parent and a site
within 100 m are never its remote.

Everything goes to `<workspace>/campaign/<name>/`: `ledger.csv` (a row per
job), `runs.log`, a log per job in `logs/`, the products in `tf/`,
`scores.csv`, `figures/` and `summary.md`. The score ranks the products of
a site; judge a product on its figures.

- A campaign resumes: a row done with the same inputs (the site's filters,
  its raw archive, the masks and flags of the run) is not run again.
- A run passes `--no-masks`, to compare every remote and option on the
  same data. `runner.masks: true`, or `--masks` in a config, applies
  masks.yaml.
- Refused at the start (exit 2): a site or config not in the plan, and a
  `runner.min_available_gb` the machine can never meet.

## The plan

A YAML file beside survey.yaml. `name`, `sites` and `groups` are needed,
and every site belongs to one group.

```yaml
name: lineC
sites: [C01, C02, C03, C04]
groups: {A: [C01, C02], B: [C03, C04]}
stages:
  options:
    configs:
      boxcar: [--taper, boxcar]
```

| key | meaning (default) |
|---|---|
| `name`, `description` | the campaign's folder and tag prefix (`<name>-<config>`); its summary text |
| `sites`, `groups` | the line in order; `{G: [SITE ...]}`, the deployment groups in processing order |
| `exclude` | `{SITE: reason}`: sites left out |
| `remote_only`, `never_remote` | sites that are only remotes, such as an observatory; plan sites that are never one |
| `overlap` | `{min_fraction, min_hours}` of the remote rule (0.5, 12) |
| `stages.remotes` | `max_candidates`: keep the N nearest eligible remotes; `flags`: `process_rr.py` flags on stage 1 |
| `stages.stacks` | `weightings` (`{u: none, w: coherence}`; `{}` for no stacks), `exclude_members`, and `flags` on stage 2 |
| `stages.options` | `configs: {NAME: [flags]}`, the stage 3 runs; `tie_tolerance` of the best-remote choice (0.02) |
| `rr_flags`, `min_band_windows` | `process_rr.py` flags, and `--min-band-windows N`, on every run |
| `remotes`, `modes` | `{SITE: REMOTE}`: a site's stage 3 remote; `{SITE: [xy]}`: the modes its score uses |
| `windows` | `{SITE: {yx: [start, end], merge: true}}`: a run over that window (UTC) and, with `merge`, a product with the other mode from the full record; or the name of the file `health_windows.py` wrote |
| `window_merge` | `{short, long, rule}`: one more product per site by `merge_windows.py` |
| `scoring` | `pmin`, `pmax`: the period window of the scores (the survey's); `quadrant_term`, `coverage`, `min_coverage`: the form of the score |
| `runner.parallel` | jobs at once (`gate`: as many as the memory gate admits) |
| `runner.min_available_gb`, `peak_factor`, `expected_peak_gb`, `peak_percentile`, `peak_recent`, `mantle_gb_per_hour` | the memory gate: a job starts with `min_available_gb` (40) free beyond what the running jobs are expected to take |
| `runner.minutes_per_job` | for the hours of the dry run |
| `runner.deferred_configs` | stage 3 configs run only when `--configs` names them |
| `runner.move_products`, `runner.masks` | move the products into the campaign's `tf/` (true); apply masks.yaml (false) |

## MANTLE configs

A config that names `--engine mantle` runs with `--no-masks` and
`--mantle-window clip`: a pair whose overlap is longer than its
`--mantle-max-hours`, or holds a gap, is processed over the longest span
both records cover. A job that needs more memory than the machine has is
marked skipped. To run MANTLE over a whole common span once the machine is
free, name the config in `runner.deferred_configs` and run it alone with
`--stage 3 --configs NAME --parallel 1`.
