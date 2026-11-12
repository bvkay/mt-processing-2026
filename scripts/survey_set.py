# -*- coding: utf-8 -*-
"""
Set, change or remove keys of one site entry, or of defaults:, in survey.yaml

The edit goes through `mt_workbench.survey_file.edit`: only the lines of that
entry change, comments, blank lines and line endings stay, the file as it was
is kept as survey.yaml.previous, and a value equal to the one in `defaults:`
is not written into a site's entry (the key is removed instead).

Each value is read by the type `mt_workbench.survey.SiteConfig` gives its key:
a text key takes the text after `=` as typed (`serial=036` stays '036',
`notes=moved 20 m: east` stays one text), a number key must read as a number,
a true/false key takes `true` or `false` only, and a list key takes a YAML
list such as `[hy]`. `key=` with nothing after `=` removes the key. A key
that is not a site key of survey.yaml is refused.

A `defaults` edit changes what every site without its own key takes, so it
is a dry run that prints the sites it reaches unless `--yes` is given. A
change of a usual dipole length or azimuth writes the old value into each
site that took it, so no site's dipoles move.

Exit status: 0 written, nothing to change, or a dry run; 2 refused (the
message says why and what to do).

Usage:
    python scripts/survey_set.py <survey.yaml> SITE key=value [key=value ...] [--add]
    python scripts/survey_set.py <survey.yaml> defaults key=value [key=value ...] [--yes]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import fields
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import yaml  # noqa: E402

from mt_workbench import survey_file  # noqa: E402
from mt_workbench.survey import SiteConfig  # noqa: E402

# the declared type of each site key, as text ("float | None", "list[str] | None", ...)
KEY_TYPES = {f.name: str(f.type) for f in fields(SiteConfig) if f.name != "name"}


def parse_value(key: str, text: str):
    """Read the text typed after `key=` by the type of that key in `SiteConfig`.

    Args:
        key (str): The survey.yaml key.
        text (str): What follows the `=`.

    Returns:
        The value to write, or `survey_file.REMOVE` for an empty text.

    Raises:
        ValueError: If the key is not a site key or the text does not read
            as its type; the message says what to type.
    """
    if key not in KEY_TYPES:
        raise ValueError(f"{key!r} is not a site key of survey.yaml (see mt_workbench.survey.SiteConfig)")
    if text == "":
        return survey_file.REMOVE
    kind = KEY_TYPES[key]
    if kind.startswith("str"):
        return text
    if kind.startswith("float"):
        try:
            return float(text)
        except ValueError:
            raise ValueError(f"{key}={text}: a number wanted") from None
    if kind.startswith("bool"):
        if text not in ("true", "false"):
            raise ValueError(f"{key}={text}: true or false wanted")
        return text == "true"
    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError:
        value = None
    if not isinstance(value, list):
        raise ValueError(f"{key}={text}: a list wanted, written as [a, b]")
    return value


def main(argv=None) -> int:
    """Set, change or remove keys of one entry of a survey.yaml.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.

    Returns:
        int: 0 written, nothing to change or a dry run; 2 refused.
    """
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("survey_yaml", help="the survey.yaml")
    parser.add_argument("site", help="the site whose entry changes, or defaults for the defaults: block")
    parser.add_argument("values", nargs="+", metavar="key=value", help="key= with nothing after = removes the key")
    parser.add_argument("--add", action="store_true", help="make a new entry for SITE")
    parser.add_argument("--yes", action="store_true", help="write a defaults edit (without it: a dry run)")
    args = parser.parse_args(argv)

    path = Path(args.survey_yaml)
    if not path.is_file():
        print(f"ERROR {path} not found", file=sys.stderr)
        return 2
    if args.add and args.site == "defaults":
        print("ERROR --add makes a site entry; defaults: is edited without it", file=sys.stderr)
        return 2
    values = {}
    for item in args.values:
        key, equals, text = item.partition("=")
        try:
            if not equals:
                raise ValueError(f"{item!r}: key=value wanted")
            values[key] = parse_value(key, text)
        except ValueError as exc:
            print(f"ERROR {exc}; nothing written", file=sys.stderr)
            return 2

    dry_run = args.site == "defaults" and not args.yes
    request = ({"defaults": values} if args.site == "defaults" else
               {"add": {args.site: values}} if args.add else {"sites": {args.site: values}})
    try:
        result = survey_file.edit(path, dry_run=dry_run, **request)
    except survey_file.SurveyFileRefused as exc:
        print(f"ERROR {exc}", file=sys.stderr)
        return 2
    for line in result.summary:
        print(line)
    if not any(result.made.values()):
        print(f"nothing to change: {path.name} already reads as asked")
    elif dry_run:
        print("dry run: nothing written; add --yes to write it")
    else:
        print(f"wrote {path}; the file as it was: {result.previous}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
