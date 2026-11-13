# Inter-site tensors and the network datum

This page covers the transfer functions between two sites: the telluric
tensor (the electric field of one site on that of another) and the magnetic
tensor (the same for the horizontal magnetic field). It gives the scripts
that estimate them, what their products hold, and the network datum, which
turns the pair products into one potential per site.

## Estimating a tensor: `process_intersite.py`

```text
scripts/process_intersite.py <survey.yaml> <local> <base> --kind telluric|magnetic (--remote SITE [--remote-channels hx,hy|ex,ey] | --remote-stack E|H [--exclude S1,S2] [--min-overlap-hours H] [--stack-plain | --stack-reject-factor F] [--stack-min-members N] [--stack-method mean|median]) [start] [end] [--min-period S] [--tag TAG] [--out-dir DIR] [--no-filters] [--dry-run]
scripts/process_intersite.py <survey.yaml> <local> [start] [end] --kind telluric --base-stack E (--remote SITE | --remote-stack H [--remote-exclude S3,S4]) [--exclude S1,S2] [--window-members-constant | --allow-member-change] [--screen-polarity flag|drop] [--allow-shared-members] ...
scripts/process_intersite.py <survey.yaml> <local> [start] [end] --kind magnetic --base-stack H (--remote SITE [--remote-channels hx,hy|ex,ey] | --remote-stack H|E [--remote-exclude S3,S4]) [--exclude S1,S2] ...
scripts/process_intersite.py <survey.yaml> <local> [<base>] [start] [end] --kind telluric|magnetic --stack NAME [--stack NAME] [--remote SITE [--remote-channels hx,hy|ex,ey]] [--allow-shared-members] [--min-period S] [--tag TAG] [--out-dir DIR] [--no-filters] [--dry-run]
```

A base recipe takes no `<base>`, a reference recipe no `--remote`.

Inter-site transfer function of a local on a base, the native interim estimator (`mt_workbench.intersite`; aurora through a virtual pair station is the production path to come): the telluric tensor T (`--kind telluric`, E_local = T E_base) or the magnetic tensor M (`--kind magnetic`, H_local = M H_base) per band of the survey's band scheme, each channel calibrated through its own filter chain, Huber reweighting referenced to a third site (`--remote SITE`, its hx, hy or `--remote-channels ex,ey`) or to the stack of every other site's E or H covering the window by `--min-overlap-hours` (12 h; the local, the base and `--exclude` left out), formed per band from the members' calibrated spectra: each member channel divided by the square root of its median band power, a member's window left out where its normalised power exceeds `--stack-reject-factor` (25) times the median over the members in that window (a natural event raises every member and is kept, one member's fault or burst is not; it needs three members or more to act), a window keeping fewer than `--stack-min-members` (2) left out of the band, and each member's scale and rejected fraction per band and the windows left out recorded in the sidecar and the `.h5`.

- `--stack-plain` takes the time-domain stack in its place (each member divided by its RMS over the window, then the plain mean)
- errors from a 20-slice jackknife over time
- the local or the base as the reference is refused (exit 2), and so is a workspace archive with no survey.yaml entry such as a `build_stack.py` stack, whose members cannot be checked against the pair
- writes `<local>_te-<base>_rr-<remote>` (`_hm-` for the magnetic tensor) `.csv`, `.json` sidecar, `.h5` (plain HDF5 arrays) and `.png` under `<workspace>/tf` or `--out-dir`, no EDI or XML
- prints and records the timing check (arg(det)/2 at the three shortest periods, the delay of a phase linear in frequency)
- `--dry-run` prints the resolution, the stack's form and members and the sites left out
- `--base-stack E` makes the band stack of the live sites' ex, ey the inputs instead of a named base (E_local = T E_stack, the local always left out, the positionals after the local then start and end, stem `<local>_te-stackE_rr-<remote>`), and `--base-stack H` the band stack of their hx, hy with `--kind magnetic` (H_local = M H_stack, reference a third site's H or E or a stack of either, stem `<local>_hm-stackH_rr-<remote>`; E with magnetic and H with telluric are refused)
- with a reference stack as well, `--remote-exclude` takes the place of `--exclude` for the reference stack so that the two stacks are built from different sites
- on the stack the telluric and magnetic tensors are in each band's normalised units (|T|, |M| not field ratios; phases and arg(det)/2 unaffected; `stack_scale_rms` per band in the record): a window in which a member's record starts or ends is refused (`--window-members-constant`, the default; `--allow-member-change` runs it and records the changes), a member channel whose median correlation with the other members over the 1-100 s bands is negative is flagged (`--screen-polarity flag`) or left out (`drop`), a reference sharing a site with the base stack is refused unless `--allow-shared-members`, `--stack-plain` is refused, and the sidecar's `base_stack` block records the members with their per-band scale and rejected fraction, the windows and sites left out, the window, the changes, the polarity screen and the shared sites
- `--stack-method median` takes the median of the kept members' real and imaginary parts per band in place of their mean (two members kept give the mean; stem `stackEmed` or `stackHmed`; every band stack block of the sidecar records its method)
- `--stack NAME` takes a band recipe of the survey's `stacks.yaml` (`use: base` is the base stack, `use: reference` the reference; given twice, one of each), whose members, window (start and end on the command line win), overlap, reject factor, min members, method and, for a base, polarity screen and membership rule are the run's
- the options a recipe declares and `--base-stack`, `--remote-stack` and `--stack-plain` beside it are refused (exit 2), as are a time recipe, a `use_filters` that is not the run's and a local at another rate than the recipe's
- the sidecar records the recipe's name, hash and text and the stem carries the recipe's name

