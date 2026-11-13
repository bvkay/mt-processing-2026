# -*- coding: utf-8 -*-
"""
The check of a survey before ingest: what stops it and what is doubtful

`check_survey` goes through a loaded survey site by site and returns one
`Finding` for each gap: a level ("stop" when the ingest of that site fails
or gives wrong products, "warn" when the student should look), a name from
`LEVELS`, and a message that says what is wrong and what to do. It lists the
data folder once (`Survey.site_dirs`, which tells a site folder by its
files) and tests whether a site's archive ``<workspace>/mth5/<site>.h5``
exists. It opens no other file of the data and writes no file.

A site is checked by its kind. A recorded site has every check. A derived
site (`derived_from:`) and an observatory are made from an archive and
have no row on a field sheet, so only their own entry, declination, notes
and `remote:` are checked. A burst site (`bursts_of:`) takes its recorded
site's settings, so only its own entry and its `remote:` are checked. A
site folder with no entry is listed, and its name checked.

`usual_dipoles` counts the recorded sites that take the usual dipole
lengths and azimuths of `defaults:`, and `usual_dipoles_text` is the line
that says so. scripts/check_survey.py prints the findings.

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

from .survey import OBSERVATORY, SiteConfig, Survey, _window_time, check_site_name
from .survey_file import DIPOLE_KEYS

STOP, WARN = "stop", "warn"
# every finding and its level; scripts/check_survey.py prints the stops first, each level in this order
LEVELS = {
    "data_root_missing": STOP,
    "site_refused": STOP,
    "site_name": STOP,
    "folder_without_entry": WARN,
    "entry_without_folder": WARN,
    "no_position": WARN,
    "no_declination": WARN,
    "span_suspect": WARN,
    "orangebox_full_scales": STOP,
    "phoenix_calibration": STOP,
    "dipoles_not_set": WARN,
    "dipoles_not_perpendicular": WARN,
    "remote_unknown": WARN,
}
# a record longer than this is taken for a wrong clock or a wrong stamp, in days
SPAN_MAX_DAYS = 400.0
# how far from a right angle the two electric lines may be laid, in degrees
AZIMUTH_TOLERANCE = 20.0
# the sentence scripts/new_survey.py once wrote into the notes of every site it made
OLD_DIPOLE_NOTE = "dipole lengths and azimuths from defaults - set them from the field sheet"


@dataclass(frozen=True)
class Finding:
    """One gap the check found.

    Attributes:
        site (str | None): The site; None for the survey as a whole.
        name (str): A key of `LEVELS`.
        level (str): "stop" or "warn".
        message (str): What is wrong and what to do.
    """

    site: str | None
    name: str
    level: str
    message: str


def _entry(survey: Survey, name: str) -> dict:
    """Return a site's own entry; {} for a bare header and for an entry that is not a block of keys."""
    entry = (survey.config.get("sites") or {}).get(name)
    return entry if isinstance(entry, dict) else {}


def _recorded(entry: dict) -> bool:
    """True for an entry with raw files of its own: not derived, not a burst site, not an observatory."""
    return not (entry.get("derived_from") or entry.get("bursts_of") or entry.get("instrument") == OBSERVATORY)


def _survey_yaml(survey: Survey) -> str:
    """Return the survey.yaml path as a command takes it: forward slashes, quoted when it holds a blank."""
    text = (survey.config_dir / "survey.yaml").as_posix()
    return f'"{text}"' if " " in text else text


def _north(layout_north) -> str:
    """Return the north the azimuths are counted from, in words."""
    return "geographic north" if layout_north == "geographic" else "magnetic north"


def _number(value) -> str:
    """Return a number written short (50.0 as 50); any other value as it is."""
    return f"{value:g}" if isinstance(value, (int, float)) and not isinstance(value, bool) else str(value)


def _name_message(name: str) -> str | None:
    """Return why a site name is refused (`mt_workbench.survey.check_site_name`), None for a name every store takes."""
    try:
        check_site_name(name)
    except ValueError as exc:
        return str(exc)
    return None


def _span_message(survey: Survey, config: SiteConfig) -> str | None:
    """Return the message of a span that ends before it starts, is too long or does not read as two times."""
    if not config.start or not config.end:
        return None
    try:
        days = (_window_time(config.end) - _window_time(config.start)).total_seconds() / 86400.0
    except ValueError:
        length = "not two times"
    else:
        if 0.0 < days <= SPAN_MAX_DAYS:
            return None
        length = f"{days:.4g} days"
    return (f"span {config.start} to {config.end} ({length}) looks wrong: check the logger clock and the file "
            f"stamps, then python scripts/survey_set.py {_survey_yaml(survey)} {config.name} start=... end=...; "
            f"fix it before running declination.py, which takes the span's midpoint")


