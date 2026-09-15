"""Channel names, whatever the reader called them: kind, label, order, unit and the pairs (no Qt).

The archive keeps each reader's own names: a LEMI-423
or an Earth Data PR6-24 (EDL) site holds hx hy hz ex ey, a LEMI-424 bx by bz
e1 e2 e3 e4. Everything the GUI draws goes through the rules here:

- `kind`   electric when the name starts with e, magnetic when it starts
           with b or h (a remote's "r_" ignored); anything else (a
           temperature) is neither and is not drawn.
- `label`  Bx By Bz Ex Ey for the LEMI-423/EDL names, Bx By Bz E1..E4 for
           the LEMI-424 ones, the name itself otherwise; a remote's "rBx".
- `order`  magnetics first, then electrics, each in name order (the MATLAB
           app's stack): hx hy ex ey; bx by bz e1 e2 e3 e4.
- `roles`  which channel plays which part in the MATLAB app's pairs: the
           first two magnetics in name order are Bx and By, the first two
           electrics Ex and Ey -- so on a LEMI-424 E1 stands in for Ex and E2
           for Ey, until the electric-pair setting (aurora's LEMI12/LEMI34
           nomenclature) says otherwise. Keyed by the LEMI-423 names, so the
           pair lists written in those names (`mtproc.timefreq.LOCAL_PAIRS`,
           `REMOTE_PAIRS`, the tabs' panels) resolve through `resolve`.
- `unit`   nT for a magnetic channel, mV/km for an electric one (what the
           readers label them; a LEMI-424's electrics are recorded mV -- see
           `mtproc.instruments`).
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
    """'magnetic' (b..., h...), 'electric' (e...) or None, a remote's "r_" ignored."""
    first = str(name).removeprefix(REMOTE)[:1].lower()
    return "magnetic" if first in ("b", "h") else "electric" if first == "e" else None


def label(name: str) -> str:
    """'Bx', 'Ey', 'E1', a remote coil 'rBx'; any other name as it is."""
    if name.startswith(REMOTE):
        return "r" + label(name[len(REMOTE):])
    if name in LEMI423_LABELS:
        return LEMI423_LABELS[name]
    return name.capitalize() if re.fullmatch(r"b[xyz]|e\d", name) else name


def order(names) -> list[str]:
    """The electric and magnetic names, magnetics first, each in name order; others left out."""
    names = list(names)
    return (sorted(n for n in names if kind(n) == "magnetic" and not n.startswith(REMOTE))
            + sorted(n for n in names if kind(n) == "electric" and not n.startswith(REMOTE)))


def unit(name: str) -> str:
    return UNITS.get(kind(name), "")


def display(available, declared=None) -> list[str]:
    """What to draw of an archive's channels: the declared ones present (all when none match), in `order`."""
    names = order(available)
    wanted = {str(c).lower() for c in declared or ()}
    return [n for n in names if n in wanted] or names


def roles(names, prefix: str = "") -> dict[str, str]:
    """{LEMI-423 name: the channel in that part}: the first two magnetics are hx, hy; the first two electrics ex, ey.

    `prefix` ("r_") names a remote's channels. A part no channel plays is left out.
    """
    local = [n.removeprefix(REMOTE) for n in names]
    mags = sorted(n for n in local if kind(n) == "magnetic")
    elecs = sorted(n for n in local if kind(n) == "electric")
    parts = dict(zip(("hx", "hy"), mags)) | dict(zip(("ex", "ey"), elecs))
    return {role: prefix + name for role, name in parts.items()}


def resolve(name: str, local: dict, remote: dict | None = None) -> str | None:
    """A LEMI-423 name from a pair list -> the channel playing it (`roles`); "r_hx" from the remote's."""
    if name.startswith(REMOTE):
        return (remote or {}).get(name[len(REMOTE):])
    return local.get(name)


def resolve_pairs(pairs, local: dict, remote: dict | None = None) -> list[tuple[str, str]]:
    """`pairs` in the LEMI-423 names -> the record's own pairs; a pair whose part nobody plays is dropped."""
    out = []
    for a, b in pairs:
        ra, rb = resolve(a, local, remote), resolve(b, local, remote)
        if ra and rb:
            out.append((ra, rb))
    return out


def title(template: str, local: dict, remote: dict | None = None) -> str:
    """'{hy}-{ex} (Zxy)' -> 'By-Ex (Zxy)', or 'By-E1 (Zxy)' on a LEMI-424 ("{r_hy}" a remote coil)."""
    keys = re.findall(r"{(\w+)}", template)
    return template.format(**{k: label(resolve(k, local, remote) or k) for k in keys})