### What a run estimates and writes

`scripts/process_intersite.py` estimates
the telluric tensor T (E_local = T E_base) or the horizontal magnetic tensor
M (H_local = M H_base) between two concurrent sites with the native
estimator of `mt_workbench.intersite`, an interim tool beside aurora. The telluric and magnetic tensors
are dimensionless once each channel is divided by its own filter chain
(E in mV/km, H in nT), and they share the impedances' periods (the survey's
band scheme). Each run of a continuous site is calibrated with its own
chain, as aurora does it: where a channel's chain changes between runs (a
gain change, a new dipole), the windows on each side take their own run's
response and a window across the change is left out. A burst site takes the
chain of its first burst and refuses a burst listing other filters. The
products in `<workspace>/tf` share the stem
`<local>_te-<base>_rr-<remote>[_<tag>]` (`_hm-` for the magnetic tensor; `<remote>` is the
reference site, `<site>-E` for its electrics, or `stackE`/`stackH`): a
`.csv` with one row per period (the four complex elements and their
jackknife errors, det, |det| and arg(det)/2 with errors, |T_eff|, the largest
element of the tensor minus the identity, the coherences, the windows, the
flags), a `.json` sidecar in process_rr's form (kind, tensor, local,
base_site, the reference and the stack's members, window, archives, the
filters each calibration removed, band scheme, estimator, `masks`, `frames`,
`flags`, `timing_check`, versions), a `.h5` holding the same arrays in plain
HDF5 (mt_metadata's TF object would label a 2 x 2 on ex, ey an impedance)
and a `.png`. No EDI or XML is written, so merge_best, Geotools and the
quality score never read a telluric or magnetic tensor as Z. The phases follow numpy's FFT: a
local lagging its base by tau shows -360 f tau degrees, and the timing check
fits that line over the shortest decade of periods, at each band's frequency
weighted by its harmonics' cross power and with each band's phase on the
branch of the best line of a scan over delays, so that a delay of tens of ms
is followed through its wraps, since a clock offset between loggers is the
first thing that mimics an IP phase (10 ms is 3.6 deg at 1 s). The scan
reaches 1 s, the loggers' clock tolerance
(`intersite.TIMING_CLOCK_TOLERANCE_S`), and half the bands' alias period. A
best line at that bound, or band phases that make no line (a weak fit: a
resultant under 0.97, observed or allowed by the band errors), is printed as
"not determined" with the reason, and the sidecar's fit values are then
null. An offset of whole seconds is read with `scripts/timing_qc.py`.

### Rows, coherences and flags

Every band of the survey's layout is a row of the CSV, so the products of
one survey hold the same periods: a band the record could not form (too
few windows on its level, or none of its harmonics) has 0 windows and NaN in its tensor, errors and
arg(det)/2. The coherences are of each output and each input on the
reference: `coh_out_unweighted_x/y` and `coh_in_unweighted_x/y` with every
sample weighted 1, `coh_out_weighted_x/y` under each row's final Huber
weights, and `frac_downweighted_x/y`, the fraction of samples the Huber
weights took below 1. On bursty electrics the weighted value describes the
data the estimate used; the plain one can read near zero where the telluric tensor is well
determined. Five flag columns mark a period and never remove it:
`flag_not_estimated` (an element is not finite), `flag_few_groups` (fewer
than 5 of the 20 jackknife slices hold a solution), `flag_low_coherence`
(the weighted output coherence of either row under 0.1),
`flag_off_diagonal` (|T_xy T_yx| > |T_xx T_yy|: one site's electric
channels exchanged, or a turn of more than 45 deg between the two sites'
layouts) and `flag_re_det_negative` (Re det < 0); the last four mark
estimated rows only. The sidecar's `flags`
block gives each flag's rule, its limit and the number of rows it marks; `frames`
gives the local's and the base's azimuth_ex, azimuth_ey, layout_north and
declination from survey.yaml, recorded and not applied (the tensor stays in
each site's channels as recorded); `masks` gives each site's entries applied
and left out and the band windows they cover.

### Masks

masks.yaml is applied to the windows of an inter-site run: a window holding
a sample inside an entry is left out of the bands the entry covers. The local and the base take their entries of
scope `local` or `both` (the base's channels are inputs of the tensor, as a
local's are), and the reference takes those of scope `both` or `remote`. An
entry naming none of the channels read from its site is left out, and one
that applies cuts the whole window for every element. The members of a
stack take none of their entries.

### A stack as the base

The base need not be one site. With `--base-stack E` the inputs are the
band stack of the ex, ey of every site live through the window (the local
always left out, `--exclude` as for a reference stack), so that
E_local = T E_stack with RR's H as the reference, and every site of a
leap-frog survey can be tied to one continuous regional E. The telluric tensor is then the local relative to the mean of that window's members, so a product must
hold one mix of members: a window in which a member's record starts or
ends is refused (one product per constant-membership epoch), a member
whose E correlates negatively with the others over 1-100 s (a reversed
dipole) is flagged or left out, and a reference sharing a site with the
stack is refused, since that site's noise would sit in both the inputs and
the reference. A start or end within 60 s of the window's edges, or a gap
of 60 s or less, is no change (`intersite.MEMBER_EDGE_S`), and the base
stack's members are chosen by the same rule: over a window shorter than
`--min-overlap-hours`, a site joins when its record, with such gaps
bridged, starts no later than 60 s after the window's start and ends no
earlier than 60 s before its end. A reference stack over such a window
needs the whole window less one sample. The stem reads
`<local>_te-stackE_rr-<remote>`, the sidecar's `base_site` is null, and its
`base_stack` block holds what ties the products of different epochs
together afterwards: the members, each one's scale and rejected fraction
per band, and the polarity screen.

Where the electrics are lost, `--base-stack H` with `--kind magnetic` does the same for the magnetic tensor: H_local = M H_stack on the band stack of the live sites'
hx, hy, with a third site's H or E (`--remote SITE [--remote-channels
ex,ey]`) or a stack of either as the reference, under the same rules (a
reversed coil shows as a negative correlation, as a reversed dipole does);
the stem reads `<local>_hm-stackH_rr-<remote>`. `--base-stack E` with
`--kind magnetic` and `--base-stack H` with `--kind telluric` are refused.
With a reference stack beside the base stack, `--exclude` leaves its sites
out of both unless `--remote-exclude` is given, which then is the reference
stack's own list, so that the two stacks can be built from different sites
and share none. On a stack the tensor is in each band's normalised units:
each member enters over its per-band scale, so |T| and |M| (and the ratio
of elements in different columns) are not field ratios, while the phases,
arg(det)/2, the delay and the ratio of two elements of one column are
unaffected. Each band of the `base_stack` record holds `stack_scale_rms`,
the root mean square of the members' scales per channel, and when the
members are calibrated alike the ratio to a member's field is, column by
column, `M_field[:, r] = M_stack[:, r] / stack_scale_rms[r]` (the same for the telluric tensor).

## One tensor over a Phoenix receiver's whole band: `merge_tensor_bands.py`

```text
scripts/merge_tensor_bands.py <bursts .json> <continuous .json> [--accept-disagreement] [--out-dir DIR]
```

One telluric tensor (or magnetic tensor) over a Phoenix receiver's whole band: a burst product (`G5H G8H --remote G6H`, compact grid) and a continuous one (`G5 G8 --remote G6`, survey `min_period` 4**(22/6)/6000) stitched by band, the burst rows below the first shared band, the continuous from it on.

- exit 2 when a shared band differs by more than 2 combined sigma, the edges do not coincide (the aligned `min_period` printed) or the archives' stamp corrections differ (see [instruments.md](instruments.md), Phoenix)

The two inputs, the burst site and the continuous record, are described in
[instruments.md](instruments.md).

## The network datum: `solve_datum.py`

```text
scripts/solve_datum.py <survey.yaml> --pairs PAIRS_CSV [--out DIR] [--scale-by-closure] [--leave-out-flag NAME ...] [--band LO-HI ...]
```

One potential per site at every period from inter-site pair products (the network datum, `mt_workbench.network`): a weighted least-squares solve of psi(l, b) = phi_l - phi_b per period and connected component, the potentials relative to the component median with a Monte Carlo error, chi2/dof with its 99 % interval, the loop each pair closes and every pair row with its reason.

- refused (exit 2) for two band layouts, mixed tensors, a missing sidecar or CSV, a stack product without `base` and an out folder that exists

### What the solve does

`scripts/solve_datum.py` turns the inter-site pair products of a survey
into one potential per site at every period. Each product gives
psi(l, b) = arg(det T) / 2 with its error per period, and over the network
psi(l, b) = phi_l - phi_b modulo 180 deg; `mt_workbench.network` solves
these equations by weighted least squares, each connected component of
the period's pairs on its own gauge site. The product of record is each
site's potential relative to its component's median, `phi_rel_deg`, with
its error `phi_rel_err_deg`, and the closure (chi2/dof and the loop each
pair closes) shows whether the pair errors describe the misfit.

**The pairs table** is a CSV with one row per product:

| column | |
|---|---|
| `sidecar` | the product's JSON sidecar from process_intersite.py or merge_tensor_bands.py; a relative path is taken against `<workspace>/tf` |
| `use` | optional, true by default; false keeps the product listed but out of the solve, and its rows are counted |
| `note` | optional free text, copied to the run record |
| `base` | only for a product whose base is a stack (sidecar `base_site` null): the node name it takes in the datum |

Products of the same two sites (parts, nights, the reverse direction) are
separate equations. All products must be of one tensor (telluric or magnetic) and one band
layout: periods closer than 10 % but more than relative 1e-9 apart are
refused (exit 2), naming the products of each layout.

The tables go into `<workspace>/datum/<pairs table stem>/` (or `--out`), a
folder that must not exist yet: a second run into it is refused, so a run
never overwrites another. The script prints one line per period: rows
entered of rows present, how many entered rows carry a flag, the component
sizes, chi2/dof and whether it lies inside its 99 % interval, the worst
loop, and any gauge tie or unconverged component.

**Reading the tables.**

- `datum_sites_period.csv`, one row per period and site. `phi_rel_deg` and
  `phi_rel_err_deg` are the product. `phi_deg` and `phi_err_deg` are
  relative to the component's gauge (the gauge 0 +- 0): its site with the
  most entered equations, then the most partners, over the whole run (the
  `gauge_rank` table of the run record). When the next site has the same
  two counts, `phi_deg` and `phi_err_deg` are NaN and `datum_periods.csv`
  names the tied sites in `gauge_tie`. `phi_rel_err_deg` comes from 4000 draws (seeded by
  the period); the middle site of a component with an odd number of
  well-separated sites is the median in every draw, so its error is 0.
  `solved` is false for a site with no entered equation at that period.
- `datum_periods.csv`, one row per period and component plus an `all` row
  per period. `chi2_dof` is near 1 when the pair errors describe the
  scatter; `chi2_dof_lo99` and `chi2_dof_hi99` bound the 99 % interval for
  its dof. Above it the misfit is larger than the errors; below it the
  errors are larger than the misfit, or equations with errors over 52 deg
  pull it down (`n_err_over_52`). `phi_err_deg` is the formal error given
  the pair errors, and outside the interval it is not a measured error.
  `n_not_estimated`, `n_no_error` and `n_left_out` count the rows that did
  not enter, `n_<flag>` the entered rows carrying each flag, and
  `n_far_from_centre` the sites more than 60 deg from the component's
  centre, where the median depends on where the circle is cut. dof 0 (a
  tree) means the closure is not tested.
- `datum_loops.csv`: every pair outside the start tree (the most precise
  spanning tree) closes one loop with the tree path between its ends.
  `closure_deg` is the signed sum of psi round the loop, `sigma_deg` the
  root sum of squares of its errors and `z` their ratio; `kind` is
  `repeat` for two products of one pair.
- `datum_pairs_period.csv`, every row of every product,
  with `entered` and `reason` (`not_estimated`, `no_error`, `use=false`,
  `flag:<name>`, or empty when it entered), the product's flags, `resid_deg`,
  `z` (residual over error) and `redundancy`, the share of the pair's
  error the rest of the network checks: 0 for a pair in no loop, near 1 for
  a pair the network fixes. To find a bad pair from a bad loop, take the
  loop's `pairs` at that period and look them up here: a bad pair has a
  large |z| at a redundancy well above 0, and it shows in every loop it
  closes.
- `datum_run.json`: the inputs with their SHA-256, each flag's rule from the
  sidecars, the options, the period lattice, the gauge ranking, the totals
  (rows by reason, and in `entered_rows_flagged` the entered rows carrying
  each flag, the sum of its `n_<flag>` over the periods), the gauge ties,
  the components not converged, what `phi_err_deg` means, the version and
  commit, and the start and end times.

**Options.** Rows leave the solve only when the caller asks:
`--leave-out-flag NAME` (repeatable) leaves out the rows that carry that
flag column of the products (such as `flag_off_diagonal`), and `use` false a
whole product;
both write the reason and are counted in `n_left_out`. Errors enter as the
products wrote them. `--scale-by-closure` multiplies `phi_err_deg` of a
component whose sqrt(chi2/dof) (`scale`, always written) is over 1 by it,
recomputes `phi_rel_err_deg` with the covariance times scale^2, and marks
those rows `errors_scaled`; chi2, `z` and the loops keep the errors as
entered. `--band LO-HI` (seconds, repeatable) writes `datum_bands.csv`, the
weighted circular mean of each site's `phi_rel_deg` over the band with two
errors (`err_independent_deg` if the periods are independent,
`err_correlated_deg` if their errors are fully correlated): a reading of
the per-period table, never an input to the solve.
