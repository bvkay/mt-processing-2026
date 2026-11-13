# -*- coding: utf-8 -*-
"""
Inter-site transfer function of one local/base pair: the telluric tensor T or the magnetic tensor M

Estimates T (E_local = T E_base, `--kind telluric`) or M (H_local =
M H_base, `--kind magnetic`) per band of the survey's band scheme with the
native estimator of `mt_workbench.intersite`: calibrated spectra, Huber
reweighting referenced to a third site's channels or to a stack of the
survey's other sites, and errors from a 20-slice jackknife over time. It is
an interim tool beside aurora, whose route through a virtual pair station is
the production path to come.

The reference is `--remote SITE`, its hx, hy unless `--remote-channels
ex,ey` asks for its electrics, or `--remote-stack E|H`, the ex, ey or hx, hy
of every site of survey.yaml at the pair's sample rate whose archive covers
the window by at least `--min-overlap-hours` (12 h, or the whole window when
it is shorter), leaving out the local, the base and `--exclude`. The
stack is formed per band from the members' spectra
(`mt_workbench.intersite.band_stack`; The stack in that module's docstring
says why): each member channel, calibrated through its own filter chain, is
divided by the square root of its median band power, a member's window is
left out where its normalised power exceeds `--stack-reject-factor` (25)
times the median over the members in that window, and a window keeping
fewer than `--stack-min-members` (2) is left out of the band. `--stack-plain`
forms the plain stack instead (`mt_workbench.intersite.stack_channels`):
each member divided by its RMS over the window in the time domain, then the
plain mean. The form, the threshold, the members' scales and rejected fractions
per band and the windows each band left out go into the sidecar. The
reference may not be
the local or the base: the base's own channels would bias the estimate low
(errors in variables), and the run is refused (exit 2). A `--remote` must be
a site of survey.yaml: a workspace archive with no entry, such as a stack
from build_stack.py, is refused too, since its members cannot be checked
against the local and the base.

`--base-stack E` makes the band stack of the live sites' ex, ey the base
(the inputs) instead of a named site: E_local = T E_stack, with the
reference as above (`--remote SITE` or `--remote-stack H`). `--base-stack
H` does the same with the live sites' hx, hy for M: H_local = M H_stack,
the reference a third site's H or E (`--remote SITE [--remote-channels
ex,ey]`) or a stack (`--remote-stack H|E`). The stack's field follows the
tensor: `--base-stack E` goes with `--kind telluric` and `--base-stack H`
with `--kind magnetic`, and the other pairings are refused. No positional
base is given, so the positionals after the local are start and end, and a
site named there is refused. The members are chosen and stacked as a
reference stack's are (the same `--exclude`, `--min-overlap-hours`,
`--stack-reject-factor` and `--stack-min-members`), the local always left
out; `--stack-plain` is refused, since the plain stack is formed in the
time domain. With a reference stack as well, `--exclude` leaves its sites
out of both stacks unless `--remote-exclude` is given, which then takes
its place for the reference stack alone, so that the two stacks can be
built from different sites. Three more rules apply to a base stack (The
stack as the base in `mt_workbench.intersite`'s docstring says why):

- Constant membership (`--window-members-constant`, on by default): a
  window in which a member's record starts or ends (60 s from the edges
  and across gaps) is refused, naming the member and the time, so that
  each product holds one mix of members; `--allow-member-change` runs it
  and records the changes.
- Polarity (`--screen-polarity flag`, the default): each member channel's
  correlation with the mean of the other members over the 1-100 s bands
  is computed before the stack is formed, and a member whose median
  correlation is negative (a reversed dipole or coil) is flagged in the
  log and the sidecar; with
  `drop` it is left out of the stack (both channels; the bands are then
  held in memory until the screen is done). The flags need the samples, so
  the dry run names the screen but cannot show them.
- Shared members: a reference that shares a site with the base stack (the
  remote, or a member of a reference stack) is refused unless
  `--allow-shared-members`; the overlap is recorded either way.

The stem then reads `<local>_te-stackE_rr-<remote>[_<tag>]` (T) or
`<local>_hm-stackH_rr-<remote>[_<tag>]` (M), and the sidecar's `base_site`
is null and its `base_stack` block holds the channels, the members with
their per-band scale and rejected fraction, the sites left out (the local
among them), the windows left out, the window, the membership changes,
the polarity screen and the shared sites. On the stack the tensor is in
each band's normalised units (Units on the stack in
`mt_workbench.intersite`'s docstring): |T| and |M| are not field ratios,
while the phases, arg(det) / 2 and the ratio of two elements of one column
are unaffected. Each band of the record holds `stack_scale_rms`, the root
mean square of the members' scales per channel, and column r times
1 / stack_scale_rms[r] is the ratio to a member's field when the members
are calibrated alike; the sidecar's `units` says so.

`--stack-method median` forms a band stack given by flags
(`--remote-stack`, `--base-stack`, both when both are given) as the median
of the kept members' scaled spectra, the real and the imaginary parts
taken apart, in place of their mean (`mt_workbench.intersite.stack_band`;
with two members kept it is their mean); the label in the stem then reads
`stackEmed` or `stackHmed`. Every band stack block of the sidecar records
its `method`, a default run's `mean` included, and the h5 its
`stack_method` or `base_stack_method`.

Recipes. `--stack NAME` takes a stack declared in the survey's stacks.yaml
(`mt_workbench.stacks`; the GUI's Stacks tab writes it): a band recipe of
`use: base` is the base stack, as `--base-stack <field>` makes it, and one
of `use: reference` the reference, as `--remote-stack <field>`; `--stack`
given twice takes one of each. The recipe's members (its rule less its
`exclude`, or its list), minimum overlap, reject factor, minimum members
and method, and for a base its polarity screen and membership rule, are the
run's settings, each stack with its own. Its window is the run's unless
start and end are given, which win; the log then prints the recipe's as
`recipe_window`. The options a recipe declares (`--exclude`,
`--remote-exclude`, `--min-overlap-hours`, `--stack-reject-factor`,
`--stack-min-members`, `--stack-method`, `--screen-polarity`,
`--window-members-constant`, `--allow-member-change`) and the stacks given
by flags (`--base-stack`, `--remote-stack`, `--stack-plain`) are refused
beside a recipe, so that an option never names a different stack depending
on what else is on the line: declare the other stack as a recipe too. Also
refused (exit 2, naming the recipe): a name stacks.yaml does not hold (the
names it holds are listed), an invalid recipe or a stacks.yaml that does not
read, a time recipe (an archive: scripts/build_stack.py --recipe NAME, then
scripts/process_rr.py with NAME as the remote), two recipes of one use, a
recipe whose `use_filters` is not the run's (`--no-filters`), a base recipe
of the field the tensor does not take, a local at another rate than the
recipe's, and a base and a reference recipe whose windows differ. The
sidecar's stack blocks record the recipe's name, hash and canonical text
(`recipe`, `recipe_hash`, `recipe_text`), the h5 its name and hash, and the
stem carries the recipe's name in place of `stackE` or `stackH`
(`<local>_hm-STK_NADOR_H_rr-<remote>`).

Each site is read from its processing archive (the filtered variant when it
declares filters, built on demand as process_rr.py does; the raw archive
with `--no-filters`), and every channel is calibrated through its own filter
chain, so a response that differs between the two sites cannot pass as a
phase. A site whose raw archive is missing is refused: ingest it first
(scripts/ingest_site.py). `start`/`end` (UTC) set the processing window;
without them it is the time the local and the base (and a single remote)
all cover.

Masks. The survey's masks.yaml entries of the local, the base and a named
remote leave out of the spectra every window holding a sample inside them
(`mt_workbench.intersite.band_spectra`). The local and the base take their
entries of scope local or both, the reference those of scope both or
remote (`mt_workbench.intersite.mask_role`); an entry naming none of the
channels read from its site is left out, and one that applies cuts whole
windows for every element. The burst grid places each entry on the bursts
it meets. A stack's members take none of their entries. The log and the
sidecar's `masks` block give each site's entries applied and left out and
the band windows its entries cover, per band and in all.

Products under `<workspace>/tf` (or `--out-dir`), stem
`<local>_te-<base>_rr-<remote>` for T and `<local>_hm-<base>_rr-<remote>` for
M, `<remote>` being the site, `<site>-E` for its electrics, or `stackE` /
`stackH` (`stackEmed` / `stackHmed` for a median, the recipe's name for a
recipe; `<base>` likewise for a base stack), plus `_<tag>` with `--tag`; a
run with the same stem overwrites the last:

- `<stem>.csv`: one row per period, the four complex elements and their
  jackknife errors, det, |det| and arg(det) / 2 with their errors, |T_eff|,
  the largest element of the tensor minus the identity, the coherences and
  the windows used (`mt_workbench.intersite.TensorEstimate.frame`). The
  coherences on the reference are `coh_out_unweighted_x/y` and
  `coh_in_unweighted_x/y` (every sample weighted 1), `coh_out_weighted_x/y`
  (under each row's final Huber weights) and `frac_downweighted_x/y`. Five
  flag columns mark a period and never remove it: `flag_not_estimated`,
  `flag_few_groups`, `flag_low_coherence`, `flag_off_diagonal` and
  `flag_re_det_negative` (`mt_workbench.intersite.TensorEstimate.flags`).
  Every band of the survey's layout has a row: a band the record could not
  form has 0 windows and NaN in its tensor, errors and arg(det) / 2;
- `<stem>.json`: the sidecar, in process_rr.py's form: kind, tensor, local,
  base_site, reference (with the stack's members and the sites left out),
  window, archives with their mtimes, channels and the filters each
  calibration removed, band scheme, estimator, counts, `masks` (each
  site's entries applied and left out), `frames` (each site's azimuths,
  layout north and declination from survey.yaml, recorded and not
  applied), `flags` (each flag's rule, limit and row count),
  `timing_check`, argv, package versions;
- `<stem>.h5`: the same arrays in a plain HDF5 file
  (`mt_workbench.intersite.write_h5`), since mt_metadata's TF object would
  label a 2 x 2 on ex, ey as an impedance; with the band stack its root
  attributes add the stack's form, threshold and minimum members, and its
  per-band record as JSON (`stack_record`);
- `<stem>.png`: magnitude (|M - I| for M) and phase of each element and
  arg(det) / 2 against period with error bars and the timing fit
  (`mt_workbench.intersite.draw_estimate`, which the GUI's View tensors
  tab draws with too): a flagged period has an open marker and each flag
  its own marker in the third panel, and a period not estimated is absent.

No EDI or XML is written: every EDI reader would take T or M for an
impedance.

The timing check (`mt_workbench.intersite.timing_check`) prints arg(det) / 2
at the three shortest periods and the delay tau of a phase linear in
frequency fitted over the shortest decade, phase = a - 360 f tau (tau > 0:
the local lags the base), at each band's cross-power weighted frequency;
the sidecar stores it as `timing_check`. A clock offset between the two
loggers shows here before it can pass as IP. When chi2/dof exceeds 4 the
log says whether the residuals (their RMS weighted by 1 / error^2) are a
small part of the line's turn (a large delay, read as a clock offset) or not
(tau is not a clock offset alone). The delay scan reaches 1 s
(`mt_workbench.intersite.TIMING_CLOCK_TOLERANCE_S`) and half the bands'
alias period; a line at that bound, or band phases that do not make a line,
are printed as not determined with the reason, and the sidecar's fit values
are then null. An offset of whole seconds is read with
scripts/timing_qc.py.

`--dry-run` prints the resolution (sites, channels, archives and their
state, window and samples, the reference, the stack's form and members,
band scheme, stem, expected memory) and exits without reading samples,
building a variant or writing a file. Both stack forms write the same stem
(`stackE`, `stackH`): give `--tag` to keep a plain and a band product side by
side.

Usage:
    python scripts/process_intersite.py <survey.yaml> <local> <base> --kind telluric|magnetic
        (--remote SITE [--remote-channels hx,hy|ex,ey] | --remote-stack E|H [--exclude S1,S2]
        [--min-overlap-hours H] [--stack-plain | --stack-reject-factor F] [--stack-min-members N]
        [--stack-method mean|median]) [start] [end] [--tag TAG] [--out-dir DIR] [--no-filters] [--dry-run]
    python scripts/process_intersite.py <survey.yaml> <local> [start] [end] --kind telluric --base-stack E
        (--remote SITE [--remote-channels hx,hy] | --remote-stack H [--remote-exclude S3,S4]) [--exclude S1,S2]
        [--min-overlap-hours H] [--stack-reject-factor F] [--stack-min-members N]
        [--window-members-constant | --allow-member-change] [--screen-polarity flag|drop]
        [--allow-shared-members] [--tag TAG] [--out-dir DIR] [--no-filters] [--dry-run]
    python scripts/process_intersite.py <survey.yaml> <local> [start] [end] --kind magnetic --base-stack H
        (--remote SITE [--remote-channels hx,hy|ex,ey] | --remote-stack H|E [--remote-exclude S3,S4]) ...
    python scripts/process_intersite.py <survey.yaml> <local> [<base>] [start] [end] --kind telluric|magnetic
        --stack NAME [--stack NAME] [--remote SITE [--remote-channels hx,hy|ex,ey]] [--allow-shared-members]
        [--min-period S] [--tag TAG] [--out-dir DIR] [--no-filters] [--dry-run]
    (a base recipe takes no <base>; a reference recipe takes no --remote)

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

import argparse
import datetime as dt
import inspect
import json
import math
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from loguru import logger  # noqa: E402

from mt_workbench import intersite, stacks  # noqa: E402
from mt_workbench.bands import build_band_scheme, lowest_harmonic, site_min_period  # noqa: E402
from mt_workbench.crosspower import _Clock  # noqa: E402
from mt_workbench.ingest import default_archive_path, processing_archive  # noqa: E402
from mt_workbench.masks import SCOPES_OF_ROLE, load_masks, masks_path  # noqa: E402
from mt_workbench.phoenix import warn_without_h_polarity  # noqa: E402
from mt_workbench.survey import Survey  # noqa: E402
from process_rr import (_archive_info, _declared_filters, _utc, _utc_text, archive_status, clean_tag,  # noqa: E402
                        recorded_site_folders, versions, write_sidecar)

BAND_KEYS = ("min_period", "max_period", "periods_per_decade", "notch_frequencies", "window", "min_bin")
PREFIXES = {"local": "l_", "base": "b_", "reference": "r_"}  # channel keys in the estimator: l_ex, b_ex, r_hx ...
BYTES_PER_SAMPLE = 4 * 6 * 1.5 + 8  # six float32 channels, the decimation copies, one float64 read at a time


def bytes_per_sample(channels: int) -> float:
    """Return the expected bytes per sample with `channels` float32 channels (`BYTES_PER_SAMPLE` for six)."""
    return 4 * channels * 1.5 + 8


class Refused(ValueError):
    """A run that cannot go ahead as asked (exit 2)."""


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser of process_intersite.py."""
    p = argparse.ArgumentParser(
        prog="process_intersite.py",
        description=next(line for line in __doc__.strip().splitlines() if line.strip()),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("survey_yaml")
    p.add_argument("local")
    p.add_argument("base", nargs="?", default=None,
                   help="the base site; not given with --base-stack, where the positionals after the local are "
                        "start and end")
    p.add_argument("start", nargs="?", default=None, help='UTC, e.g. "2022-02-14 06:00"')
    p.add_argument("end", nargs="?", default=None, help="UTC")
    p.add_argument("--kind", choices=tuple(intersite.KINDS), required=True,
                   help="telluric: T, outputs the local's ex, ey, inputs the base's; magnetic: M, on hx, hy")
    ref = p.add_mutually_exclusive_group()  # or a reference recipe (--stack); resolve() wants exactly one
    ref.add_argument("--remote", default=None, metavar="SITE", help="a third site as the reference")
    ref.add_argument("--remote-stack", choices=tuple(intersite.FIELDS), default=None,
                     help="the stack of every other site's ex, ey (E) or hx, hy (H) as the reference")
    p.add_argument("--remote-channels", default=None, metavar="LIST",
                   help="with --remote: hx,hy (the default) or ex,ey")
    p.add_argument("--exclude", default=None, metavar="LIST",
                   help="with --remote-stack or --base-stack: sites left out of the stack (of both stacks unless "
                        "--remote-exclude is given), comma list")
    p.add_argument("--remote-exclude", default=None, metavar="LIST",
                   help="with --remote-stack and --base-stack: sites left out of the reference stack, in place of "
                        "--exclude there, so that the two stacks can be built from different sites")
    p.add_argument("--min-overlap-hours", type=float, default=None, metavar="H",
                   help=f"with --remote-stack: the overlap a member needs with the window (in use: "
                        f"{intersite.MIN_OVERLAP_HOURS:g}, or the whole window when shorter)")
    p.add_argument("--stack-plain", action="store_true",
                   help="with --remote-stack: the earlier time-domain stack (each member over its RMS over the "
                        "window, plain mean) instead of the band stack")
    p.add_argument("--stack-reject-factor", type=float, default=None, metavar="F",
                   help=f"with the band stack: a member's window over F times the array level is left out (in "
                        f"use: {intersite.STACK_REJECT_FACTOR:g})")
    p.add_argument("--stack-min-members", type=int, default=None, metavar="N",
                   help=f"with the band stack: kept members a window needs (in use: {intersite.STACK_MIN_MEMBERS})")
    p.add_argument("--stack-method", choices=intersite.STACK_METHODS, default=None,
                   help="with --remote-stack or --base-stack (the band stack): how the kept members are combined "
                        "per window, mean (in use) or median (of the real and imaginary parts apart)")
    p.add_argument("--stack", action="append", default=None, metavar="NAME",
                   help="a band recipe of the survey's stacks.yaml: use base makes it the base stack, use reference "
                        "the reference; give it twice for one of each. Its members, window and stack options are "
                        "the run's, and the options it declares are refused beside it")
    p.add_argument("--base-stack", choices=tuple(intersite.FIELDS), default=None,
                   help="the band stack of the live sites' ex, ey (E, with --kind telluric) or hx, hy (H, with "
                        "--kind magnetic) as the base (the inputs), the local left out; no named base")
    members = p.add_mutually_exclusive_group()
    members.add_argument("--window-members-constant", action="store_true", default=None,
                         help="with --base-stack (on by default there): refuse a window in which a member's record "
                              "starts or ends")
    members.add_argument("--allow-member-change", action="store_true",
                         help="with --base-stack: run a window in which the membership changes, recording the "
                              "changes")
    p.add_argument("--screen-polarity", choices=("flag", "drop"), default=None,
                   help="with --base-stack: flag (in use) or drop a member whose median correlation with the other "
                        "members over the 1-100 s bands is negative")
    p.add_argument("--allow-shared-members", action="store_true",
                   help="with --base-stack: accept a reference sharing a site with the base stack (recorded)")
    p.add_argument("--min-period", type=float, default=None, metavar="S",
                   help="the shortest period in s (in use: the survey's processing: min_period, or for a site "
                        "faster than the survey's rate the shortest of the survey's layout at or above 4 / rate, "
                        "mt_workbench.bands.site_min_period)")
    p.add_argument("--tag", default=None, help="suffix appended to the output stem")
    p.add_argument("--out-dir", default=None, metavar="DIR", help="where the products go (in use: <workspace>/tf)")
    p.add_argument("--no-filters", action="store_true", help="read the raw archives, not the filtered variants")
    p.add_argument("--dry-run", action="store_true", help="print what this run resolved to and exit, reading nothing")
    return p


def _ts(ns: int):
    """Return ns since the epoch as a UTC Timestamp."""
    return pd.Timestamp(int(ns), unit="ns", tz="UTC")


def _text_ns(ns) -> str:
    """Format ns since the epoch as 2023-09-22T12:21:22Z."""
    return _utc_text(_ts(ns))


def parse_list(text: str | None) -> list[str]:
    """Parse a comma list: 'A, B' -> ['A', 'B']; None -> []."""
    return [part.strip() for part in str(text or "").split(",") if part.strip()]


def reference_channels(text: str | None) -> tuple[str, str]:
    """Return the remote's channels from --remote-channels: hx,hy (None) or ex,ey.

    Raises:
        Refused: For any other list.
    """
    if text is None:
        return intersite.FIELDS["H"]
    chans = tuple(c.lower() for c in parse_list(text))
    for pair in intersite.FIELDS.values():
        if chans == pair:
            return pair
    raise Refused(f"--remote-channels takes hx,hy or ex,ey; given {text!r}")


def stem_of(local: str, base: str, kind: str, ref_label: str, tag=None) -> str:
    """Build the product stem <local>_<te|hm>-<base>_rr-<ref_label>[_<tag>]."""
    stem = f"{local}_{intersite.STEM_CODES[kind]}-{base}_rr-{ref_label}"
    suffix = clean_tag(tag)
    return f"{stem}_{suffix}" if suffix else stem


def _site_runs(survey: Survey, site: str, roles, label: str) -> tuple[Path, list]:
    """Return a site's raw archive and its runs holding `roles`.

    Raises:
        Refused: When the site has no survey.yaml entry, no raw archive, or no run with the roles.
    """
    if site not in survey.site_names():
        raise Refused(f"{site} ({label}) has no entry in survey.yaml: check the name, or add the site")
    raw = default_archive_path(survey, site)
    if not raw.exists():
        raise Refused(f"{site} ({label}): no archive at {raw}: ingest it first "
                      f"(scripts/ingest_site.py <survey.yaml> {site})")
    runs = intersite.archive_runs(raw, site, roles)
    if not runs:
        raise Refused(f"{site} ({label}): no run of {raw.name} holds {', '.join(roles)}")
    return raw, runs


def _scheme_kwargs(survey: Survey) -> dict:
    """Return the survey's `processing:` block filled out from build_band_scheme's defaults."""
    kwargs = dict(survey.processing)
    defaults = {n: p.default for n, p in inspect.signature(build_band_scheme).parameters.items()}
    for key in BAND_KEYS:
        kwargs.setdefault(key, defaults[key])
    return kwargs


def positionals(args, survey: Survey, base_given: str | None = None) -> tuple:
    """Return (base, start, end) from the positionals after the local.

    Without a base stack they are base [start] [end]. With one
    (--base-stack, or a base recipe) no base is given, so the two after the
    local are start and end.

    Args:
        args (argparse.Namespace): Parsed arguments.
        survey (Survey): The survey.
        base_given (str, optional): How the base stack was given, for the
            messages ("--base-stack E", "--stack STK_B"); None takes
            --base-stack from `args`.

    Raises:
        Refused: Without a base stack, no base; with one, a site named
            where the start goes, three positionals, or one that is not a
            time.
    """
    if base_given is None and args.base_stack is not None:
        base_given = f"--base-stack {args.base_stack}"
    if base_given is None:
        if args.base is None:
            raise Refused("give the base site, or --base-stack E|H (or --stack NAME of a use: base recipe)")
        return args.base, args.start, args.end
    if args.base is not None and args.base in survey.site_names():
        raise Refused(f"{args.base} is a site: {base_given} is the base, so a named base goes without it")
    if args.end is not None:
        raise Refused(f"with {base_given.split()[0]} the positionals after the local are start and end; three were "
                      f"given")
    for value in (args.base, args.start):
        if value is not None:
            try:
                _utc(value)
            except (ValueError, TypeError):
                raise Refused(f"{value!r} is not a time: with {base_given.split()[0]} the positionals after the "
                              f"local are start and end") from None
    return None, args.base, args.start


# the band stack's rule per method, as products record it; the mean's text is the one recorded before the median
STACK_RULES = {m: stacks.METHODS[f"band_{m}"].rule for m in intersite.STACK_METHODS}
STACK_RULE = STACK_RULES["mean"]
STACK_UNITS_OF = {"mean": intersite.STACK_UNITS, "median": intersite.STACK_UNITS_MEDIAN}  # the units text per method
SCALE_UNITS = ("the band spectra as the estimator forms them: the calibrated channel (E in mV/km, H in nT) per "
               "harmonic of the Hann-tapered window's FFT")
# the options a recipe declares, refused beside one: (flag, attribute of the parsed arguments, the recipe's key)
DECLARED_OPTIONS = (("--exclude", "exclude", "exclude"), ("--remote-exclude", "remote_exclude", "exclude"),
                    ("--min-overlap-hours", "min_overlap_hours", "min_overlap_hours"),
                    ("--stack-reject-factor", "stack_reject_factor", "reject_factor"),
                    ("--stack-min-members", "stack_min_members", "min_members"),
                    ("--stack-method", "stack_method", "method"),
                    ("--screen-polarity", "screen_polarity", "screen_polarity"),
                    ("--window-members-constant", "window_members_constant", "member_change"),
                    ("--allow-member-change", "allow_member_change", "member_change"))


def stack_recipes(args, survey: Survey) -> dict:
    """Return the recipes `--stack` names, by use, refusing what cannot go with them.

    Args:
        args (argparse.Namespace): Parsed arguments.
        survey (Survey): The survey.

    Returns:
        dict: ``{"base": Recipe or None, "reference": Recipe or None}``;
        both None without `--stack`.

    Raises:
        Refused: Naming the recipe, for a name stacks.yaml does not hold, an
            invalid recipe or a stacks.yaml that does not read; a time
            recipe; two recipes of one use; a recipe beside a stack given
            by flags (--base-stack, --remote-stack, --stack-plain) or beside
            an option the recipe declares (`DECLARED_OPTIONS`); a recipe
            whose use_filters is not the run's; and a base and a reference
            recipe whose windows differ.
    """
    out = {"base": None, "reference": None}
    names = list(args.stack or [])
    if not names:
        return out
    for name in names:
        try:
            recipe = stacks.load_recipe(survey, name)
        except stacks.StacksError as exc:
            raise Refused(f"--stack {name}: {exc}") from None
        except OSError as exc:
            raise Refused(f"--stack {name}: {stacks.stacks_path(survey)} cannot be read ({exc})") from None
        if recipe.engine != "band":
            raise Refused(f"--stack {name}: a time recipe ({recipe.method}) is an archive, not a band stack: build "
                          f"it with scripts/build_stack.py <survey.yaml> --recipe {name}, then run "
                          f"scripts/process_rr.py with {name} as the remote")
        if out[recipe.use] is not None:
            raise Refused(f"--stack {out[recipe.use].name} and --stack {name} are both use: {recipe.use} recipes; a "
                          f"run takes one base recipe and one reference recipe at most")
        out[recipe.use] = recipe
    given = " ".join(f"--stack {name}" for name in names)
    flags = [flag for flag, on in (("--base-stack", args.base_stack is not None),
                                   ("--remote-stack", args.remote_stack is not None),
                                   ("--stack-plain", bool(args.stack_plain))) if on]
    if flags:
        raise Refused(f"{given} with {', '.join(flags)}: a recipe and a stack given by flags are not mixed in one "
                      f"run, since an option would then name a different stack depending on what else is on the "
                      f"line; declare the other stack as a recipe too")
    for flag, attr, key in DECLARED_OPTIONS:
        if getattr(args, attr) not in (None, False):
            raise Refused(f"{given}: {flag} is declared by the recipe ({key} in stacks.yaml); change the recipe, "
                          f"not the command line")
    use_filters = not args.no_filters
    for recipe in (r for r in out.values() if r is not None):
        if recipe.use_filters != use_filters:
            run = "reads the raw archives (--no-filters)" if args.no_filters else "reads the filtered variants"
            raise Refused(f"--stack {recipe.name}: the recipe declares use_filters: "
                          f"{str(recipe.use_filters).lower()} and the run {run}; give --no-filters exactly when the "
                          f"recipe says false")
    base, ref = out["base"], out["reference"]
    if base is not None and ref is not None and None not in (base.window_ns, ref.window_ns) \
            and base.window_ns != ref.window_ns:
        raise Refused(f"--stack {base.name} and --stack {ref.name} declare different windows ({_window_text(base)} "
                      f"and {_window_text(ref)}); a run has one window: make them equal, or leave one out")
    return out


def _window_text(recipe) -> str:
    """Format a recipe's window as '<start> to <end>' in UTC."""
    lo, hi = recipe.window_ns
    return f"{_text_ns(lo)} to {_text_ns(hi)}"


def recipe_members(recipe, survey: Survey, lo: int, hi: int, local: str, base: str | None,
                   edge_s: float | None = None) -> tuple[list, list]:
    """Return a band recipe's members and the sites it leaves out (`mt_workbench.stacks.resolve_members`).

    `edge_s` is passed to `mt_workbench.intersite.select_stack`: the base
    recipe takes `MEMBER_EDGE_S`, a reference recipe None.

    Raises:
        Refused: For what resolve_members refuses (a local or base at
            another rate than the recipe's), naming the recipe.
    """
    try:
        return stacks.resolve_members(recipe, survey, (lo, hi), local, base, edge_s=edge_s)
    except stacks.StacksError as exc:
        raise Refused(f"--stack {recipe.name}: {exc}") from None


def recipe_record(recipe) -> dict:
    """Return what a stack block records of its recipe: ``recipe``, ``recipe_hash`` and ``recipe_text``."""
    record = stacks.provenance(recipe)
    return {key: record[key] for key in ("recipe", "recipe_hash", "recipe_text")}


def resolve(args, started) -> dict:
    """Resolve everything the run needs, reading archive metadata only.

    Refuses (`Refused`, exit 2): a local equal to the base; a reference
    that is the local or the base; options of the other reference form; a
    site without a survey.yaml entry or a raw archive, the remote included
    (a workspace archive with no entry, such as a stack from
    build_stack.py, is refused, since nothing says which sites it holds
    and so whether it carries the local's or the base's channels: use
    `--remote-stack`, whose members are chosen here and recorded); sample
    rates that differ; a window the sites do not all cover; a stack with
    no member. With `--base-stack`: a named base, `--stack-plain`, a field
    that is not the tensor's (E with telluric, H with magnetic), a base
    stack whose membership changes inside the window (unless
    `--allow-member-change`), and a reference sharing a site with the base
    stack (unless `--allow-shared-members`); the base-stack options without
    `--base-stack`; and `--remote-exclude` without both stacks. With
    `--stack`: what `stack_recipes` refuses, a base recipe with no
    reference, a second reference beside a reference recipe, and a local at
    another rate than a recipe's.

    Args:
        args (argparse.Namespace): Parsed arguments.
        started (datetime.datetime): Start of the run.

    Returns:
        dict: The resolution, printed by `print_resolution`.
    """
    if not args.stack and args.remote is None and args.remote_stack is None:
        raise Refused("give the reference: --remote SITE, --remote-stack E|H, or --stack NAME of a use: reference "
                      "recipe")
    survey = Survey.from_yaml(args.survey_yaml)
    kind = args.kind
    roles = intersite.KINDS[kind]
    local = args.local
    recipes = stack_recipes(args, survey)
    base_recipe, ref_recipe = recipes["base"], recipes["reference"]
    if ref_recipe is None and args.remote is None and args.remote_stack is None:
        # the check above passes any --stack; a base recipe alone leaves the run without a reference
        raise Refused(f"--stack {base_recipe.name} is a base recipe and the run has no reference: give --remote "
                      f"SITE, --remote-stack E|H, or --stack NAME of a use: reference recipe")
    base_stack = base_recipe.field if base_recipe is not None else args.base_stack
    base_given = f"--stack {base_recipe.name}" if base_recipe is not None else None
    base, start, end = positionals(args, survey, base_given)
    if local == base:
        raise Refused(f"the local and the base are both {local}")
    stack = ref_recipe.field if ref_recipe is not None else args.remote_stack
    if ref_recipe is not None and args.remote is not None:
        raise Refused(f"--stack {ref_recipe.name} is the reference (use: reference) and --remote {args.remote} "
                      f"another: give one reference")
    stack_options = (args.stack_plain or args.stack_reject_factor is not None
                     or args.stack_min_members is not None)
    if stack is None and base_stack is None and (args.exclude is not None or args.min_overlap_hours is not None
                                                 or stack_options):
        raise Refused("--exclude, --min-overlap-hours, --stack-plain, --stack-reject-factor and --stack-min-members "
                      "go with --remote-stack or --base-stack")
    if stack is None and base_stack is None and args.stack_method is not None:
        raise Refused("--stack-method goes with --remote-stack or --base-stack (the band stack)")
    if base_stack is None and (args.window_members_constant or args.allow_member_change
                               or args.screen_polarity is not None or args.allow_shared_members):
        raise Refused("--window-members-constant, --allow-member-change, --screen-polarity and "
                      "--allow-shared-members go with --base-stack (or a use: base recipe)")
    if base_stack is not None and args.stack_plain:
        raise Refused("--stack-plain forms the stack in the time domain and cannot be the base: --base-stack takes "
                      "the band stack")
    if base_stack is not None and base_stack != intersite.BASE_FIELDS[kind]:
        other = next(k for k, f in intersite.BASE_FIELDS.items() if f == base_stack)
        if base_recipe is not None:
            raise Refused(f"--stack {base_recipe.name} is a base recipe of field {base_stack}, the members' "
                          f"{', '.join(intersite.FIELDS[base_stack])}, but {intersite.TENSORS[kind]} (--kind "
                          f"{kind}) takes {', '.join(intersite.KINDS[kind])} as its inputs: a field "
                          f"{base_stack} base recipe goes with --kind {other}")
        raise Refused(f"--base-stack {base_stack} stacks the members' {', '.join(intersite.FIELDS[base_stack])}, "
                      f"but {intersite.TENSORS[kind]} (--kind {kind}) takes {', '.join(intersite.KINDS[kind])} as "
                      f"its inputs: --base-stack {intersite.BASE_FIELDS[kind]} goes with --kind {kind}, "
                      f"--base-stack {base_stack} with --kind {other}")
    if args.remote_exclude is not None and (stack is None or base_stack is None):
        raise Refused("--remote-exclude goes with --remote-stack and --base-stack together: it leaves sites out of "
                      "the reference stack alone; with one stack, --exclude is its list")
    if args.stack_plain and (args.stack_reject_factor is not None or args.stack_min_members is not None):
        raise Refused("--stack-reject-factor and --stack-min-members go with the band stack, not --stack-plain")
    if args.stack_plain and args.stack_method is not None:
        raise Refused("--stack-method goes with the band stack, not --stack-plain (the time-domain mean)")
    reject_factor = (intersite.STACK_REJECT_FACTOR if args.stack_reject_factor is None
                     else float(args.stack_reject_factor))
    min_members = intersite.STACK_MIN_MEMBERS if args.stack_min_members is None else int(args.stack_min_members)
    if not reject_factor > 1.0:
        raise Refused(f"--stack-reject-factor {reject_factor:g}: it must exceed 1, or members at the array level "
                      f"are left out")
    if min_members < 1:
        raise Refused(f"--stack-min-members {min_members}: at least 1")
    # each stack's own settings: a recipe's, else the flags' (shared by the two stacks given by flags)
    flag_method = args.stack_method or "mean"
    settings = {}
    for use, recipe in (("base", base_recipe), ("reference", ref_recipe)):
        if recipe is not None:
            settings[use] = {"reject_factor": recipe.reject_factor, "min_members": recipe.min_members,
                             "method": stacks.METHODS[recipe.method].stack,
                             "min_overlap_hours": recipe.min_overlap_hours}
        else:
            settings[use] = {"reject_factor": reject_factor, "min_members": min_members, "method": flag_method,
                             "min_overlap_hours": (intersite.MIN_OVERLAP_HOURS if args.min_overlap_hours is None
                                                   else float(args.min_overlap_hours))}
    if stack is not None and args.remote_channels is not None:
        named = "--remote-stack names" if ref_recipe is None else f"of its recipe's field ({ref_recipe.name})"
        raise Refused(f"--remote-channels goes with --remote; a stack takes the channels {named}")
    if args.remote is not None and args.remote in (local, base):
        role = "local" if args.remote == local else "base"
        raise Refused(f"the reference {args.remote} is the {role}: a reference must be a third site, since the "
                      f"pair's own channels carry the noise the reference must not share (errors in variables)")
    rate = survey.sample_rate_of(local)
    for recipe in (base_recipe, ref_recipe):
        if recipe is not None and not math.isclose(rate, recipe.sample_rate, rel_tol=1e-9):
            raise Refused(f"--stack {recipe.name}: the recipe is at {recipe.sample_rate:g} Hz and the local {local} "
                          f"at {rate:g} Hz")
    others = ([(base, "base")] if base else []) + ([(args.remote, "remote")] if args.remote else [])
    burst_sites = [s for s in (local, base, args.remote) if s and survey.bursts_parent(s)]
    bursts = bool(burst_sites)
    if bursts:
        named = [s for s in (local, base, args.remote) if s]
        if stack or base_stack or len(burst_sites) != len(named) or len(named) < 3:
            raise Refused(f"burst sites ({', '.join(burst_sites)}) are read on a compact grid of their bursts: the "
                          f"local, the base and a --remote must all be burst sites (bursts_of), and the stacks "
                          f"(--remote-stack, --base-stack), which read a dense grid, are refused")
    for site, label in others:
        if survey.sample_rate_of(site) != rate:
            raise Refused(f"{local} is at {rate:g} Hz and {site} ({label}) at {survey.sample_rate_of(site):g} Hz")
    local_raw, local_runs = _site_runs(survey, local, roles, "local")
    base_raw = base_runs = None
    if base:
        base_raw, base_runs = _site_runs(survey, base, roles, "base")
    ref_roles = intersite.FIELDS[stack] if stack else reference_channels(args.remote_channels)
    remote_raw = remote_runs = None
    if args.remote:
        workspace_archive = survey.workspace / "mth5" / f"{args.remote}.h5"
        if args.remote not in survey.site_names() and workspace_archive.exists():
            raise Refused(f"{args.remote} (remote) is a workspace archive with no survey.yaml entry, such as a "
                          f"stack from build_stack.py: its member sites cannot be checked against the local and "
                          f"the base, and a stack holding either carries the noise the reference must not share "
                          f"(errors in variables); use --remote-stack E|H, or a site of survey.yaml")
        remote_raw, remote_runs = _site_runs(survey, args.remote, ref_roles, "remote")
    mask_file = masks_path(survey)
    mask_sites = {}
    for role_name, site, chans in (("local", local, roles), ("base", base, roles), ("reference", args.remote,
                                                                                    ref_roles)):
        if site:
            mask_sites[site] = {"role": role_name, "scopes": list(SCOPES_OF_ROLE[intersite.mask_role(role_name)]),
                                "channels": list(chans),
                                **intersite.site_masks(load_masks(survey, site), role_name, chans)}

    span = lambda runs: (runs[0][0], max(e for _s, e in runs))  # noqa: E731
    spans = {"local": span(local_runs)}
    if base_runs:
        spans["base"] = span(base_runs)
    if remote_runs:
        spans["remote"] = span(remote_runs)
    # the window: the command line's, else a recipe's (stack_recipes refused two that differ), else the common span
    recipe_window = next((r.window_ns for r in (base_recipe, ref_recipe) if r is not None and r.window_ns), None)
    if recipe_window is not None and start is None and end is None:
        lo, hi = recipe_window
    else:
        lo = max(s for s, _e in spans.values()) if start is None else _utc(start).value
        hi = min(e for _s, e in spans.values()) if end is None else _utc(end).value
    if hi <= lo:
        raise Refused("the window is empty: " + "; ".join(
            f"{name} {_text_ns(s)} to {_text_ns(e)}" for name, (s, e) in spans.items()))
    for name, runs in (("local", local_runs), ("base", base_runs), ("remote", remote_runs)):
        if runs and intersite.overlap_hours(runs, lo, hi) <= 0:
            raise Refused(f"the {name} records nothing in the window {_text_ns(lo)} to {_text_ns(hi)}")
    clock = _Clock(rate)
    i0, i1 = clock.ceil(lo), clock.ceil(hi)
    t0_ns, n = clock.ns(i0), i1 - i0
    burst_grid = None
    if bursts:
        slots = None
        lengths = {}
        for site in (local, base, args.remote):
            mine = intersite.burst_slots(default_archive_path(survey, site), site,
                                         ref_roles if site == args.remote else roles)
            mine = {s: v for s, v in mine.items() if lo <= s < hi}
            lengths.update({(site, s): v[1] for s, v in mine.items()})
            slots = set(mine) if slots is None else slots & set(mine)
        slots = sorted(slots)
        if not slots:
            raise Refused(f"the burst sites share no burst start in the window {_text_ns(lo)} to {_text_ns(hi)}")
        per_burst = min(v for (site, s), v in lengths.items() if s in set(slots))
        n = len(slots) * (per_burst + intersite.BURST_GAP) - intersite.BURST_GAP
        t0_ns = slots[0]
        burst_grid = {"grid": "compact bursts", "slots": len(slots), "samples_per_burst": per_burst,
                      "gap_samples": intersite.BURST_GAP, "first_slot": _ts(slots[0]).isoformat(),
                      "last_slot": _ts(slots[-1]).isoformat(), "slots_ns": slots}

    members, left_out = [], []
    exclude = parse_list(args.exclude)
    ref_exclude = exclude if args.remote_exclude is None else parse_list(args.remote_exclude)
    ref_exclude_from = "--exclude" if args.remote_exclude is None else "--remote-exclude"
    ref_set, base_set = settings["reference"], settings["base"]
    if ref_recipe is not None:
        ref_exclude, ref_exclude_from = list(ref_recipe.exclude), f"stacks.yaml {ref_recipe.name}"
    if base_recipe is not None:
        exclude = list(base_recipe.exclude)
    if stack:
        what = f"the {stack} stack" if ref_recipe is None else f"the reference recipe {ref_recipe.name}"
        if ref_recipe is not None:
            members, left_out = recipe_members(ref_recipe, survey, lo, hi, local, base)
        else:
            members, left_out = intersite.select_stack(survey, local, base, lo, hi, ref_roles, ref_exclude,
                                                       ref_set["min_overlap_hours"])
        if not members:
            raise Refused(f"no site qualifies for {what}: " + "; ".join(
                f"{x['site']} {x['reason']}" for x in left_out))
        if not args.stack_plain and len(members) < ref_set["min_members"]:
            least = "--stack-min-members" if ref_recipe is None else "the recipe's min_members"
            raise Refused(f"{what} has {len(members)} member(s), fewer than {least} {ref_set['min_members']}: "
                          f"every window would be left out")
    base_block = None
    if base_stack:
        what = f"the {base_stack} base stack" if base_recipe is None else f"the base recipe {base_recipe.name}"
        if base_recipe is not None:
            b_members, b_left = recipe_members(base_recipe, survey, lo, hi, local, None,
                                               edge_s=intersite.MEMBER_EDGE_S)
        else:
            b_members, b_left = intersite.select_stack(survey, local, None, lo, hi, roles, exclude,
                                                       base_set["min_overlap_hours"], edge_s=intersite.MEMBER_EDGE_S)
        if not b_members:
            raise Refused(f"no site qualifies for {what}: " + "; ".join(
                f"{x['site']} {x['reason']}" for x in b_left))
        if len(b_members) < base_set["min_members"]:
            least = "--stack-min-members" if base_recipe is None else "the recipe's min_members"
            raise Refused(f"{what} has {len(b_members)} member(s), fewer than {least} {base_set['min_members']}: "
                          f"every window would be left out")
        constant = (not args.allow_member_change if base_recipe is None
                    else base_recipe.member_change == "constant")
        changes = intersite.member_changes(survey, b_members, roles, lo, hi)
        if changes and constant:
            how = ("--allow-member-change to run it and record the changes" if base_recipe is None else
                   f"member_change: allow in {base_recipe.name} to run it and record the changes")
            raise Refused("the base stack's membership changes inside the window " + f"{_text_ns(lo)} to "
                          f"{_text_ns(hi)}: " + "; ".join(f"{c['site']} {c['change']} at {_text_ns(c['time_ns'])}"
                                                          for c in changes)
                          + f": run one window per constant-membership epoch, or {how}")
        ref_sites = [m["site"] for m in members] if stack else [args.remote]
        try:
            shared = intersite._check_keys(
                tuple(PREFIXES["local"] + r for r in roles), tuple(PREFIXES["base"] + r for r in roles),
                tuple(PREFIXES["reference"] + r for r in ref_roles), [m["site"] for m in b_members], ref_sites,
                args.allow_shared_members)
        except ValueError as exc:
            hint = ("--exclude, or --remote-exclude for a reference stack" if not args.stack else
                    "exclude: or members: in the recipe")
            raise Refused(f"{exc}; leave the site out ({hint}) or take another reference, or "
                          f"--allow-shared-members to run it and record the overlap") from None
        mode = (args.screen_polarity or "flag") if base_recipe is None else base_recipe.screen_polarity
        method = base_set["method"]
        base_block = {
            "type": "stack", "site": None, "field": base_stack, "form": "band", "method": method,
            "channels": list(roles), "rule": STACK_RULES[method], "reject_factor": base_set["reject_factor"],
            "min_members": base_set["min_members"], "scale_units": SCALE_UNITS, "units": STACK_UNITS_OF[method],
            "members": b_members, "left_out": b_left,
            "exclude": exclude, "min_overlap_hours": base_set["min_overlap_hours"], "local_excluded": local,
            "window": {"start": _ts(lo).isoformat(), "end": _ts(hi).isoformat(), "hours": (hi - lo) / 3.6e12},
            "window_members_constant": constant, "member_edge_s": intersite.MEMBER_EDGE_S,
            "member_changes": [{"site": c["site"], "change": c["change"], "time": _ts(c["time_ns"]).isoformat()}
                               for c in changes],
            "screen_polarity": {"mode": mode, "periods_s": list(intersite.POLARITY_PERIODS),
                                "rule": "each member channel's correlation with the mean of the other members' "
                                        "same channel per band (each over its per-band scale, the windows the "
                                        "stack rejects left out); a negative median over the bands flags it"
                                        + ("; a member flagged in either channel is left out of the stack"
                                           if mode == "drop" else "")},
            "shared_with_reference": shared, "allow_shared_members": bool(args.allow_shared_members)}
        if base_recipe is not None:
            base_block.update(recipe_record(base_recipe))
    # a recipe is labelled by its name; a median given by flags adds "med", so a mean and a median product of
    # one pair keep apart; the default labels (stackE, stackH) are unchanged
    if ref_recipe is not None:
        ref_label = ref_recipe.name
    elif stack:
        ref_label = f"stack{stack}" + ("med" if ref_set["method"] == "median" and not args.stack_plain else "")
    else:
        ref_label = args.remote if ref_roles == intersite.FIELDS["H"] else f"{args.remote}-E"
    # every declared recorded site, its raw folder found or not: the archive status and the sidecar's
    # filter record then say what `processing_archive` reads whichever root holds the raw folders
    raw_sites = recorded_site_folders(survey)
    use_filters = not args.no_filters
    scheme_kwargs = _scheme_kwargs(survey)
    if args.min_period is not None:
        scheme_kwargs["min_period"] = float(args.min_period)
    elif rate != survey.sample_rate:
        scheme_kwargs["min_period"] = site_min_period(rate, survey.sample_rate, scheme_kwargs["min_period"],
                                                      scheme_kwargs["periods_per_decade"],
                                                      scheme_kwargs.get("factor", 4))
    scheme = build_band_scheme(rate, **scheme_kwargs)
    n_bands = sum(len(b) for b in scheme["band_edges"].values())
    out_dir = Path(args.out_dir) if args.out_dir else survey.workspace / "tf"
    if base:
        base_label = base
    elif base_recipe is not None:
        base_label = base_recipe.name
    else:
        base_label = f"stack{base_stack}" + ("med" if base_set["method"] == "median" else "")
    stem = stem_of(local, base_label, kind, ref_label, args.tag)
    reference = {"type": "stack" if stack else "site", "site": None if stack else args.remote,
                 "channels": list(ref_roles)}
    channels = 6
    if stack and args.stack_plain:
        reference.update({"field": stack, "form": "plain",
                          "rule": "each member's channel median removed and divided by its RMS "
                                  "over the window, then the plain mean of the members present",
                          "members": members, "left_out": left_out, "exclude": ref_exclude,
                          "exclude_from": ref_exclude_from, "min_overlap_hours": ref_set["min_overlap_hours"]})
    elif stack:
        method = ref_set["method"]
        reference.update({"field": stack, "form": "band", "method": method, "rule": STACK_RULES[method],
                          "reject_factor": ref_set["reject_factor"], "min_members": ref_set["min_members"],
                          "scale_units": SCALE_UNITS, "members": members, "left_out": left_out,
                          "exclude": ref_exclude, "exclude_from": ref_exclude_from,
                          "min_overlap_hours": ref_set["min_overlap_hours"]})
        if ref_recipe is not None:
            reference.update(recipe_record(ref_recipe))
        channels = 2 * len(roles) + len(ref_roles) * len(members)
    if base_block is not None:
        channels += len(roles) * (len(base_block["members"]) - 1)
    return {
        "survey": survey, "survey_yaml": str(Path(args.survey_yaml)), "kind": kind,
        "tensor": intersite.TENSORS[kind], "local": local, "base": base, "base_label": base_label,
        "base_stack": base_block, "roles": roles, "reference": reference,
        "ref_label": ref_label, "remote_archive": remote_raw, "local_archive": local_raw,
        "base_archive": base_raw, "raw_sites": raw_sites, "use_filters": use_filters,
        "status": {site: archive_status(survey, site, raw_sites, use_filters)
                   for site in [local] + ([base] if base else []) + ([args.remote] if args.remote else [])},
        "spans": spans, "window": (lo, hi), "t0_ns": t0_ns, "n": n, "sample_rate": rate,
        "scheme_kwargs": scheme_kwargs, "scheme": scheme, "n_bands": n_bands,
        "lowest_harmonic": lowest_harmonic(rate, **scheme_kwargs), "stem": stem, "out_dir": out_dir,
        "tag": args.tag, "started": started,
        "memory_gb": n * bytes_per_sample(channels) / 1e9,
        "bursts": burst_grid,
        "masks": {"file": str(mask_file) if mask_file.exists() else None, "sites": mask_sites,
                  "stack_members": ("their masks.yaml entries are not applied" if stack or base_stack else None)},
        # a recipe's window that the command line's replaced, for the log; None when the recipe's is used
        "recipe_window": recipe_window if recipe_window is not None and (start, end) != (None, None) else None,
    }


def print_resolution(res: dict) -> None:
    """Print the resolution as `key: value` lines, as --dry-run and the log show them."""
    roles = res["roles"]
    ref = res["reference"]
    bstack = res["base_stack"]
    lo, hi = res["window"]
    lines = [
        ("survey_yaml", res["survey_yaml"]),
        ("kind", f"{res['kind']} ({res['tensor']})"),
        ("outputs", f"{res['local']} {', '.join(roles)}"),
        ("inputs", (f"base stack {bstack['field']}: {', '.join(bstack['channels'])} of {len(bstack['members'])} "
                    f"member(s), {res['local']} left out" if bstack else f"{res['base']} {', '.join(roles)}")),
        ("reference", (f"stack {ref['field']}: {', '.join(ref['channels'])} of {len(ref['members'])} member(s)"
                       if ref["type"] == "stack" else
                       f"{ref['site']} {', '.join(ref['channels'])}")),
    ]
    for key, value in lines:
        print(f"{key}: {value}")
    for site, status in res["status"].items():
        if status is None:
            print(f"archive {site}: (no raw folder)")
        else:
            missing = f" ({status['raw_missing']})" if status.get("raw_missing") else ""
            print(f"archive {site}: raw: {status['raw']}{missing}, variant: {status['variant_state']}")
    for name, (s, e) in res["spans"].items():
        print(f"{name}_span: {_text_ns(s)} to {_text_ns(e)}")
    print(f"window: {_text_ns(lo)} to {_text_ns(hi)} ({(hi - lo) / 3.6e12:.2f} h, {res['n']} samples "
          f"at {res['sample_rate']:g} Hz)")
    if res.get("recipe_window"):
        rlo, rhi = res["recipe_window"]
        print(f"recipe_window: {_text_ns(rlo)} to {_text_ns(rhi)} (the command line's is used)")
    if bstack:
        for m in bstack["members"]:
            status = archive_status(res["survey"], m["site"], res["raw_sites"], res["use_filters"])
            state = status["variant_state"] if status else "no raw folder"
            print(f"base_member: {m['site']} {m['overlap_h']:.2f} h of the window, variant: {state}")
        for x in bstack["left_out"]:
            print(f"base_left_out: {x['site']} ({x['reason']})")
        print(f"base_stack_form: band (per-band scale, a member's window over {bstack['reject_factor']:g} times the "
              f"array level left out, at least {bstack['min_members']} member(s) kept per window)")
        print(f"base_stack_method: {bstack['method']}")
        if bstack.get("recipe"):
            print(f"base_stack_recipe: {bstack['recipe']} {bstack['recipe_hash']}")
        print(f"window_members_constant: {'on' if bstack['window_members_constant'] else 'off'} (a start or end "
              f"more than {bstack['member_edge_s']:g} s inside the window is a change)")
        for c in bstack["member_changes"]:
            print(f"member_change: {c['site']} {c['change']} at {_text_ns(_utc(c['time']).value)}")
        screen = bstack["screen_polarity"]
        print(f"polarity_screen: {screen['mode']} (median correlation with the other members over the "
              f"{screen['periods_s'][0]:g}-{screen['periods_s'][1]:g} s bands; the flags need the samples, so they "
              f"come with the run)")
        shared = bstack["shared_with_reference"]
        print(f"shared_members: {', '.join(shared) if shared else 'none'}"
              + (" (--allow-shared-members)" if shared else ""))
        if bstack["method"] == "median":
            print(f"base_stack_units: per-band normalised (median): |{res['tensor']}| is not a field ratio; the "
                  f"phases and arg(det)/2 are the members' common ones only when their phase responses agree; "
                  f"stack_scale_rms per band in the sidecar")
        else:
            print(f"base_stack_units: per-band normalised: |{res['tensor']}| is not a field ratio; the phases and "
                  f"arg(det)/2 are unaffected; stack_scale_rms per band in the sidecar")
    if ref["type"] == "stack":
        for m in ref["members"]:
            status = archive_status(res["survey"], m["site"], res["raw_sites"], res["use_filters"])
            state = status["variant_state"] if status else "no raw folder"
            print(f"member: {m['site']} {m['overlap_h']:.2f} h of the window, variant: {state}")
        for x in ref["left_out"]:
            print(f"left_out: {x['site']} ({x['reason']})")
        if bstack:
            print(f"reference_exclude: {', '.join(ref['exclude']) or 'none'} ({ref['exclude_from']})")
    if ref["type"] == "stack" or bstack:
        print(f"min_overlap_hours: {(bstack or ref)['min_overlap_hours']:g}")
        if bstack and ref["type"] == "stack" and ref["min_overlap_hours"] != bstack["min_overlap_hours"]:
            print(f"reference_min_overlap_hours: {ref['min_overlap_hours']:g}")
    if ref["type"] == "stack":
        if ref["form"] == "plain":
            print("stack_form: plain (--stack-plain: each member over its RMS over the window, time-domain mean)")
        else:
            print(f"stack_form: band (per-band scale, a member's window over {ref['reject_factor']:g} times the "
                  f"array level left out, at least {ref['min_members']} member(s) kept per window)")
            print(f"stack_method: {ref['method']}")
            if ref.get("recipe"):
                print(f"stack_recipe: {ref['recipe']} {ref['recipe_hash']}")
    for key in BAND_KEYS:
        value = res["scheme_kwargs"][key]
        if key == "notch_frequencies":
            value = ", ".join(f"{f:g}" for f in value)
        print(f"{'window_samples' if key == 'window' else key}: {value}")
    print(f"lowest_harmonic: {res['lowest_harmonic']:.4g}")
    print(f"bands: {res['n_bands']} on {len(res['scheme']['band_edges'])} decimation levels")
    print(f"estimator: huber r0 {intersite.R0:g}, {intersite.JACKKNIFE_GROUPS}-slice jackknife, at most "
          f"{intersite.MAX_WINDOWS} windows per level")
    print(f"filters: {'raw archives (--no-filters)' if not res['use_filters'] else 'filtered variants where declared'}")
    masks = res["masks"]
    print(f"masks_file: {masks['file'] or 'none (no masks.yaml beside survey.yaml)'}")
    for site, entry in masks["sites"].items():
        print(f"masks: {site} ({entry['role']}, scopes {'/'.join(entry['scopes'])}): {len(entry['applied'])} "
              f"entries applied, {len(entry['left_out_scope'])} left out by scope, "
              f"{len(entry['left_out_channels'])} naming none of {','.join(entry['channels'])}")
    if masks["stack_members"]:
        print(f"masks: stack members: {masks['stack_members']}")
    print(f"stem: {res['stem']}")
    print(f"out_dir: {res['out_dir']}")
    if res.get("bursts"):
        g = res["bursts"]
        print(f"grid: compact bursts, {g['slots']} shared burst(s) of {g['samples_per_burst']} samples, "
              f"{g['first_slot']} to {g['last_slot']}")
    print(f"memory: about {res['memory_gb']:.1f} GB")


def member_keys(index: int, roles) -> dict:
    """Return the channel keys of the band stack's member `index`: {role: s<index>_<role>}."""
    return {r: f"s{index}_{r}" for r in roles}


def base_member_keys(index: int, roles) -> dict:
    """Return the channel keys of the base stack's member `index`: {role: bs<index>_<role>}."""
    return {r: f"bs{index}_{r}" for r in roles}


def _read_members(res: dict, members, channels, keys_of, arrays: dict, responses: dict) -> tuple[list, dict]:
    """Read a band stack's members' channels into `arrays` and `responses` under `keys_of(i, channels)`.

    Returns:
        tuple: (one record per member: site, archive, channels, coverage;
        {site: calibration}).
    """
    survey, t0, n, rate = res["survey"], res["t0_ns"], res["n"], res["sample_rate"]
    records, calibration = [], {}
    for i, m in enumerate(members):
        site = m["site"]
        path = processing_archive(survey, site, res["use_filters"])
        warn_without_h_polarity(path, site)
        got, resp, chains = intersite.read_channels(path, site, channels, t0, n, rate)
        keys = keys_of(i, channels)
        live = np.ones(n, dtype=bool)
        for r in channels:
            live &= np.isfinite(got[r])
        arrays.update({keys[r]: got[r] for r in channels})
        responses.update({keys[r]: resp[r] for r in channels})
        calibration[site] = chains
        records.append({"site": site, "archive": str(path), "channels": {r: chains[r]["channel"] for r in channels},
                        "coverage": round(float(live.mean()), 6)})
        del live
        logger.info(f"stack member {site}: coverage {records[-1]['coverage']:.3f}")
    return records, calibration


def read_inputs(res: dict) -> tuple[dict, dict, dict, list, list]:
    """Read the local's, the base's and the reference's channels over the window.

    Returns:
        tuple: (arrays keyed l_<role>, b_<role> for a named base or
        bs<i>_<role> per member of the base stack (`base_member_keys`),
        and r_<role> for a site or the plain stack, or s<i>_<role> per
        member of the band stack (`member_keys`); responses keyed likewise,
        none for the plain stack; the archives and calibration per site;
        the reference stack's member records, [] for a site reference; the
        base stack's member records, [] for a named base).
    """
    survey, roles, ref = res["survey"], res["roles"], res["reference"]
    t0, n, rate, use_filters = res["t0_ns"], res["n"], res["sample_rate"], res["use_filters"]
    arrays, responses, sources, members, base_members = {}, {}, {}, [], []
    grid = res.get("bursts")

    def read(path, site, channels):
        if grid:
            return intersite.read_bursts(path, site, channels, grid["slots_ns"], grid["samples_per_burst"], rate)
        return intersite.read_channels(path, site, channels, t0, n, rate)

    for role_name, site in (("local", res["local"]), ("base", res["base"])):
        if site is None:
            continue
        path = processing_archive(survey, site, use_filters)
        warn_without_h_polarity(path, site)
        got, resp, chains = read(path, site, roles)
        prefix = PREFIXES[role_name]
        arrays.update({prefix + r: got[r] for r in roles})
        responses.update({prefix + r: resp[r] for r in roles})
        sources[role_name] = {"site": site, "archive": _archive_info(path), "calibration": chains}
    if res["base_stack"] is not None:
        base_members, calibration = _read_members(res, res["base_stack"]["members"], roles, base_member_keys,
                                                   arrays, responses)
        sources["base"] = {"site": res["base_label"], "archive": None, "calibration": calibration}
    prefix = PREFIXES["reference"]
    if ref["type"] == "stack" and ref["form"] == "band":
        members, calibration = _read_members(res, ref["members"], ref["channels"], member_keys, arrays, responses)
        sources["reference"] = {"site": res["ref_label"], "archive": None, "calibration": calibration}
    elif ref["type"] == "stack":
        got, members = intersite.stack_channels(survey, ref["members"], ref["channels"], t0, n, rate, use_filters)
        arrays.update({prefix + r: got[r] for r in ref["channels"]})
        sources["reference"] = {"site": f"stack{ref['field']}", "archive": None,
                                "calibration": "none: the estimate is unchanged by a fixed linear transform of "
                                               "the reference"}
    else:
        path = processing_archive(survey, ref["site"], use_filters)
        warn_without_h_polarity(path, ref["site"])
        got, resp, chains = read(path, ref["site"], ref["channels"])
        arrays.update({prefix + r: got[r] for r in ref["channels"]})
        responses.update({prefix + r: resp[r] for r in ref["channels"]})
        sources["reference"] = {"site": ref["site"], "archive": _archive_info(path), "calibration": chains}
    return arrays, responses, sources, members, base_members


def stack_summary(record: list) -> dict:
    """Return the band stack's record summed up: windows left out, and each member's rejected fractions.

    Args:
        record (list): `mt_workbench.intersite.band_stack`'s record, one dict per band.

    Returns:
        dict: ``bands``, ``bands_left_out`` (not estimated), ``windows``,
        ``windows_left_out`` (over every band), and ``members``, {site:
        {role: {"median", "max"} of the rejected fraction over the bands}}.
    """
    out = {"bands": len(record), "bands_left_out": sum(1 for b in record if not b["estimated"]),
           "windows": sum(b["windows"] for b in record), "windows_left_out": sum(b["left_out"] for b in record),
           "members": {}}
    for band in record:
        for site, roles in band["members"].items():
            for role, value in roles.items():
                if value["rejected"] is not None:
                    out["members"].setdefault(site, {}).setdefault(role, []).append(value["rejected"])
    for site, roles in out["members"].items():
        for role, values in roles.items():
            roles[role] = {"median": float(np.median(values)), "max": float(np.max(values))}
    return out


def base_stack_block(res: dict, members: list, record: list, polarity: dict) -> dict:
    """Return the sidecar's base_stack block: the resolution's, with each member's read record and per-band values.

    Args:
        res (dict): Output of `resolve`.
        members (list): `read_inputs`'s base member records.
        record (list): `mt_workbench.intersite.band_stack`'s record of the base stack.
        polarity (dict): The polarity screen: ``record``, ``flags`` and ``dropped``.

    Returns:
        dict: The block, members with ``overlap_h`` and ``per_band`` (period,
        level, estimated and per role scale, present and rejected; none for a
        member left out by the screen), ``bands`` (the record), ``summary``
        (`stack_summary`) and ``polarity``.
    """
    block = dict(res["base_stack"])
    overlap = {m["site"]: m["overlap_h"] for m in block["members"]}
    out = []
    for m in members:
        entry = dict(m, overlap_h=overlap.get(m["site"]), dropped=m["site"] in polarity["dropped"], per_band=[])
        for band in record:
            values = band["members"].get(m["site"])
            if values is not None:
                entry["per_band"].append({"period": band["period"], "level": band["level"],
                                          "estimated": band["estimated"], **values})
        out.append(entry)
    block["members"] = out
    block["bands"] = record
    block["summary"] = stack_summary(record)
    block["screen_polarity"] = dict(block["screen_polarity"], flags=polarity["flags"],
                                    flagged=[f for f in polarity["flags"] if f["flagged"]],
                                    dropped=polarity["dropped"], bands=polarity["record"])
    return block


def flag_block(est) -> dict:
    """Return the sidecar's flags: each flag's rule, its limit where it has one, and its row count.

    A flag marks a period in the CSV and the h5 and never removes it.
    """
    rules = {"flag_not_estimated": ("an element of the tensor is not finite; a band of the layout the record "
                                    "could not form has 0 windows", None),
             "flag_few_groups": ("n_groups below the limit on an estimated row", intersite.FLAG_MIN_GROUPS),
             "flag_low_coherence": ("coh_out_weighted of either row below the limit, the coherence screen limit "
                                    "of upstream 110: a coherence of the output on the reference, not calibrated "
                                    "against the errors of T", intersite.FLAG_COHERENCE),
             "flag_off_diagonal": ("|xy yx| > |xx yy|: the shape of a tensor with one site's electric channels "
                                   "exchanged, or a turn of more than 45 deg between the two sites' layouts "
                                   "(see the frames block)", None),
             "flag_re_det_negative": ("Re det < 0: also with arg(det) / 2 beyond 45 deg", None)}
    out = {}
    for name, values in est.flags().items():
        rule, limit = rules[name]
        out[name] = {"rule": rule, "rows": int(np.sum(values))}
        if limit is not None:
            out[name]["below"] = limit
    return out


def frames_block(res: dict, base_block: dict | None = None) -> dict:
    """Return the frames of the local and the base (or each base stack member) as survey.yaml declares them.

    The frames are recorded and not applied: the tensor stays in each
    site's channels as recorded, so a T between sites laid out at
    different azimuths carries their relative turn. ``entry`` is False for
    a site with no survey.yaml entry, whose values are the defaults.
    """
    survey = res["survey"]
    names = survey.site_names()
    roles = [(res["local"], "local")]
    if res["base"]:
        roles.append((res["base"], "base"))
    elif base_block is not None:
        roles += [(m["site"], "base stack member") for m in base_block["members"]]
    sites = {}
    for site, role in roles:
        cfg = survey.site(site)
        sites[site] = {"role": role, "entry": site in names, "azimuth_ex": cfg.azimuth_ex,
                       "azimuth_ey": cfg.azimuth_ey, "layout_north": cfg.layout_north,
                       "declination": cfg.declination}
    return {"source": "survey.yaml", "applied": False,
            "rule": "recorded, not applied: the tensor is in each site's channels as recorded", "sites": sites}


def mask_block(res: dict, record: list) -> dict:
    """Return the sidecar's `masks` block: each site's entries applied and left out, and the windows masked.

    Args:
        res (dict): Output of `resolve`.
        record (list): `mt_workbench.intersite.band_spectra`'s mask record,
            [] when no entry covers a sample of the grid.

    Returns:
        dict: "file" (None without masks.yaml), "window_rule", "sites"
        ({site: role, scopes, channels, the entries "applied",
        "left_out_scope" and "left_out_channels", and "windows_masked", the
        band windows its entries cover summed over the bands}), "bands"
        (the record), "windows_left_out" and "stack_members".
    """
    masks = res["masks"]
    sites = {}
    for site, entry in masks["sites"].items():
        sites[site] = dict(entry)
        sites[site]["windows_masked"] = int(sum(r["masked"].get(site, 0) for r in record))
    return {"file": masks["file"],
            "window_rule": "a window holding a sample inside an applied entry is left out of the bands the entry "
                           "covers; counts are of the windows clear of gaps, before the thinning to "
                           f"{intersite.MAX_WINDOWS} per level",
            "sites": sites, "bands": record, "windows_left_out": int(sum(r["left_out"] for r in record)),
            "stack_members": masks["stack_members"]}


def build_sidecar(res: dict, args, started, finished, est, timing: dict, sources: dict, members: list,
                  paths: dict, coverage: float, stack_record: list | None = None,
                  base_block: dict | None = None, masks: dict | None = None) -> dict:
    """Build the `.json` sidecar of one run, in process_rr.py's form.

    Args:
        res (dict): Output of `resolve`.
        args (argparse.Namespace): Parsed arguments.
        started, finished (datetime.datetime): Start and end of the run.
        est (TensorEstimate): The estimate.
        timing (dict): Its `timing_check`.
        sources (dict): `read_inputs`'s archives and calibration.
        members (list): The stack's member records.
        paths (dict): The products written, {"csv", "h5", "figure"}.
        coverage (float): Fraction of the window every channel covers.
        stack_record (list, optional): The band stack's record per band
            (`mt_workbench.intersite.band_stack`), stored in the reference
            block as ``bands`` with its `stack_summary`.
        base_block (dict, optional): `base_stack_block` with --base-stack,
            stored as ``base_stack`` (null with a named base).
        masks (dict, optional): `mask_block`, stored as ``masks``.

    Returns:
        dict: The sidecar.
    """
    survey = res["survey"]
    ref = dict(res["reference"])
    if ref["type"] == "stack":
        ref["members"] = members
    if stack_record is not None:
        ref["summary"] = stack_summary(stack_record)
        ref["bands"] = stack_record
    lo, hi = res["window"]
    finite = np.isfinite(est.half_arg_err_deg)
    base_sites = [res["base"]] if res["base"] else [m["site"] for m in base_block["members"]]
    filter_sites = [res["local"]] + base_sites + ([ref["site"]] if ref["type"] == "site" else
                                                  [m["site"] for m in members])
    inputs = ([f"{res['base']} {r}" for r in res["roles"]] if res["base"] else
              [f"{res['base_label']} {r}" for r in res["roles"]])
    return {
        "kind": res["kind"],
        "tensor": res["tensor"],
        "local": res["local"],
        "base_site": res["base"],
        "base_stack": base_block,
        "remote": res["ref_label"],
        "outputs": [f"{res['local']} {r}" for r in res["roles"]],
        "inputs": inputs,
        "reference": ref,
        "units": base_block["units"] if base_block is not None else intersite.UNITS,
        "started": started.isoformat(),
        "finished": finished.isoformat(),
        "seconds": (finished - started).total_seconds(),
        "window": {"start": _ts(lo).isoformat(), "end": _ts(hi).isoformat(), "hours": (hi - lo) / 3.6e12,
                   "samples": res["n"], "coverage": coverage},
        "local_archive": sources["local"]["archive"],
        "base_archive": sources["base"]["archive"],
        "remote_archive": sources["reference"]["archive"],
        "calibration": {k: v["calibration"] for k, v in sources.items()},
        "survey_yaml": {"path": res["survey_yaml"], "name": Path(res["survey_yaml"]).name},
        "sample_rates": {"survey": survey.sample_rate, "local": res["sample_rate"]},
        "grid": ({k: v for k, v in res["bursts"].items() if k != "slots_ns"} if res.get("bursts")
                 else "dense"),
        "band_scheme": dict(res["scheme_kwargs"]),
        "lowest_harmonic": res["lowest_harmonic"],
        "estimator": {"engine": "mt_workbench.intersite", "method": "huber", "r0": intersite.R0,
                      "max_iterations": intersite.MAX_ITERATIONS, "tolerance": intersite.TOLERANCE,
                      "jackknife_groups": intersite.JACKKNIFE_GROUPS, "max_windows": intersite.MAX_WINDOWS,
                      "window_samples": int(res["scheme"]["num_samples_window"][0]), "taper": "hann",
                      "overlap": f"25 % (75 % for windows over {intersite.LONG_WINDOW_S:g} s)",
                      "prewhiten": "first difference, recoloured"},
        "filters": {site: _declared_filters(survey, site, res["raw_sites"]) for site in filter_sites},
        "masks": masks if masks is not None else mask_block(res, []),
        "frames": frames_block(res, base_block),
        "counts": {"bands": int(est.period.size), "bands_with_errors": int(finite.sum()),
                   "windows_per_level": {str(int(lv)): int(est.n_windows[est.level == lv].max())
                                         for lv in np.unique(est.level)},
                   "bands_not_formed": int((est.n_windows == 0).sum())},
        "flags": flag_block(est),
        "timing_check": timing,
        "argv": list(sys.argv),
        "tag": res["tag"],
        "csv": paths["csv"].name,
        "h5": paths["h5"].name,
        "figure": paths["figure"].name,
        "versions": versions(),
    }


def main(args) -> None:
    """Estimate T or M for one pair and write the CSV, JSON sidecar, HDF5 and figure.

    Args:
        args (argparse.Namespace): Parsed arguments from `build_parser`.
    """
    started = dt.datetime.now().astimezone()
    try:
        res = resolve(args, started)
    except Refused as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    print_resolution(res)
    if args.dry_run:
        return
    tic = time.time()
    arrays, responses, sources, members, base_members = read_inputs(res)
    ref, bstack = res["reference"], res["base_stack"]
    band_form = ref["type"] == "stack" and ref["form"] == "band"
    stack_keys = [member_keys(i, ref["channels"]) for i in range(len(members))] if band_form else []
    roles, ref_roles = res["roles"], res["reference"]["channels"]
    base_keys = [base_member_keys(i, roles) for i in range(len(base_members))]
    optional = [k for keys in stack_keys + base_keys for k in keys.values()]
    covered = np.ones(res["n"], dtype=bool)
    for key, a in arrays.items():
        if key not in optional:
            covered &= np.isfinite(a)
    for keys_list, channels, need in ((stack_keys, ref["channels"] if band_form else (), ref.get("min_members")),
                                      (base_keys, roles if bstack else (), (bstack or {}).get("min_members"))):
        for r in channels:
            count = np.zeros(res["n"], dtype=np.uint16)
            for keys in keys_list:
                count += np.isfinite(arrays[keys[r]])
            covered &= count >= need
            del count
    coverage = float(covered.mean())
    del covered
    logger.info(f"read {len(arrays)} channels in {time.time() - tic:.0f} s; {coverage:.4f} of the window covered "
                f"by every channel")
    outputs = tuple(PREFIXES["local"] + r for r in roles)
    inputs = tuple(PREFIXES["base"] + r for r in roles)
    reference = tuple(PREFIXES["reference"] + r for r in ref_roles)

    def progress(band, out):
        logger.debug(f"L{band.level} {band.period:.4g} s: {band.n_windows} windows, arg(det)/2 "
                     f"{out['half_arg_deg']:+.3f} +/- {out['half_arg_err_deg']:.3f} deg")

    stack_record = base_record = None
    polarity = {"record": [], "flags": [], "dropped": []}
    grid = res.get("bursts")
    spans = []
    for site, entry in res["masks"]["sites"].items():
        spans += intersite.mask_spans(entry["applied"], res["t0_ns"], res["n"], res["sample_rate"], site,
                                      slots_ns=grid["slots_ns"] if grid else None,
                                      per_burst=grid["samples_per_burst"] if grid else None)
    mask_record = []
    # without a span band_spectra is called with no mask argument
    masking = {"masked": spans, "mask_record": mask_record} if spans else {}
    if optional:
        bands = intersite.band_spectra(arrays, res["sample_rate"], res["scheme"], responses, optional=optional,
                                       **masking)
    else:
        bands = intersite.band_spectra(arrays, res["sample_rate"], res["scheme"], responses, **masking)
    if bstack:
        pairs = [(m["site"], keys) for m, keys in zip(base_members, base_keys)]
        bands = intersite.polarity_screen(bands, pairs, roles, reject_factor=bstack["reject_factor"],
                                          record=polarity["record"])
        if bstack["screen_polarity"]["mode"] == "drop":
            bands = list(bands)  # the screen needs every band of 1-100 s before the stack is formed
            polarity["flags"] = intersite.polarity_summary(polarity["record"], [p[0] for p in pairs], roles)
            polarity["dropped"] = sorted({f["site"] for f in polarity["flags"] if f["flagged"]})
            if polarity["dropped"]:
                gone = [k for name, keys in pairs if name in polarity["dropped"] for k in keys.values()]
                for band in bands:
                    for k in gone:
                        band.spectra.pop(k, None)
                pairs = [(name, keys) for name, keys in pairs if name not in polarity["dropped"]]
                logger.info(f"polarity screen: {', '.join(polarity['dropped'])} left out of the base stack")
            if len(pairs) < bstack["min_members"]:
                least = "--stack-min-members" if not bstack.get("recipe") else f"{bstack['recipe']}'s min_members"
                print(f"ERROR the polarity screen leaves {len(pairs)} base stack member(s), fewer than "
                      f"{least} {bstack['min_members']}", file=sys.stderr)
                raise SystemExit(2)
        base_record = []
        bands = intersite.band_stack(bands, pairs, dict(zip(roles, inputs)), bstack["reject_factor"],
                                     bstack["min_members"], base_record, method=bstack["method"])
    if band_form:
        stack_record = []
        bands = intersite.band_stack(bands, [(m["site"], keys) for m, keys in zip(members, stack_keys)],
                                     dict(zip(ref_roles, reference)), ref["reject_factor"], ref["min_members"],
                                     stack_record, method=ref["method"])
    est = intersite.estimate(bands, outputs, inputs, reference, progress=progress, layout=res["scheme"])
    del arrays, bands
    timing = intersite.timing_check(est)
    for line in intersite.timing_text(timing):
        print(line)
    masks = mask_block(res, mask_record)
    if spans:
        for site, entry in masks["sites"].items():
            print(f"masks: {site} ({entry['role']}): {entry['windows_masked']} band windows masked over "
                  f"{len(mask_record)} bands")
        print(f"masks: {masks['windows_left_out']} band windows left out in all")
    else:
        print("masks: no applied entry holds a sample of the window; no window masked")
    for label, record, min_kept in (("stack", stack_record, ref.get("min_members")),
                                    ("base stack", base_record, (bstack or {}).get("min_members"))):
        if record is None:
            continue
        summary = stack_summary(record)
        print(f"{label}: {summary['windows_left_out']} of {summary['windows']} band windows left out with fewer "
              f"than {min_kept} member(s) kept; {summary['bands_left_out']} of {summary['bands']} bands left out")
        for site, values in summary["members"].items():
            print(f"{label} member {site}: rejected " + ", ".join(
                f"{r} median {v['median']:.4f} max {v['max']:.4f}" for r, v in values.items()) + " of its windows "
                "per band")
    base_block = None
    if bstack:
        if not polarity["flags"]:
            polarity["flags"] = intersite.polarity_summary(polarity["record"], [m["site"] for m in base_members],
                                                           roles)
        for f in polarity["flags"]:
            if f["flagged"]:
                fate = "left out of the stack" if f["site"] in polarity["dropped"] else "kept (--screen-polarity flag)"
                print(f"polarity: {f['site']} {f['channel']} median correlation {f['correlation']:+.3f} with the "
                      f"other members over {f['bands']} bands: flagged, {fate}")
        if not any(f["flagged"] for f in polarity["flags"]):
            print(f"polarity: no member flagged ({len(polarity['record'])} bands screened)")
        base_block = base_stack_block(res, base_members, base_record, polarity)
    out_dir = Path(res["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    stem, letter = res["stem"], res["tensor"]
    paths = {"csv": out_dir / f"{stem}.csv", "h5": out_dir / f"{stem}.h5", "figure": out_dir / f"{stem}.png",
             "json": out_dir / f"{stem}.json"}
    intersite.write_csv(est, letter, paths["csv"])
    base_text = (res["base"] if res["base"] else
                 f"the {bstack['field']} stack of {len(base_members) - len(polarity['dropped'])} member(s)")
    title = (f"{intersite.TENSOR_NAMES[letter]} of {res['local']} on {base_text}, reference {res['ref_label']}, "
             f"{_text_ns(res['window'][0])} to {_text_ns(res['window'][1])}")
    intersite.plot_estimate(est, letter, paths["figure"], title=title, timing=timing)
    finished = dt.datetime.now().astimezone()
    sidecar = build_sidecar(res, args, started, finished, est, timing, sources, members, paths, coverage,
                            stack_record, base_block, masks)
    attrs = {"kind": res["kind"], "local": res["local"],
             "base_site": res["base"] if res["base"] else f"none: the base is {res['base_label']}",
             "remote": res["ref_label"], "sidecar": paths["json"].name, "window_start": sidecar["window"]["start"],
             "window_end": sidecar["window"]["end"], "frames": json.dumps(sidecar["frames"])}
    if stack_record is not None:
        attrs.update({"stack_form": "band", "stack_reject_factor": ref["reject_factor"],
                      "stack_min_members": ref["min_members"], "stack_record": json.dumps(stack_record),
                      "stack_method": ref["method"]})
        if ref.get("recipe"):
            attrs.update({"stack_recipe": ref["recipe"], "stack_recipe_hash": ref["recipe_hash"]})
    if base_block is not None:
        attrs.update({"base_stack_form": "band", "base_stack_reject_factor": bstack["reject_factor"],
                      "base_stack_min_members": bstack["min_members"],
                      "base_stack_members": [m["site"] for m in base_block["members"] if not m["dropped"]],
                      "base_stack_record": json.dumps(base_record),
                      "base_stack_polarity": json.dumps(base_block["screen_polarity"]["flags"]),
                      "base_stack_method": bstack["method"]})
        if bstack.get("recipe"):
            attrs.update({"base_stack_recipe": bstack["recipe"], "base_stack_recipe_hash": bstack["recipe_hash"]})
    intersite.write_h5(est, letter, paths["h5"], attrs=attrs)
    write_sidecar(paths["json"], sidecar)
    for key in ("csv", "json", "h5", "figure"):
        print(f"{key}: {paths[key]}")


if __name__ == "__main__":
    main(build_parser().parse_intermixed_args())
