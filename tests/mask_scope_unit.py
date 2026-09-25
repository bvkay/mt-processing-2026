# -*- coding: utf-8 -*-
"""
Unit test for the scope of masks.yaml entries

Checks the `scope` key of a mask (`crust.masks`: `normalise`, `load_masks`,
`save_masks`, `masks_for_role`, `remote_masks`), the masks
scripts/process_rr.py takes from each site of a pair (`resolve`, the
sidecar and the resolution line) under the rule `role` and under
`--mask-scope union`, and the scope the mask writers give their entries
(scripts/cluster_masks.py, scripts/gate_masks.py), on a synthetic survey in
a temporary folder. Runs without an archive and without aurora.

Usage:
    python tests/mask_scope_unit.py

@author: ben kay (ben@auscope.org.au)

:license: MIT

**This test fails if**

1. a mask without `scope` does not normalise to scope "local", one with
   scope "both" does not keep it, or scope "remote" (not one of
   `crust.masks.SCOPES`) is not refused with ValueError, directly and when
   masks.yaml holds it; or a site saved with a both-scoped and a default
   entry does not write "scope: both" and "scope: local" into masks.yaml
   and load back with the same scopes;
2. `masks_for_role` does not return every entry for the role local and only
   the both-scoped ones for the role remote, every entry for the remote
   under the rule union, or does not refuse an unknown role or rule;
   `remote_masks` does not give B's both-scoped entry alone (all three
   under union), or gives any entry of the stack STK_Bu;
3. process_rr's `resolve` for A rr B, where A declares a default-scoped and
   a both-scoped mask and B two local-scoped masks (one written without the
   key) and one both-scoped mask, does not give `masks_local` A's two,
   `masks_remote` B's both-scoped one and `masks` exactly the starts of
   MASK_ROLE_STARTS; the sidecar does not record `mask_scope` "role" and
   `mask_counts` {local 2, remote 1, remote_left_out 2} beside the same
   three lists; the resolution line is not exactly MASK_ROLE_LINE; B rr A
   does not take all three of B's entries as local and A's both-scoped one
   as remote; with `--mask-scope union` A rr B does not take all three of
   B's entries (`masks` exactly MASK_UNION_STARTS), with `mask_scope`
   "union", `mask_counts` {local 2, remote 3, remote_left_out 0} and the
   line MASK_UNION_LINE; `--no-masks` leaves a list non-empty or a count
   non-zero; or the parser accepts `--mask-scope remote`;
4. the masks cluster_masks.py (`mask_records`) and gate_masks.py
   (`spans_to_masks`, `night_masks`) build are not scope "local", or
   `write_site_masks` replacing a site's cluster masks does not keep its
   both-scoped time mask both-scoped in masks.yaml.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import importlib.util
import io
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from loguru import logger  # noqa: E402

import cluster_masks as cm  # noqa: E402
import gate_masks as gm  # noqa: E402
from crust.masks import (  # noqa: E402
    SCOPES, load_masks, masks_for_role, masks_path, normalise, remote_masks, save_masks,
)

logger.remove()
logger.add(sys.stderr, level="WARNING")

T0 = pd.Timestamp("2023-09-22T00:00:00", tz="UTC")


def entry(h0: float, h1: float, reason: str, bands="all", scope: str | None = None) -> dict:
    """Build one masks.yaml entry found by "time", from hour h0 to hour h1 after T0; scope left out when None."""
    out = {"start": (T0 + pd.Timedelta(hours=h0)).isoformat().replace("+00:00", "Z"),
           "end": (T0 + pd.Timedelta(hours=h1)).isoformat().replace("+00:00", "Z"),
           "bands": bands, "reason": reason, "found_by": "time"}
    if scope is not None:
        out["scope"] = scope
    return out


MASKS = {
    "A": [entry(1.0, 1.5, "A ey night"),
          entry(5.0, 5.25, "A mains at both", scope="both")],
    "B": [entry(2.0, 2.25, "B ey burst"),
          entry(3.0, 3.5, "B ex polar", bands=[0.1, 1.0], scope="local"),
          entry(4.0, 4.25, "B mains at both", scope="both")],
    "STK_Bu": [entry(6.0, 6.5, "a stack's entry", scope="both")],
}
# stated here, not computed from the masks: the starts each rule applies to A rr B, earliest first
MASK_ROLE_STARTS = ["2023-09-22T01:00:00Z", "2023-09-22T04:00:00Z", "2023-09-22T05:00:00Z"]
MASK_UNION_STARTS = ["2023-09-22T01:00:00Z", "2023-09-22T02:00:00Z", "2023-09-22T03:00:00Z",
                     "2023-09-22T04:00:00Z", "2023-09-22T05:00:00Z"]
MASK_ROLE_LINE = "masks: A 2, B 1 (3 applied; B 2 of scope local left out)"
MASK_UNION_LINE = "masks: A 2, B 3 (5 applied; --mask-scope union)"


def make_survey(root: Path) -> Path:
    """Write a two-site survey.yaml, an empty filters.yaml and MASKS as masks.yaml; return the survey.yaml."""
    sites = {s: {"latitude": 31.0 + 0.045 * k, "longitude": -5.5, "start": "2023-09-22T00:00:00Z",
                 "end": "2023-09-23T00:00:00Z"} for k, s in enumerate(("A", "B"))}
    cfg = {"name": "SYN", "instrument": "lemi423", "sample_rate": 1000, "data_root": str(root / "raw"),
           "workspace": str(root / "work"), "processing": {"min_period": 0.005, "max_period": 5000.0},
           "sites": sites}
    root.mkdir(parents=True, exist_ok=True)
    (root / "survey.yaml").write_text(yaml.safe_dump(cfg), encoding="utf-8")
    (root / "filters.yaml").write_text("{}\n", encoding="utf-8")
    (root / "masks.yaml").write_text(yaml.safe_dump(MASKS, sort_keys=False), encoding="utf-8")
    return root / "survey.yaml"


def load_process_rr():
    """Import scripts/process_rr.py as a module."""
    spec = importlib.util.spec_from_file_location("process_rr", REPO / "scripts" / "process_rr.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    logger.remove()  # after the script's imports (mth5 adds its own sink)
    logger.add(sys.stderr, level="WARNING")
    return module


def test_scope_key() -> None:
    assert SCOPES == ("local", "both"), SCOPES
    assert normalise(entry(1, 2, "x"))["scope"] == "local"
    assert normalise(entry(1, 2, "x", scope="both"))["scope"] == "both"
    try:
        normalise(entry(1, 2, "x", scope="remote"))
    except ValueError as exc:
        assert "scope" in str(exc) and "remote" in str(exc), exc
    else:
        raise AssertionError("scope 'remote' was accepted")
    with tempfile.TemporaryDirectory() as tmp:
        survey_yaml = Path(tmp) / "survey.yaml"
        survey_yaml.write_text("name: x\n", encoding="utf-8")
        masks_path(survey_yaml).write_text(yaml.safe_dump({"X": [entry(1, 2, "x", scope="remote")]}),
                                           encoding="utf-8")
        try:
            load_masks(survey_yaml, "X")
        except ValueError as exc:
            assert "scope" in str(exc), exc
        else:
            raise AssertionError("masks.yaml holding scope 'remote' loaded")
        masks_path(survey_yaml).unlink()
        save_masks(survey_yaml, "X", [entry(1, 2, "default"), entry(3, 4, "both", scope="both")])
        text = masks_path(survey_yaml).read_text(encoding="utf-8")
        assert "  scope: local\n" in text and "  scope: both\n" in text, text
        got = [(m["reason"], m["scope"]) for m in load_masks(survey_yaml, "X")]
        assert got == [("default", "local"), ("both", "both")], got
    print("  no key -> local; both kept; 'remote' refused by normalise and by load_masks; "
          "save_masks writes both scopes and they load back")


def test_role_filter() -> None:
    masks = [normalise(m) for m in MASKS["B"]]
    assert [m["reason"] for m in masks_for_role(masks, "local")] == [m["reason"] for m in masks]
    assert [m["reason"] for m in masks_for_role(masks, "remote")] == ["B mains at both"]
    assert [m["reason"] for m in masks_for_role(masks, "remote", rule="union")] == [m["reason"] for m in masks]
    for kwargs in ({"role": "reference"}, {"role": "remote", "rule": "all"}):
        try:
            masks_for_role(masks, **kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"masks_for_role accepted {kwargs}")
    with tempfile.TemporaryDirectory() as tmp:
        survey_yaml = make_survey(Path(tmp))
        assert [m["reason"] for m in remote_masks(survey_yaml, "B")] == ["B mains at both"]
        assert len(remote_masks(survey_yaml, "B", rule="union")) == 3
        assert remote_masks(survey_yaml, "STK_Bu") == [] and remote_masks(survey_yaml, "STK_Bu", rule="union") == []
    print("  local role: all 3 of B's; remote role: the both-scoped one; union: all 3; unknown role and rule "
          "refused; remote_masks alike, a stack none")


def resolve_line(process_rr, res) -> str:
    """Return the "masks:" line `print_resolution` prints for a resolution."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        process_rr.print_resolution(res)
    return next((ln for ln in out.getvalue().splitlines() if ln.startswith("masks:")), "")


