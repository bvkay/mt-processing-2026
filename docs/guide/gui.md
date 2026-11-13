# The window (GUI)

This page covers the desktop window: how to start it, what each tab holds,
how the Process tab chooses what to process, and how a tensor product is
viewed.

## Start

```bash
python -m mt_workbench surveys/<survey>/survey.yaml
```

The installed console script `mt-workbench surveys/<survey>/survey.yaml` does the same.

## What the window holds

A desktop launcher and viewer over the scripts ([commands.md](commands.md)) and each survey's YAML,
with:

- a Metadata tab listing each site's survey.yaml entry, its archive and,
in its dc level column, the raw DC level the ingest recorded: per channel
the verdict and median in counts ("hx ok 4.30e7, ..., ey open input?
1.60e9"), the most severe verdict of its runs with the number of runs when
only some have it, red with an open input and yellow with a saturated
channel, every run in the tooltip, and "-" for an archive built before the
ingest recorded it (scripts/dc_level_check.py reads those),
- a site/window tree on the Time Series tab (2 h windows at 1000 Hz,
4 h at 500 Hz),
- live Spectra,
Spectrogram and Coherence views that compute only through `mt_workbench.timefreq` on
the loaded window,
- a Filter Data tab that previews the site's filter list on
a loaded window (raw behind filtered, time series and PSD) and drives
`<survey>/filters.yaml`,
- a Stacks tab that declares stack recipes in
`<survey>/stacks.yaml` (sites, field, window, method; written only at Save
recipe) over a chart of every site's runs and checks the members on the
loaded window through `mt_workbench.stackcheck` (Build archive and Use in
Process hand the recipe to the Process tab's queue and recipe picker),
- a Process tab (rows of station and remote, window bar, queue buttons, options
and queue) that queues the scripts
as subprocesses (Add to queue, then Run queue as a separate step;
its Engine combo, aurora or mantle, becomes `--engine mantle`, the queue
label carries "[mantle]" and, when the pair declares masks, `--no-masks`
goes with it and the status line says so; beside min period, max period,
periods per decade and the notches, window samples, min bin and min band
windows start at the survey's `processing:` values (min bin at 0, read
"layout's own", when the survey gives no `min_bin:`; min band windows at
`MIN_BAND_WINDOWS`, 2, when it gives no `min_band_windows:`) and pass
`--window-samples`, `--min-bin` and `--min-band-windows` only when moved
off them, min bin 0 over a survey's `min_bin:` passing `--min-bin 0`;
min band windows is disabled under mantle) and lists as stations every raw
folder and every declared site that has an archive, a site without a raw
folder labelled by its kind: a recorded site whose raw folder is not found
under `data_root` reads "A01  (archive)" and is processed from its archive,
its declared filters applied as with the folder present; a declared derived
or burst site with an archive is a station too ("B01L  (derived from B01,
1 Hz)", "G5H  (bursts of G5, 24000 Hz)"), also on
a survey whose raw folders are present; an observatory is a
remote only),
- a Build MTH5 button on the Time Series tab for a site with no archive yet,
- a satellite basemap under the Process tab's site map, fetched when a survey
is opened,
- and a View EDIs tab drawn with mtpy-v2, which labels each product
by its sidecar's engine ("[aurora]", "[mantle]", "[mantle fine grid]") and,
for a MANTLE product, draws its verdict strip under the resistivity panels
from `<stem>.mantle_report.json` (one row per verdict word over the periods
it covers), shows the sidecar's verdict word counts and opens the report's
notes as plain text (`src/mt_workbench/gui/mantle_products.py`).

**No product** (archive, transfer
function, EDI, report figure) is computed in the GUI, and no PNG is ever
displayed in it. Full detail: `src/mt_workbench/gui/README.md` (a local file that git does not track).

## Processing type: MT, telluric tensor or magnetic tensor

The first box of the Process tab, Processing type, chooses what Add to
queue runs:

- "MT impedance and tipper" (the default): `scripts/process_rr.py` for the
  station against the remote ([commands.md](commands.md)).
- "Telluric tensor, E to E": `scripts/process_intersite.py --kind telluric`,
  the station's ex, ey on the base's ex, ey.
- "Magnetic tensor, B to B": `scripts/process_intersite.py --kind magnetic`,
  the station's hx, hy on the base's hx, hy.