def _phoenix_message(survey: Survey, config: SiteConfig) -> str | None:
    """Return the message of a Phoenix site without a receiver calibration, as ingest would look for it.

    A relative `calibration_dir` is looked for in the survey folder, then
    under `data_root`, as `mt_workbench.ingest._calibration_dir` does.
    """
    serial = config.serial or "<serial>"
    files = f"the receiver's {serial}_*.rxcal.json and the coils' <serial>_*.scal.json files"
    if not config.calibration_dir:
        return (f"calibration_dir is not set: copy {files} into a folder sensors beside survey.yaml, then "
                f"python scripts/survey_set.py {_survey_yaml(survey)} defaults calibration_dir=sensors --yes")
    folder = Path(config.calibration_dir)
    if not folder.is_absolute():
        folder = next((c for c in (survey.config_dir / folder, survey.data_root / folder) if c.is_dir()),
                      survey.config_dir / folder)
    if folder.is_dir() and any(folder.glob(f"{config.serial or '*'}_*.rxcal.json")):
        return None
    return f"no receiver calibration for {serial} in {folder}: copy {files} there"


def _azimuth_message(config: SiteConfig) -> str | None:
    """Return the message of two electric lines that are not laid about 90 degrees apart."""
    try:
        apart = (float(config.azimuth_ey) - float(config.azimuth_ex)) % 180.0
    except (TypeError, ValueError):
        apart = None
    if apart is not None and abs(apart - 90.0) <= AZIMUTH_TOLERANCE:
        return None
    return (f"Ex azimuth {_number(config.azimuth_ex)} and Ey azimuth {_number(config.azimuth_ey)} (deg from "
            f"{_north(config.layout_north)}) are not about 90 deg apart: check the field sheet (a serial typed "
            f"in the azimuth column, or the same direction twice)")


def _stack_names(survey: Survey) -> set[str]:
    """Return the names of the recipes in the survey's stacks.yaml; empty when it cannot be read."""
    # imported here: mt_workbench.stacks loads mth5, which no other part of the check needs
    from .stacks import StacksError, load_recipes

    try:
        valid, errors = load_recipes(survey)
    except (StacksError, OSError):
        return set()
    return set(valid) | set(errors)


def _settings_findings(survey: Survey, config: SiteConfig, recorded: bool, instrument: str) -> list[tuple]:
    """Return (name, message) for each gap in the merged settings of a site that is not a burst site."""
    out = []
    yaml_path = _survey_yaml(survey)
    placed = config.latitude is not None and config.longitude is not None
    if recorded and not placed:
        out.append(("no_position", "has no position: set latitude and longitude from the field sheet "
                                   "(declination, the map and remote distances need it)"))
    if placed and config.start and config.declination is None:
        out.append(("no_declination",
                    f"has no declination: run python scripts/declination.py {yaml_path} {config.name} --write "
                    f"(command line; leave the site out to fill every site, which also recomputes those already "
                    f"set); the value is recorded with the products and is never applied to the data"))
    if recorded and (message := _span_message(survey, config)):
        out.append(("span_suspect", message))
    if recorded and instrument == "orangebox" and None in (config.electric_full_scale_uv,
                                                           config.magnetic_full_scale_nt):
        out.append(("orangebox_full_scales",
                    f"Orange Box full scales not set: uncomment electric_full_scale_uv and magnetic_full_scale_nt "
                    f"in defaults: of survey.yaml and set them from the field notes (25000 uV for the +/-2.5 V "
                    f"boxes before July 2010, 100000 for the +/-10 V ones; 70000 or 100000 nT), or python "
                    f"scripts/survey_set.py {yaml_path} defaults electric_full_scale_uv=25000 "
                    f"magnetic_full_scale_nt=70000 --yes"))
    if recorded and instrument == "phoenix" and (message := _phoenix_message(survey, config)):
        out.append(("phoenix_calibration", message))
    if OLD_DIPOLE_NOTE in str(config.notes or ""):
        out.append(("dipoles_not_set", "notes say the dipoles were never set from the field sheet: set them, or "
                                       "confirm the usual values and remove that sentence"))
    if recorded and (message := _azimuth_message(config)):
        out.append(("dipoles_not_perpendicular", message))
    return out


