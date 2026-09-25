# -*- coding: utf-8 -*-
"""
Channel naming rules for display

The archive keeps each reader's own channel names: a LEMI-423 or an Earth
Data PR6-24 (EDL) site holds hx hy hz ex ey, a LEMI-424 bx by bz e1 e2 e3 e4.
Everything the GUI draws goes through these rules. The module has no Qt
dependency.

* `kind`: electric when the name starts with e, magnetic when it starts with
  b or h, ignoring a remote's "r_" prefix. Any other channel (for example a
  temperature) is neither and is not drawn.
* `label`: Bx By Bz Ex Ey for the LEMI-423 and EDL names, Bx By Bz E1..E4 for
  the LEMI-424 names, the name itself otherwise; "rBx" for a remote coil.
* `order`: magnetics first, then electrics, each in name order, as the plots
  are stacked: hx hy ex ey; bx by bz e1 e2 e3 e4.
* `roles`: which channel plays Bx, By, Ex or Ey in the drawn pairs. The
  first two magnetics in name order are Bx and By and the first two
  electrics Ex and Ey, so on a LEMI-424 E1 stands in for Ex and E2 for Ey
  unless the electric-pair setting (aurora's LEMI12/LEMI34 nomenclature)
  says otherwise. Roles are keyed by the LEMI-423 names, so pair lists
  written in those names (`crust.timefreq.LOCAL_PAIRS`, `REMOTE_PAIRS`, the
  tabs' panels) resolve through `resolve`.
* `unit`: nT for a magnetic channel, mV/km for an electric one, as the
  readers label them. A LEMI-424 records its electrics in mV (see
  `crust.instruments`).

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import re

REMOTE = "r_"
LEMI423_LABELS = {"hx": "Bx", "hy": "By", "hz": "Bz", "ex": "Ex", "ey": "Ey"}
UNITS = {"magnetic": "nT", "electric": "mV/km"}
ROLE_NAMES = ("hx", "hy", "ex", "ey")  # the role keys: Bx, By, Ex, Ey in the LEMI-423 names
# a remote's two horizontal coils, whichever reader named them (`load_grid` keeps those present)
REMOTE_COMPS = ("hx", "hy", "bx", "by")


def kind(name: str) -> str | None:
    """Return 'magnetic' (b..., h...), 'electric' (e...) or None, ignoring a remote's "r_"."""
    first = str(name).removeprefix(REMOTE)[:1].lower()
    return "magnetic" if first in ("b", "h") else "electric" if first == "e" else None


def label(name: str) -> str:
    """Return the display label: 'Bx', 'Ey', 'E1', 'rBx' for a remote coil, other names unchanged."""
    if name.startswith(REMOTE):
        return "r" + label(name[len(REMOTE):])
    if name in LEMI423_LABELS:
        return LEMI423_LABELS[name]
    return name.capitalize() if re.fullmatch(r"b[xyz]|e\d", name) else name


def order(names) -> list[str]:
    """Return the local electric and magnetic names, magnetics first, each in name order."""
    names = list(names)
    return (sorted(n for n in names if kind(n) == "magnetic" and not n.startswith(REMOTE))
            + sorted(n for n in names if kind(n) == "electric" and not n.startswith(REMOTE)))


def unit(name: str) -> str:
    """Return 'nT', 'mV/km' or '' for a channel name."""
    return UNITS.get(kind(name), "")


def display(available, declared=None) -> list[str]:
    """Select the channels to draw from an archive.

    Args:
        available: Channel names in the archive.
        declared: Channel names asked for, or None.

    Returns:
        list[str]: The declared channels present, in `order`; all of them
        when none of the declared names match.
    """
    names = order(available)
    wanted = {str(c).lower() for c in declared or ()}
    return [n for n in names if n in wanted] or names


def roles(names, prefix: str = "") -> dict[str, str]:
    """Map each role to the channel that plays it.

    The first two magnetics in name order play hx and hy, the first two
    electrics ex and ey. A role no channel plays is left out.

    Args:
        names: Channel names of the record.
        prefix (str): Prefix added to the mapped names, "r_" for a remote.

    Returns:
        dict[str, str]: LEMI-423 role name to channel name.
    """
    local = [n.removeprefix(REMOTE) for n in names]
    mags = sorted(n for n in local if kind(n) == "magnetic")
    elecs = sorted(n for n in local if kind(n) == "electric")
    parts = dict(zip(("hx", "hy"), mags)) | dict(zip(("ex", "ey"), elecs))
    return {role: prefix + name for role, name in parts.items()}


def resolve(name: str, local: dict, remote: dict | None = None) -> str | None:
    """Return the channel playing a LEMI-423 role name; "r_hx" looks in the remote roles."""
    if name.startswith(REMOTE):
        return (remote or {}).get(name[len(REMOTE):])
    return local.get(name)


def resolve_pairs(pairs, local: dict, remote: dict | None = None) -> list[tuple[str, str]]:
    """Translate pairs written in LEMI-423 names into the record's own channel names.

    A pair with a role no channel plays is dropped.

    Args:
        pairs: (a, b) pairs in LEMI-423 names, "r_" for remote channels.
        local (dict): Local roles from `roles`.
        remote (dict | None): Remote roles from `roles`.

    Returns:
        list[tuple[str, str]]: The pairs in the record's names.
    """
    out = []
    for a, b in pairs:
        ra, rb = resolve(a, local, remote), resolve(b, local, remote)
        if ra and rb:
            out.append((ra, rb))
    return out


def title(template: str, local: dict, remote: dict | None = None) -> str:
    """Fill a title template with channel labels.

    '{hy}-{ex} (Zxy)' becomes 'By-Ex (Zxy)', or 'By-E1 (Zxy)' on a LEMI-424;
    '{r_hy}' names a remote coil.
    """
    keys = re.findall(r"{(\w+)}", template)
    return template.format(**{k: label(resolve(k, local, remote) or k) for k in keys})
