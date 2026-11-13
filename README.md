# mt-workbench

mt-workbench processes magnetotelluric (MT) recordings of Adelaide Uni
surveys into transfer functions:

- MT impedance and tipper of a site
- Telluric tensor between two sites, E to E
- Magnetic tensor between two sites, B to B

It reads these recorders:

- LEMI-423
- LEMI-424
- Earth Data PR6-24
- Orange Box
- Phoenix MTU-5C and MTU-8A
- Phoenix MTU-5A

It is built on the IAGA-DVI stack
([mt-io](https://github.com/kujaku11/mt-io),
[mth5](https://github.com/IAGA-DVI-DataStandards/mth5),
[mt-metadata](https://github.com/IAGA-DVI-DataStandards/mt-metadata)) with
[aurora](https://github.com/simpeg/aurora) as the transfer-function engine.
Every job is a script, and a desktop window shows the data and queues the
scripts.

Design rules, in order:

1. **Thin.** mt-workbench wraps the community packages.
2. **Headless first.** Everything runs from a script or the command line; the desktop window (`src/mt_workbench/gui`) calls the same scripts.
3. **Decisions are data.** Noise masks, band choices and remote-reference pairs live in per-survey YAML/JSON files.

## Install

```bash
conda env create -f environment.yml
conda activate bbmt-2026
```

This makes the environment `bbmt-2026` (Python 3.11) and installs the package
editable (`mt-workbench`, import name `mt_workbench`). The MT libraries come
from five forks on GitHub: [docs/guide/install.md](docs/guide/install.md)
says which, why, and how to install a local clone of one.

## Start

```bash
python -m mt_workbench surveys/<survey>/survey.yaml
```

This opens the window (the GUI) on a survey file. Its tabs, left to right:

- **Metadata**: make or open a survey, and read and edit each site's entry in `survey.yaml`.
- **Time Series**: choose a site and a window and see every channel at full resolution; build a site's archive.
- **Spectra**: the power spectra of the loaded window.
- **Spectrogram**: the loaded window's power against period and time, channel by channel.
- **Coherence**: whether the loaded window has signal, and whether the remote sees the same field.
- **Filter Data**: try a site's filter list on the loaded window and declare it in `filters.yaml`.
- **Cross-powers**: the impedance chunk by chunk and band by band, and the time masks of `masks.yaml`.
- **Stacks**: declare stack recipes in `stacks.yaml` and check their members.
- **Process**: choose the processing type, the station, the remote and the window, and queue the scripts.
- **View EDIs**: plot the EDI products (apparent resistivity, phase and phase tensor).
- **View tensors**: plot the telluric tensor and magnetic tensor products.

[docs/guide/gui.md](docs/guide/gui.md) has more on each.

## The usual path through a survey

1. **Make a survey.** `python scripts/new_survey.py <data_root> --name NAME`
   reads a folder of site folders and writes `survey.yaml`; `--site-table`
   merges a field sheet. The Metadata tab does the same with "New survey...".
2. **Check it.** Read each site's entry on the Metadata tab. On LEMI-423
   files, `scripts/timing_qc.py <survey.yaml> <local> <remote>` checks the
   clocks and `scripts/noise_psd.py <survey.yaml> <site>` gives a first look
   at the noise. `scripts/declination.py <survey.yaml> --write` fills each
   site's declination.
3. **Ingest and look at the data.** `python scripts/ingest_site.py
   <survey.yaml> --all` writes each site's raw archive,
   `<workspace>/mth5/<site>.h5` (for one site, Build MTH5 on the Time Series
   tab). Look at windows on the Time Series, Spectra, Spectrogram and
   Coherence tabs, and at the whole record with `scripts/site_qc.py
   <survey.yaml> <site>`. Declare filters on the Filter Data tab and masks on
   the Cross-powers tab.
4. **Process.** On the Process tab choose the processing type, the station,
   the remote and the window, press Add to queue, then Run queue. The types:
   - MT impedance and tipper: `scripts/process_rr.py <survey.yaml> <local> <remote>`;
   - telluric tensor, E to E: `scripts/process_intersite.py <survey.yaml> <local> <base> --kind telluric --remote SITE`;
   - magnetic tensor, B to B: the same script with `--kind magnetic`.

   Every product is remote-referenced. `scripts/campaign.py` runs a whole
   line of sites from a plan file.
5. **View the products.** They are in `<workspace>/tf`. The View EDIs tab
   plots the EDIs and the View tensors tab the tensor products.
6. **Deliver.** `scripts/merge_modes.py` and `scripts/merge_best.py` join
   products of one site into one EDI, and `scripts/deliver_as_laid.py
   <survey.yaml> <in.edi> <out.edi>` writes the delivered EDI with each
   reversed electric line as laid.

## House rules of the data

- **As recorded.** Data and products stay in the frame the sensors were laid
  out in: geomagnetic coordinates for a layout to magnetic north, the
  default. Processing applies no rotation. A declination is recorded with
  every product and never applied.
- **Flags.** A flag marks a period and never removes it.
- **Full band.** Every transfer function is estimated over the survey's full
  band layout. A narrower band is chosen when a product is read, not when it
  is estimated.
- **A lean survey file.** `survey.yaml` holds the facts of the deployment.
  Noise decisions go in `filters.yaml` and `masks.yaml`, stack recipes in
  `stacks.yaml`, and everything a run writes goes in the workspace.

## Where things live

```
src/mt_workbench/      the package: survey.py, instruments.py, ingest.py, process.py,
                       compare.py, bands.py, qc.py, timefreq.py, virtual.py and more
src/mt_workbench/gui/  the window: a launcher and viewer over scripts/ and
                       survey.yaml
scripts/               the student-facing command line, one job each
tests/                 unit tests, plus the tests of the window
docs/guide/            the topic pages listed below
docs/                  the issue logs and the work log
surveys/<name>/        one folder per survey: survey.yaml (config), filters.yaml,
                       reference_edis.yaml
```

The raw recordings are read from the folder that `data_root:` in `survey.yaml`
names, one folder per site. Everything a run writes goes to the survey's
workspace (`workspace:`, which `new_survey.py` sets to `<data_root>/work`):
the archives in `mth5/`, the products in `tf/`, the figures in `qc/`, and
`campaign/`, `datum/` and `logs/`.

## Read more

- [install.md](docs/guide/install.md): the environment and the forked libraries.
- [commands.md](docs/guide/commands.md): the scripts, each with its usage and what it writes.
- [products.md](docs/guide/products.md): the workspace, archives, product names, frame and declination.
- [instruments.md](docs/guide/instruments.md): the recorders, how each is read, and the ingest keys of `survey.yaml`.
- [gui.md](docs/guide/gui.md): the window, the processing types and the tensor view.
- [tensors.md](docs/guide/tensors.md): the telluric and magnetic tensors between sites, and the network datum.
- [campaigns.md](docs/guide/campaigns.md): a processing campaign over a line of sites.
- [tests.md](docs/guide/tests.md): the test list.

## Tests

Each test file runs on its own; a test of the window needs an offscreen Qt
platform:

```bash
python tests/survey_unit.py
QT_QPA_PLATFORM=offscreen python tests/gui_smoke.py
```

The list, with what each test checks, is [docs/guide/tests.md](docs/guide/tests.md).