def check_survey(survey: Survey, raw_sites: dict[str, Path] | None = None) -> list[Finding]:
    """List what stops an ingest of the survey's sites and what is doubtful.

    The survey-wide finding comes first, then the sites of `sites:` in file
    order, then the site folders with no entry. With `data_root` not found
    the two folder findings are left out, since no folder can be listed.

    Args:
        survey (Survey): The survey, as loaded from its survey.yaml.
        raw_sites (dict[str, Path] | None): Site name to data folder, when
            the caller holds the map of `Survey.site_dirs` already; None
            lists the data folder here.

    Returns:
        list[Finding]: One per gap; empty when the check found none.
    """
    found: list[Finding] = []

    def add(site, name, message):
        found.append(Finding(site, name, LEVELS[name], message))

    have_root = survey.data_root.is_dir()
    if not have_root:
        add(None, "data_root_missing", f"data folder {survey.data_root} not found: connect the drive, or correct "
                                       f"data_root in survey.yaml")
    folders = (survey.site_dirs() if raw_sites is None else raw_sites) if have_root else {}
    names = survey.site_names()
    stacks = None
    for name in names:
        own = (survey.config.get("sites") or {}).get(name)
        if not isinstance(name, str):
            add(str(name), "site_name", f"site {name} is written as a number in survey.yaml ({name}:): put it in "
                                        f"quotes by hand ('{name}':)")
            continue
        if own is not None and not isinstance(own, dict):
            add(name, "site_refused", f"the entry of {name} in survey.yaml is the value {own!r}, not a block of "
                                      f"key: value lines: check the indentation of the lines around it")
            continue
        entry = _entry(survey, name)
        recorded = _recorded(entry)
        try:
            config, instrument = survey.site(name), survey.instrument_of(name)
        except ValueError as exc:
            add(name, "site_refused", str(exc))
            config = None
        except (TypeError, AttributeError) as exc:
            add(name, "site_refused", f"{name}: a value in its entry has the wrong kind ({exc}): compare each "
                                      f"key of the entry with another site's")
            config = None
        if recorded and (message := _name_message(name)):
            add(name, "site_name", message)
        archive = survey.workspace / "mth5" / f"{name}.h5"
        if recorded and have_root and name not in folders and not archive.exists():
            add(name, "entry_without_folder", "has an entry but no data folder under data_root and no archive: "
                                              "check the folder name")
        if config is None:
            continue
        if not entry.get("bursts_of"):
            for finding, message in _settings_findings(survey, config, recorded, instrument):
                add(name, finding, message)
        remote = config.remote
        if remote and remote not in names and remote not in folders:
            stacks = _stack_names(survey) if stacks is None else stacks
            if remote not in stacks:
                add(name, "remote_unknown", f"remote {remote} is not a site of this survey: the Process tab will "
                                            f"ignore it; correct the name, or remove it with python "
                                            f"scripts/survey_set.py {_survey_yaml(survey)} {name} remote=")
    for name in sorted(set(folders) - {str(n) for n in names}):
        if message := _name_message(name):
            add(name, "site_name", message)
        add(name, "folder_without_entry", "has a data folder but no entry: press Add sites (or run new_survey.py "
                                          "again)")
    return found


def usual_dipoles(survey: Survey) -> tuple[int, int]:
    """Count the recorded sites that take the usual dipoles and those with a dipole key of their own.

    A site has a dipole key of its own when its entry holds any of
    `mt_workbench.survey_file.DIPOLE_KEYS`. Derived sites, burst sites and
    observatories are not counted: no field sheet has a row for them.

    Args:
        survey (Survey): The survey.

    Returns:
        tuple[int, int]: (sites with no dipole key of their own, sites with one).
    """
    own = [any(key in _entry(survey, name) for key in DIPOLE_KEYS)
           for name in survey.site_names() if _recorded(_entry(survey, name))]
    return own.count(False), own.count(True)


def usual_dipoles_text(survey: Survey) -> str:
    """Return the line that says how many sites take the usual dipoles, and what the file cannot tell.

    The usual values are those of `defaults:`, or the built-in ones of
    `SiteConfig` for a key `defaults:` does not hold.

    Args:
        survey (Survey): The survey.

    Returns:
        str: The line scripts/check_survey.py prints below the findings.
    """
    built_in = {f.name: f.default for f in fields(SiteConfig)}
    usual = {key: survey.defaults.get(key, built_in[key]) for key in (*DIPOLE_KEYS, "layout_north")}
    without, with_own = usual_dipoles(survey)
    return (f"dipoles and azimuths: {without} site(s) have no dipole key of their own and take "
            f"{_number(usual['dipole_length_ex'])}/{_number(usual['dipole_length_ey'])} m, "
            f"{_number(usual['azimuth_ex'])}/{_number(usual['azimuth_ey'])} deg from "
            f"{_north(usual['layout_north'])}; {with_own} have their own. A site entered as usual looks the same "
            f"as one never entered: compare the first number with the field sheets.")