def test_process_rr_selection() -> None:
    process_rr = load_process_rr()
    started = dt.datetime(2026, 9, 26, 9, 0, 0, tzinfo=dt.timezone.utc)
    with tempfile.TemporaryDirectory() as tmp:
        survey_yaml = make_survey(Path(tmp))

        def resolved(local, remote, *extra):
            """Resolve local rr remote and build its sidecar; return (resolution, sidecar, masks line)."""
            args = process_rr.build_parser().parse_args([str(survey_yaml), local, remote, *extra])
            res = process_rr.resolve(args, started)
            edi = res["survey"].workspace / "tf" / f"{res['stem']}.edi"
            sidecar = process_rr.build_sidecar(res, args, started, started, edi, edi.with_suffix(".png"), {}, [])
            json.loads(json.dumps(sidecar, default=str))
            for key in ("masks_local", "masks_remote", "masks"):
                assert sidecar[key] == res[key], (key, sidecar[key])
            return res, sidecar, resolve_line(process_rr, res)

        res, sidecar, line = resolved("A", "B")
        assert [m["reason"] for m in res["masks_local"]] == ["A ey night", "A mains at both"], res["masks_local"]
        assert [m["reason"] for m in res["masks_remote"]] == ["B mains at both"], res["masks_remote"]
        assert [m["start"] for m in res["masks"]] == MASK_ROLE_STARTS, [m["start"] for m in res["masks"]]
        assert sidecar["mask_scope"] == "role", sidecar["mask_scope"]
        assert sidecar["mask_counts"] == {"local": 2, "remote": 1, "remote_left_out": 2}, sidecar["mask_counts"]
        assert line == MASK_ROLE_LINE, line
        print(f"  A rr B: {len(res['masks'])} applied, starts {[s[11:16] for s in MASK_ROLE_STARTS]}; "
              f"counts {sidecar['mask_counts']}; {line!r}")

        res, sidecar, line = resolved("B", "A")
        assert [m["reason"] for m in res["masks_local"]] == ["B ey burst", "B ex polar", "B mains at both"], \
            res["masks_local"]
        assert [m["reason"] for m in res["masks_remote"]] == ["A mains at both"], res["masks_remote"]
        assert sidecar["mask_counts"] == {"local": 3, "remote": 1, "remote_left_out": 1}, sidecar["mask_counts"]
        print(f"  B rr A: B's 3 as local, A's both-scoped one as remote; counts {sidecar['mask_counts']}")

        res, sidecar, line = resolved("A", "B", "--mask-scope", "union")
        assert [m["reason"] for m in res["masks_remote"]] == ["B ey burst", "B ex polar", "B mains at both"], \
            res["masks_remote"]
        assert [m["start"] for m in res["masks"]] == MASK_UNION_STARTS, [m["start"] for m in res["masks"]]
        assert sidecar["mask_scope"] == "union", sidecar["mask_scope"]
        assert sidecar["mask_counts"] == {"local": 2, "remote": 3, "remote_left_out": 0}, sidecar["mask_counts"]
        assert line == MASK_UNION_LINE, line
        print(f"  A rr B --mask-scope union: {len(res['masks'])} applied; counts {sidecar['mask_counts']}; {line!r}")

        res, sidecar, line = resolved("A", "B", "--no-masks")
        assert res["masks_local"] == res["masks_remote"] == res["masks"] == [], res
        assert sidecar["mask_counts"] == {"local": 0, "remote": 0, "remote_left_out": 0}, sidecar["mask_counts"]
        assert line == "masks: ignored (--no-masks)", line
        print(f"  --no-masks: nothing applied, counts {sidecar['mask_counts']}")

        with contextlib.redirect_stderr(io.StringIO()):
            try:
                process_rr.build_parser().parse_args([str(survey_yaml), "A", "B", "--mask-scope", "remote"])
            except SystemExit:
                pass
            else:
                raise AssertionError("--mask-scope remote was accepted")
        print("  --mask-scope remote refused by the parser")


