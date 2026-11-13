# The window (GUI)

This page covers the desktop window: how to start it and, tab by tab, what
each tab is for and what to do there.

## Start

```bash
python -m mt_workbench surveys/<survey>/survey.yaml
```

The console script `mt-workbench` does the same; without a survey file the
window opens empty. A tab shows data, edits one of the survey's YAML
files, or queues a script
([commands.md](commands.md)). Jobs run one at a time, and the Process tab
lists them.

## Metadata

Make a survey ("New survey...") or open one ("Open survey.yaml..."), and
read each site's `survey.yaml` entry, one row per site. The site column
stays at the left edge when the table is scrolled sideways. The `dc level`
column is red for an open input and yellow for a saturated channel.

- **New survey...** asks for the data folder (one folder per site), the
  survey name (30 characters at most, of letters, digits, `_` and `-`),
  the instrument ("auto (from the files)" takes the recorder most common
  among the site folders), the time zone, the usual dipole length and the
  usual azimuths of Ex and Ey in degrees from magnetic north, the electric
  gain of an EDL survey and the zone of the logger clocks of an Orange Box
  survey (both empty unless needed), and an optional site table. It runs
  `new_survey.py` ([commands.md](commands.md#make-a-survey)) and opens the
  survey it writes. For a survey that exists it runs nothing: open it and
  press "Add sites".
- **Edit** a cell by double-click. "Import site table..." fills cells from
  a CSV or XLSX and keeps a position a site already has. A value typed
  equal to the usual one in `defaults:` removes the site's own key.
- **Save survey.yaml** writes the changed cells into their sites' entries.
  The other lines and every comment stay, and the file as it was is kept
  as `survey.yaml.previous`. When another program holds the file open, or
  it is read-only, Save says so after about two seconds: close that
  program or clear the flag, and save again.
- **Add sites** adds an entry for each site folder that has none (a greyed
  row). It asks first with their names, runs `new_survey.py` again and
  changes nothing else. Save the table's edits first. A second deployment
  of a station goes in a folder of its own, such as `SA106_2`.
- **Check** lists what stops an ingest (STOP, red) and what to look at
  (WARN, yellow), one row per site and finding, as `check_survey.py`
  prints it. Double-click a row to select its site.
- **Ex and Ey swapped** and **Hx and Hy swapped** are tick boxes for a site
  whose two electric lines, or two horizontal coils, were connected to each
  other's inputs (`swap_e`, `swap_h`: [instruments.md](instruments.md)).
  Ingest exchanges the samples of the two channels; for the electric
  lines, give the lengths and azimuths of the lines as they are after the
  exchange. A tick reaches the data only when the archive is built again:
  press Save survey.yaml, then select the site and press Rebuild archive.
- **Rebuild archive** builds the selected site's archive again from its raw
  data, after a question (`ingest_site.py <survey.yaml> SITE --force`); a
  site with declared filters gets its filtered variant built again too. It
  needs a site with an entry, a raw data folder and an archive, and no job
  running.

## Time Series

Click a window under a site in the tree to load it: every channel at the
full sample rate, and the same window on the next three tabs. "Build MTH5"
ingests a site with no archive yet. "Use visible range as processing
window" sends the zoomed range to the Process tab.

## Spectra, Spectrogram and Coherence

Three views of the loaded window: Spectra (By with Ex and Bx with Ey, the
remote's coil in grey), Spectrogram (power against period and time per
channel) and Coherence (whether the window has signal, and whether the
remote chosen there sees the same field). Whole-record figures come from
`scripts/site_qc.py` and `scripts/psd_qc.py`.

## Filter Data

Build a site's filter list (Add, Remove, Move up, Move down), compare raw
and filtered on the loaded window, then "Save filters.yaml". Filters go
into a filtered copy of the archive, built when a run needs it; the raw
archive stays as recorded. The filter kinds: [products.md](products.md).

## Cross-powers

The impedance of a site against a remote, chunk by chunk and band by band.
Press "Compute", drag over the chunks that stand apart, press "Mask
selected", then "Save masks", which writes the site's block of
`masks.yaml`. A new mask has scope `local`: it applies when the site is the
local of a pair ([commands.md](commands.md), under `process_rr.py`).

## Stacks

Declare a stack recipe (sites, field, window, method) over a chart of every
site's runs, "Check" its members on the loaded window, and "Save recipe"
to `stacks.yaml`. "Build archive" queues `build_stack.py` for a time recipe
(press "Run queue" on the Process tab; the built archive becomes the remote
there unless the station is one of its members). "Use in Process" hands a
time or base recipe to the Process tab. A reference recipe runs from the
command line shown.

## Process

Choose the Processing type, the station, the remote reference and the
window, press "Add to queue", then "Run queue": adding and running are two
steps. The station box lists every raw folder and every declared site with
an archive ("A01  (archive)": no raw folder found, processed from its
archive); an observatory is a remote only.

| Processing type | "Add to queue" runs |
|---|---|
| MT impedance and tipper (the default) | `process_rr.py`, the station against the remote |
| Telluric tensor, E to E | `process_intersite.py --kind telluric`, the station's ex, ey on the base's |
| Magnetic tensor, B to B | `process_intersite.py --kind magnetic`, the station's hx, hy on the base's |

For MT, a band option is passed only when moved off the survey's
`processing:` value. "use declared filters" off adds `--no-filters`, "apply
masks.yaml" off adds `--no-masks`, and the engine `mantle` applies no
masks.

A tensor type shows a Base box: the sites with an archive at the station's
sample rate, then the base stacks saved on the Stacks tab ("stack: NAME").
The remote stays the reference, a third site. A tensor run takes
only the tag and the filters switch, and always applies `masks.yaml`.

"Add every site on this base" queues one run for every other site with an
archive at that rate (the remote left out), each with the same remote,
window, tag and filters switch; the status line names the sites left out
with the reason. A base stack takes one station at a time. A pair that
would be refused is not queued: a message says what is wrong and what to
do.

The tensor products and the network datum: [tensors.md](tensors.md).

## View EDIs

Lists the EDIs of `<workspace>/tf`, labelled by engine, and the reference
EDIs of `reference_edis.yaml`. Tick rows to overlay them; Quick view steps
through the list with the arrow keys. Plot adds the phase tensor or the
tipper (disabled when the sites declare no hz channel). Phase "-180 to 180
deg" shows the yx phase where it sits, so a mode out of its quadrant is
seen. A MANTLE product adds its verdict strip and "MANTLE notes...".

## View tensors

Lists the tensor products of `<workspace>/tf` under their local site, with
base, reference, tensor, tag and window. A product is listed by its
sidecar's `kind`, not its file name; one that cannot be read stays listed
with the reason. "Reload" reads the folder again, as does a
`process_intersite.py` job that ends without an error.

Choosing a row draws the figure the script writes as `<stem>.png`, over the
periods of the whole band layout: the magnitudes of the four elements (for
a magnetic tensor, of the tensor less the identity, so matched coils plot
near zero), their phases, and psi with its error bars and the line of the
timing check.

How to read psi and the magnitudes, and what raises each flag:
[tensors.md](tensors.md). A flagged period keeps its
place with an open marker, and each flag has its own marker in the psi
panel, counted in the legend. A period that was not estimated is absent;
the legend counts those.

The box under the list gives the
facts of the run from the sidecar, with each site's frame "as recorded, not
rotated" and the declination as a recorded number, not applied.
