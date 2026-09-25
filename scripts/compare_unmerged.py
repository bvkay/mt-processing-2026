# -*- coding: utf-8 -*-
"""
Compare an aurora EDI with every unmerged lemimt EDI of one site

lemimt (LEMI's own processing program) writes one EDI per decimation rate
and, at the higher rates, one per chunk of the record:
``MT-<site>_RR-<remote>_<rate>Hz[_<chunk>].edi``, e.g.
``MT-D7_RR-D9_1000Hz_3.edi``, ``MT-D7_RR-D9_125Hz.edi``. Each file covers the
band that rate resolves. The script overlays aurora's single EDI on all of
them, coloured by rate, to show which settings the broadband data needs to
reproduce lemimt's result, and prints a table of the median differences per
rate. Unreadable EDIs are skipped with a warning.

Site matching: lemimt's site name is the survey's with leading zeros dropped
after the letter (D07 -> D7), matched case-insensitively; ``--remote`` does
the same to the RR- name. Without ``--remote``, every remote found for the
site is used, and the legend says so.

Usage:
    python scripts/compare_unmerged.py <aurora.edi> <unmerged_dir> <site> \
        [--remote NAME] [--out PNG] [--title TEXT]

@author: ben kay (ben@auscope.org.au)

:license: MIT
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from loguru import logger

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from crust.compare import rho_phi  # noqa: E402

# a dark-neutral look, defined here so the headless script depends on matplotlib alone
plt.rcParams.update({
    "figure.facecolor": "#1f1f1f", "figure.edgecolor": "#1f1f1f",
    "axes.facecolor": "#1f1f1f", "axes.edgecolor": "#c8c8c8",
    "axes.labelcolor": "#e6e6e6", "axes.titlecolor": "#e6e6e6",
    "text.color": "#e6e6e6",
    "xtick.color": "#c8c8c8", "ytick.color": "#c8c8c8",
    "grid.color": "#4a4a4a",
    "legend.facecolor": "#1f1f1f", "legend.edgecolor": "#555555", "legend.labelcolor": "#e6e6e6",
    "savefig.facecolor": "#1f1f1f", "savefig.edgecolor": "#1f1f1f",
})

AURORA_XY_COLOUR = "#4fc3f7"  # cyan-blue, matches the GUI's magnetics colour
AURORA_YX_COLOUR = "#ff5252"  # red, matches the GUI's electrics colour

UNMERGED_RE = re.compile(
    r"^MT-(?P<site>[A-Za-z0-9]+)_RR-(?P<remote>[A-Za-z0-9]+)_(?P<rate>\d+)Hz(?:_(?P<chunk>\d+))?\.edi$",
    re.IGNORECASE,
)


def normalise_site(name: str) -> str:
    """Normalise a site name to lemimt's naming.

    Drops leading zeros after the letter(s) and upper-cases: D07 -> D7,
    d07 -> D7, D007 -> D7, R06 -> R6. A name that is not letters followed by
    digits is upper-cased only.

    Args:
        name (str): Site or remote name.

    Returns:
        str: The normalised name.
    """
    m = re.match(r"^([A-Za-z]+)(\d+)$", name.strip())
    if not m:
        return name.strip().upper()
    letters, digits = m.groups()
    return f"{letters.upper()}{int(digits)}"


def find_unmerged(unmerged_dir: Path, site: str, remote: str | None = None) -> list[dict]:
    """Find the unmerged EDIs of a site in a folder.

    Args:
        unmerged_dir (Path): Folder of lemimt's unmerged EDIs.
        site (str): Site name, in either naming.
        remote (str | None): Remote name to filter on; every remote when None.

    Returns:
        list[dict]: One entry per file with path, rate (int, Hz), chunk (int
        or None) and remote (as found in the file name, not normalised).
    """
    target_site = normalise_site(site)
    target_remote = normalise_site(remote) if remote else None
    found = []
    for path in sorted(unmerged_dir.glob("*.edi")):
        m = UNMERGED_RE.match(path.name)
        if not m:
            continue
        if normalise_site(m.group("site")) != target_site:
            continue
        file_remote = m.group("remote")
        if target_remote is not None and normalise_site(file_remote) != target_remote:
            continue
        found.append({
            "path": path,
            "rate": int(m.group("rate")),
            "chunk": int(m.group("chunk")) if m.group("chunk") else None,
            "remote": file_remote,
        })
    return found


def load_unmerged(entries: list[dict]) -> dict[int, list[dict]]:
    """Read each matched file with `rho_phi`, grouped by rate.

    A file that fails to read is skipped with a logged warning.

    Args:
        entries (list[dict]): Entries from `find_unmerged`.

    Returns:
        dict[int, list[dict]]: Entries by rate, each extended with period,
        rho, phi, rho_err and phi_err.
    """
    by_rate: dict[int, list[dict]] = defaultdict(list)
    for entry in entries:
        try:
            period, rho, phi, rho_err, phi_err = rho_phi(entry["path"])
        except Exception as exc:  # noqa: BLE001 - a bad lemimt EDI is skipped and the run continues
            logger.warning(f"skip {entry['path'].name}: {exc!r}")
            continue
        by_rate[entry["rate"]].append({
            **entry, "period": period, "rho": rho, "phi": phi,
            "rho_err": rho_err, "phi_err": phi_err,
        })
    return by_rate


def diff_table(aurora_period, aurora_rho, aurora_phi, by_rate: dict[int, list[dict]]):
    """Compute the median differences between aurora and lemimt per rate.

    Aurora is interpolated in log period onto each lemimt point's period;
    the medians are of |d log10 rho| and |d phase| (deg).

    Args:
        aurora_period (np.ndarray): Aurora periods in seconds.
        aurora_rho (np.ndarray): Aurora apparent resistivity, (nf, 2, 2).
        aurora_phi (np.ndarray): Aurora phase in degrees, (nf, 2, 2).
        by_rate (dict[int, list[dict]]): Output of `load_unmerged`.

    Returns:
        tuple[list[dict], dict]: (rows, overall). Each is a dict with rate
        (rows only), n_files, and xy_n/xy_rho/xy_phi, yx_n/yx_rho/yx_phi.
    """
    order = np.argsort(aurora_period)
    log_p_a = np.log10(aurora_period)[order]
    with np.errstate(divide="ignore"):
        # xx/yy are not used below; a zero there (an unset diagonal, as in a
        # synthetic test TF) would otherwise warn about an unused log10
        log10_rho_a = np.log10(aurora_rho)[order]
    phi_a = aurora_phi[order]

    rows = []
    pooled = {"xy": {"rho": [], "phi": []}, "yx": {"rho": [], "phi": []}}
    for rate in sorted(by_rate, reverse=True):
        entries = by_rate[rate]
        period = np.concatenate([e["period"] for e in entries])
        rho = np.concatenate([e["rho"] for e in entries])
        phi = np.concatenate([e["phi"] for e in entries])
        log_p_t = np.log10(period)

        row = {"rate": rate, "n_files": len(entries)}
        for mode, (i, j) in (("xy", (0, 1)), ("yx", (1, 0))):
            rho_a_interp_log = np.interp(log_p_t, log_p_a, log10_rho_a[:, i, j])
            phi_a_interp = np.interp(log_p_t, log_p_a, phi_a[:, i, j])
            with np.errstate(divide="ignore"):
                # a real lemimt point can be exactly zero at a dead period;
                # the resulting inf is a real (large) disagreement, so only
                # the warning is suppressed
                d_rho = np.abs(rho_a_interp_log - np.log10(rho[:, i, j]))
            d_phi = np.abs(phi_a_interp - phi[:, i, j])
            row[f"{mode}_n"] = int(period.size)
            row[f"{mode}_rho"] = float(np.median(d_rho))
            row[f"{mode}_phi"] = float(np.median(d_phi))
            pooled[mode]["rho"].append(d_rho)
            pooled[mode]["phi"].append(d_phi)
        rows.append(row)

    overall = {"n_files": sum(r["n_files"] for r in rows)}
    for mode in ("xy", "yx"):
        rho_cat = np.concatenate(pooled[mode]["rho"]) if pooled[mode]["rho"] else np.array([])
        phi_cat = np.concatenate(pooled[mode]["phi"]) if pooled[mode]["phi"] else np.array([])
        overall[f"{mode}_n"] = int(rho_cat.size)
        overall[f"{mode}_rho"] = float(np.median(rho_cat)) if rho_cat.size else float("nan")
        overall[f"{mode}_phi"] = float(np.median(phi_cat)) if phi_cat.size else float("nan")
    return rows, overall


def print_table(rows, overall) -> None:
    """Print the per-rate and overall difference table of `diff_table`."""
    header = (f"{'rate':>8}  {'n files':>8}  {'n(xy)':>6}  {'d log10 rho (xy)':>17}  "
              f"{'d phase deg (xy)':>17}  {'n(yx)':>6}  {'d log10 rho (yx)':>17}  {'d phase deg (yx)':>17}")
    print(header)
    for row in rows:
        print(f"{row['rate']:>6}Hz  {row['n_files']:>8}  {row['xy_n']:>6}  {row['xy_rho']:>17.4f}  "
              f"{row['xy_phi']:>17.3f}  {row['yx_n']:>6}  {row['yx_rho']:>17.4f}  {row['yx_phi']:>17.3f}")
    print(f"{'overall':>8}  {overall['n_files']:>8}  {overall['xy_n']:>6}  {overall['xy_rho']:>17.4f}  "
          f"{overall['xy_phi']:>17.3f}  {overall['yx_n']:>6}  {overall['yx_rho']:>17.4f}  {overall['yx_phi']:>17.3f}")


def plot(aurora_path: Path, by_rate: dict[int, list[dict]], all_remotes: bool, title: str, out_png: Path):
    """Plot aurora's rho and phase over the unmerged lemimt EDIs, coloured by rate.

    Args:
        aurora_path (Path): Aurora EDI.
        by_rate (dict[int, list[dict]]): Output of `load_unmerged`.
        all_remotes (bool): Whether every remote was used; noted in the
            legend.
        title (str): Figure title.
        out_png (Path): Output figure.

    Returns:
        Path: `out_png`.
    """
    aurora_period, aurora_rho, aurora_phi, aurora_rho_err, aurora_phi_err = rho_phi(aurora_path)

    rates = sorted(by_rate, reverse=True)
    cmap = plt.get_cmap("viridis")
    colours = {rate: cmap(i / max(1, len(rates) - 1)) for i, rate in enumerate(rates)}

    fig, axes = plt.subplots(
        2, 2, figsize=(11, 8.5), sharex=True, layout="constrained",
    )
    (ax_rho_xy, ax_rho_yx), (ax_phi_xy, ax_phi_yx) = axes

    all_periods = [aurora_period]
    for rate in rates:
        entries = by_rate[rate]
        colour = colours[rate]
        suffix = ", all remotes)" if all_remotes else ")"
        label = f"lemimt {rate} Hz ({len(entries)} files{suffix}"
        for k, entry in enumerate(entries):
            all_periods.append(entry["period"])
            kw = dict(marker="o", ls="none", ms=3.0, alpha=0.5, color=colour)
            lbl = label if k == 0 else None
            ax_rho_xy.plot(entry["period"], entry["rho"][:, 0, 1], label=lbl, **kw)
            ax_rho_yx.plot(entry["period"], entry["rho"][:, 1, 0], **kw)
            ax_phi_xy.plot(entry["period"], entry["phi"][:, 0, 1], **kw)
            ax_phi_yx.plot(entry["period"], entry["phi"][:, 1, 0], **kw)

    kw_main = dict(fmt="o-", ms=3.5, lw=1.2, elinewidth=0.8, capsize=2.0)
    ax_rho_xy.errorbar(aurora_period, aurora_rho[:, 0, 1], yerr=aurora_rho_err[:, 0, 1],
                        color=AURORA_XY_COLOUR, label="aurora (xy)", **kw_main)
    ax_rho_yx.errorbar(aurora_period, aurora_rho[:, 1, 0], yerr=aurora_rho_err[:, 1, 0],
                        color=AURORA_YX_COLOUR, label="aurora (yx)", **kw_main)
    ax_phi_xy.errorbar(aurora_period, aurora_phi[:, 0, 1], yerr=aurora_phi_err[:, 0, 1],
                        color=AURORA_XY_COLOUR, **kw_main)
    ax_phi_yx.errorbar(aurora_period, aurora_phi[:, 1, 0], yerr=aurora_phi_err[:, 1, 0],
                        color=AURORA_YX_COLOUR, **kw_main)

    all_periods = np.concatenate(all_periods)
    pmin, pmax = float(all_periods.min()), float(all_periods.max())
    for ax in (ax_rho_xy, ax_rho_yx, ax_phi_xy, ax_phi_yx):
        ax.set_xscale("log")
        ax.set_xlim(pmin / 1.3, pmax * 1.3)
        ax.grid(True, which="both", alpha=0.3)

    ax_rho_xy.set_yscale("log")
    ax_rho_yx.set_yscale("log")
    ax_rho_xy.set_ylabel(r"$\rho_a$ ($\Omega$m)")
    ax_phi_xy.set_ylabel("phase (deg)")
    ax_phi_xy.set_xlabel("period (s)")
    ax_phi_yx.set_xlabel("period (s)")
    # the physical quadrants (crust.compare.phase_quadrants): xy in (0, 90), yx in (-180, -90)
    ax_phi_xy.set_ylim(0, 90)
    ax_phi_yx.set_ylim(-180, -90)
    ax_rho_xy.set_title("Zxy")
    ax_rho_yx.set_title("Zyx")

    handles_xy, labels_xy = ax_rho_xy.get_legend_handles_labels()
    handles_yx, labels_yx = ax_rho_yx.get_legend_handles_labels()
    fig.legend(handles_xy + handles_yx, labels_xy + labels_yx, fontsize=8,
               loc="outside lower center", ncols=3)
    fig.suptitle(title)

    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
    return out_png


def main(argv=None) -> None:
    """Plot and tabulate the comparison; exits 0, or 1 when no EDI could be used.

    Args:
        argv (list[str] | None): Command-line arguments; sys.argv when None.
    """
    args = parse_args(argv)
    aurora_path = Path(args.aurora_edi)
    unmerged_dir = Path(args.unmerged_dir)

    entries = find_unmerged(unmerged_dir, args.site, args.remote)
    if not entries:
        remote_txt = f" RR {args.remote}" if args.remote else ""
        print(f"no unmerged EDIs found for site {args.site}{remote_txt} in {unmerged_dir}")
        sys.exit(1)

    remotes_found = sorted({e["remote"] for e in entries})
    all_remotes = args.remote is None
    if all_remotes:
        print(f"no --remote given; using every remote found: {', '.join(remotes_found)}")

    by_rate = load_unmerged(entries)
    if not by_rate:
        print(f"every matched unmerged EDI for site {args.site} failed to parse")
        sys.exit(1)

    remote_label = args.remote if args.remote else "/".join(remotes_found)
    title = args.title or f"{args.site} RR {remote_label} — aurora ({aurora_path.name}) vs lemimt unmerged"
    out_png = Path(args.out) if args.out else aurora_path.with_name(f"{aurora_path.stem}_vs_lemimt_unmerged.png")

    out_png = plot(aurora_path, by_rate, all_remotes, title, out_png)
    print(f"comparison figure: {out_png}")

    aurora_period, aurora_rho, aurora_phi, _, _ = rho_phi(aurora_path)
    rows, overall = diff_table(aurora_period, aurora_rho, aurora_phi, by_rate)
    print_table(rows, overall)
    sys.exit(0)


def parse_args(argv=None) -> argparse.Namespace:
    """Parse the command line of compare_unmerged.py."""
    p = argparse.ArgumentParser(description=next(line for line in __doc__.strip().splitlines() if line.strip()))
    p.add_argument("aurora_edi", help="aurora transfer function (EDI) to compare")
    p.add_argument("unmerged_dir", help="folder of lemimt's per-rate/per-chunk unmerged EDIs")
    p.add_argument("site", help="site name, survey convention (e.g. D07; matched to lemimt's D7)")
    p.add_argument("--remote", metavar="NAME",
                   help="filter to this remote-reference site (lemimt's RR- name); "
                        "default: every remote found for the site")
    p.add_argument("--out", metavar="PNG",
                   help="output figure path (default: <aurora>_vs_lemimt_unmerged.png next to the aurora EDI)")
    p.add_argument("--title", metavar="TEXT", help="figure title (default: built from site/remote/aurora file name)")
    return p.parse_args(argv)


if __name__ == "__main__":
    main()