def test_writers() -> None:
    starts = [T0 + pd.Timedelta(minutes=10 * k) for k in range(6)]
    ends = [s + pd.Timedelta(minutes=10) for s in starts]
    split = {"source_phase": 3.0, "source_z": 0.1, "earth_phase": 45.0, "separation": 42.0, "n_source": 2, "n": 6}
    cluster = cm.mask_records(starts, ends, np.array([0, 1, 1, 0, 1, 0], bool), 0.1, 0.2, "yx", split)
    gate = gm.spans_to_masks([(starts[0], ends[0])], "gate", gm.GATE_ORIGIN)
    night = gm.night_masks(T0, T0 + pd.Timedelta(days=1), "01:00-05:00", "UTC")
    for name, masks in (("cluster", cluster), ("gate", gate), ("night", night)):
        assert masks and all(m["scope"] == "local" for m in masks), (name, masks)
    with tempfile.TemporaryDirectory() as tmp:
        survey_yaml = Path(tmp) / "survey.yaml"
        survey_yaml.write_text("name: x\n", encoding="utf-8")
        save_masks(survey_yaml, "X", [entry(8, 9, "hand, both", scope="both"), *cluster[:1]])
        cm.write_site_masks(survey_yaml, "X", cluster, "cluster")
        after = load_masks(survey_yaml, "X")
        kept = [m for m in after if m["found_by"] == "time"]
        assert [(m["reason"], m["scope"]) for m in kept] == [("hand, both", "both")], after
        assert sorted((m["start"], m["scope"]) for m in after if m["found_by"] == "cluster") == sorted(
            (m["start"], "local") for m in cluster), after
    print(f"  cluster ({len(cluster)}), gate ({len(gate)}) and night ({len(night)}) masks are scope local; "
          f"a cluster rewrite keeps the both-scoped time mask both")


if __name__ == "__main__":
    tests = [test_scope_key, test_role_filter, test_process_rr_selection, test_writers]
    print(__doc__.split("**This test fails if**")[1].strip())
    print()
    for test in tests:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\nPASS  mask_scope_unit ({len(tests)} tests)")
