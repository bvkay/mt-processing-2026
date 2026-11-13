# Inter-site tensors and the network datum

This page covers the telluric and magnetic tensors between two sites:
estimating one, reading its product, and the network datum, which turns
pair products into one potential per site.

## What the tensors are

For two sites recording at the same time, the telluric tensor maps the
base's ex, ey onto the local's, and the magnetic tensor does the same for
hx, hy: a 2 x 2 complex tensor per period of the survey's band layout,
dimensionless once each channel is calibrated.

psi = arg(det) / 2, in degrees, is the phase of the local's field less the
base's. A tensor and its psi are read against their base: another base
gives another tensor.

Each tensor is referenced to a third site and stays in the two sites'
channels as recorded: no rotation is applied, and the azimuths and
declination are recorded in the product, not applied.

## Estimate one pair

In the window, choose a tensor type on the Process tab
([gui.md](gui.md#process)). From the command line:

```text
python scripts/process_intersite.py <survey.yaml> <local> <base> [start] [end] --kind telluric|magnetic --remote SITE
```

`start` and `end` are UTC (`"2022-02-14 06:00"`); without them the window is
the time the three sites share. A run that cannot go ahead is refused with
the reason (exit 2), for example a site without an archive, sites at
different sample rates, or a reference that is the local, the base or a
`build_stack.py` archive.

| option | what it does | default |
|---|---|---|
| `--kind telluric\|magnetic` | the tensor, on ex, ey or on hx, hy | required |
| `--remote SITE`, `--remote-channels hx,hy\|ex,ey` | the reference site and its channels | `hx,hy` |
| `--remote-stack E\|H` | reference: the other sites' stacked ex, ey or hx, hy | |
| `--base-stack E\|H` | base: a stack | |
| `--stack NAME` | a `stacks.yaml` recipe as base or reference | |
| `--exclude LIST`, `--remote-exclude LIST` | sites left out of a stack; with two stacks, of the reference stack alone | |
| `--min-overlap-hours H`, `--stack-reject-factor F`, `--stack-min-members N`, `--stack-method mean\|median`, `--stack-plain` | how a stack chooses, screens and combines its members (`--help` describes each) | 12, 25, 2, `mean`, off |
| `--window-members-constant`, `--allow-member-change` | base stack: refuse, or run, a window in which a member's record starts or ends | refuse |
| `--screen-polarity flag\|drop` | base stack: flag or drop a reversed member, one that correlates negatively with the others over 1-100 s | `flag` |
| `--allow-shared-members` | base stack: allow a reference sharing a site with it | refused |
| `--min-period S` | shortest period, s | the survey's; a faster site takes the layout's shortest at or above 4 / rate |
| `--tag TAG`, `--out-dir DIR` | suffix of the stem; output folder | none; `<workspace>/tf` |
| `--no-filters` | read each site's raw archive | its filtered archive where filters are declared |
| `--dry-run` | print what the run resolved to and its expected memory, and exit: run it first | |

### What a run writes

Four files in `<workspace>/tf`, stem `<local>_te-<base>_rr-<remote>[_<tag>]`
(`_hm-` for the magnetic tensor): `.csv` (one row per period), `.json` (the
sidecar: the facts of the run, with the blocks `masks`, `frames`, `flags`
and `timing_check`), `.h5` and `.png`. No EDI or XML is written: an EDI
reader would take a tensor for an impedance. In the stem a remote's
electrics read `<site>-E` and a stack `stackE` or `stackH` (`stackEmed`,
`stackHmed` with the median) or its recipe's name. A run with the same
stem replaces the earlier product: give `--tag` to keep both.

Every band of the layout has a row in the CSV; a band the record could not
form has `n_windows` 0 and NaN values. A flag marks a period and never
removes it.

| column | holds, or is raised when |
|---|---|
| `period`, `n_windows`, `n_groups` | the band's period (s), its windows and its jackknife slices |
| `T_xx_re`, `T_xx_im`, `T_xx_err` | an element and its jackknife error (also xy, yx, yy; `M_` for the magnetic tensor) |
| `half_arg_det_deg`, `half_arg_det_err_deg` | psi and its error, deg |
| `max_abs_minus_identity` | the largest element of the tensor less the identity |
| `coh_out_weighted_x`, `coh_out_weighted_y` | coherence of each output with the reference under the final weights |
| `flag_not_estimated` | an element is not finite |
| `flag_few_groups` | under 5 of the 20 jackknife slices hold a solution |
| `flag_low_coherence` | `coh_out_weighted_x` or `coh_out_weighted_y` under 0.1 |
| `flag_off_diagonal` | \|xy yx\| > \|xx yy\|: one site's electric channels exchanged, or over 45 deg between the layouts |
| `flag_re_det_negative` | Re det < 0: such an exchange, or psi beyond 45 deg |

The other columns include the band's edges, the determinant and the
unweighted coherences, which on bursty electrics can read near zero where
the tensor is well determined.

### Check the timing first

A run prints a delay tau fitted to psi over the shortest decade of periods
(tau > 0: the local lags the base). A clock offset between the loggers
shows here (10 ms is 3.6 deg at 1 s): do not read it as a phase between
the sites. `delay not determined` is printed with the reason: the phases
make no line, their errors are too large to show one, or the delay lies
at the limit of the scan (1 s at most), as a delay beyond 1 s does;
whole seconds are found with `scripts/timing_qc.py`.

### Masks

`masks.yaml` is always applied: a window holding a sample inside an entry
is left out of the bands the entry covers. The local and the base take
their entries of scope `local` or `both`, the reference those of scope
`both` or `remote`; an entry naming none of the channels the run reads is
left out, and the members of a stack take none. Scope: `process_rr.py` in
[commands.md](commands.md).

## A stack as the base

`--base-stack E` (telluric) or `H` (magnetic) takes as the base the stack
of every other site live through the window, which ties every site to one
regional field. No `<base>` is given: the positionals after the local are
`start` and `end`.

- The tensor is relative to that mix of members: run one window per epoch
  of constant membership. A start or end within 60 s of the window's
  edges, or a gap of 60 s or less, is no change.
- The magnitudes are in each band's normalised units, not field ratios;
  the phases and psi are unaffected. Column r divided by
  `stack_scale_rms[r]` of the sidecar's `base_stack` block is the ratio to
  a member's field when the members are calibrated alike.

`--stack NAME` runs a band recipe saved on the Stacks tab as the base
(`use: base`) or the reference (`use: reference`); give it twice for one of
each. A base recipe takes no `<base>`, a reference recipe no `--remote`.
The recipe's members, window and stack options are the run's: `start` and
`end` replace its window, and a stack option beside it is refused.

## One tensor over a Phoenix receiver's whole band

A Phoenix receiver records a continuous stream and 24 kHz bursts
([instruments.md](instruments.md)). Estimate the pair on the burst sites
(`G5H G8H --remote G6H`; all three must be burst sites, without stacks) and
on the continuous sites (`G5 G8 --remote G6`), then stitch the two
products. The two share band edges only with the `min_period` that
`new_survey.py` writes for a Phoenix survey, 0.026878315731090622 s: do not
round it.

```text
python scripts/merge_tensor_bands.py <bursts .json> <continuous .json> [--accept-disagreement] [--out-dir DIR]
```

It writes `<continuous stem>_wide` (`.csv`, `.json`, `.h5`, `.png`) beside
the continuous product or in `--out-dir`: the burst rows below the first
band both products hold, the continuous rows from it on. It is refused
(exit 2) when a shared band differs by more than 2 combined sigma
(`--accept-disagreement` writes the merge and records it), when the band
edges do not coincide (the message gives the `min_period` that aligns
them), and when the two products differ in sites, tensor, estimator
settings or stamp corrections, or one has a stack.

## The network datum

`scripts/solve_datum.py` turns the pair products into one potential phi per
site at every period, in degrees: each product gives psi = phi_local -
phi_base modulo 180 deg, solved by weighted least squares over each
connected group of sites (a component).

```text
python scripts/solve_datum.py <survey.yaml> --pairs PAIRS_CSV [--out DIR] [--leave-out-flag NAME] [--scale-by-closure] [--band LO-HI]
```

The pairs table is a CSV with one row per product, all of one tensor and
one band layout: `sidecar` (the product's `.json`, a relative path taken
against `<workspace>/tf`) and, optional, `use` (`false` keeps the product
out of the solve), `note` and `base` (needed for a base stack: the site
name it takes in the network). Three pairs that close a loop:

```text
sidecar
A_te-B_rr-R.json
B_te-C_rr-R.json
A_te-C_rr-R.json
```

| option | what it does | default |
|---|---|---|
| `--out DIR` | folder of the tables; it must not exist | `<workspace>/datum/<pairs table stem>` |
| `--leave-out-flag NAME` | leave the rows carrying that flag out of the solve; repeatable | |
| `--scale-by-closure` | multiply a component's site errors by its sqrt(chi2/dof) when over 1 (`errors_scaled`) | off |
| `--band LO-HI` | also write `datum_bands.csv`, each site's mean `phi_rel_deg` over LO-HI s: a reading, not an input to the solve; repeatable | |

A row that is not estimated or has no error cannot enter; every other row
enters unless `use` is false or its flag is named.

| table | read |
|---|---|
| `datum_sites_period.csv` | `phi_rel_deg` and `phi_rel_err_deg`, the product: each site's potential relative to the median of its component. An error of 0 marks the median site, not an exact value |
| `datum_periods.csv` | `chi2_dof` and its 99 % interval (`chi2_dof_lo99`, `chi2_dof_hi99`): inside it the pair errors describe the misfit; outside it `phi_err_deg`, the formal error given the pair errors, is not a measured error. `n_err_over_52` counts the rows with an error over 52 deg, which pull it down; `n_far_from_centre` the sites over 60 deg from their component's centre, where the median depends on where the circle is cut |
| `datum_loops.csv` | each loop a pair closes: `closure_deg`, `sigma_deg`, `z`, `pairs` |
| `datum_pairs_period.csv` | every row of every product: `entered`, `reason`, `resid_deg`, `z`, `redundancy` (0 for a pair in no loop, near 1 for one the network fixes) |
| `datum_run.json` | the inputs, the options and the totals |

To find a bad pair, take the worst loop of a period (`worst_loop_sites` in
`datum_periods.csv`), read its `pairs` in `datum_loops.csv` and look them
up in `datum_pairs_period.csv`: a bad pair has a large |z| at a
`redundancy` well above 0 and shows in every loop it closes.