A tensor type shows a Base box. The tensor and psi = arg(det) / 2 are the
station's field relative to the base's field, so a product is always read
against its base, and another base gives another tensor. Both are in each
site's channels as recorded, in geomagnetic coordinates: no rotation is
applied, and a declination is a recorded number that is not applied. The
Base box lists the survey.yaml sites that have an archive at the station's
sample rate, then the base stacks saved on the Stacks tab for the tensor's
field, as "stack: NAME". The remote stays the reference: a third site, to
whose hx, hy the estimate is referenced.

To queue one pair, choose the type, the station, the remote and the base,
set the window on the bar and press Add to queue, then Run queue. To queue
a star of pairs around one base, choose a base site and press "Add every
site on this base": it queues one run for every other site that has an
archive at that sample rate, with the same remote, window, tag and filters
switch. The base and the remote are left out, and so is every site the
script would refuse, such as a site that records nothing in the window;
the status line counts the runs queued and names the sites left out under
each reason. A base stack takes one station at a time. A pair the script
would refuse is never queued: a message says what is wrong and what to do
next. A tensor run takes the tag and the "use declared filters" switch;
the other run options are greyed meanwhile, since process_intersite.py
estimates on the survey's band layout with its own estimator and always
applies masks.yaml.

A finished run writes four files to `<workspace>/tf` and lists them under
Products: `<station>_te-<base>_rr-<remote>.csv` (one row per period; the
flag columns mark a period and never remove it), `.json` (the facts of the
run), `.h5` and `.png`, with `_hm-` in place of `_te-` for the magnetic
tensor and `_<tag>` at the end with a tag. A second run of the same pair
with the same tag replaces the first. No EDI is written.

Planning the pairs of a network (which base for which site, and the pairs
that tie the groups together) and solving the network datum are run from
the command line for now: `scripts/solve_datum.py`, under "The network
datum" in [tensors.md](tensors.md).

## Viewing a tensor product

The window's View tensors tab, after View EDIs, lists the telluric tensor
and magnetic tensor products of the survey's `<workspace>/tf` folder: every
stem that has a `.csv` and a `.json` sidecar whose `kind` is telluric or
magnetic. The sidecar decides, not the file name, and an EDI product is
never listed. Each product is one row under its local site, with the base
(a site, or the stack's name), the reference, the tensor, the tag and the
window. Reload reads the folder again, and the tab does so itself when a
`process_intersite.py` job of the queue has finished. A product whose
sidecar or CSV cannot be read stays in the list with the reason and what
to do about it.

Choosing a row draws the product. It is the figure
`scripts/process_intersite.py` writes as `<stem>.png`, drawn from the CSV
by the same function (`mt_workbench.intersite.draw_estimate`), in three
panels over one log period axis that spans the whole band layout:

1. the magnitudes of the four elements xx, xy, yx and yy. For a magnetic
   tensor it is the magnitude of M less the identity, so two matched coils
   plot near zero and a 1 % gain difference plots at 0.01;
2. the phases of the four elements, in degrees;
3. psi = arg(det) / 2, in degrees, with its jackknife error bars and the
   line of the timing check over the periods it fitted.

psi is relative to the base. It is the phase of the local site's field
less the base's (half the phase of the determinant of the tensor), and a
value of psi means something only with its base named: two products of one
local on two bases differ by the phase between the bases. On a stack as
the base the magnitudes are in each period's normalised units and are not
field ratios; the box beside the figure gives the sidecar's own words on
the units.

A flag marks a period and never removes it. A flagged period keeps its
place on every curve with an open marker, and in the third panel each flag
adds a marker of its own, named in the legend under the figure with its
number of periods: few jackknife groups, low coherence, off-diagonal, and
Re det < 0. A period that was not estimated has no value and is absent;
the legend counts those periods, and the period axis still runs to the end
of the layout. Every point stays in view, and a long error bar may run off
its panel.

No rotation and no correction is applied, in the tab or in the product:
each element is in the two sites' channels as recorded (geomagnetic
coordinates for a layout to magnetic north). The box beside the figure
gives the facts of the run from the sidecar: local, base, reference,
window and tag, the periods estimated and the periods under each flag, the
`masks.yaml` entries applied, each site's frame under the words "as
recorded, not rotated" (the azimuths of ex and ey, the layout's north, and
the declination as a recorded number that is not applied), and whether the
timing check determined a delay.
