#!/usr/bin/env python3
"""selftest.py — end-to-end regression suite for the bio-pathway figure engine.

Renders 6 built-in sandbox figures (mechanism, compartments, feedback, chart,
opt-in layout flags, evidence styles) into a temp dir and asserts:
  - built-in checker: 0 violations
  - independent SVG audit: 0 violations
  - PNG + PDF exist and are non-empty
Exit 0 iff all pass. Usage: python3 selftest.py [--workdir DIR]
"""
from __future__ import annotations
import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_figure import render

MECH = {
    "mode": "mechanism", "title": "selftest mechanism",
    "caption": "Solid: direct. Dashed: reported.",
    "compartments": [
        {"id": "ext", "label": "Extracellular", "kind": "exterior"},
        {"id": "mb", "label": "Membrane", "kind": "membrane"},
        {"id": "cyt", "label": "Cytosol", "kind": "cytosol"},
        {"id": "nuc", "label": "Nucleus", "kind": "nucleus"}],
    "nodes": [
        {"id": "L", "label": "Ligand", "kind": "other", "compartment": "ext", "source": "s1"},
        {"id": "R", "label": "RecA", "kind": "receptor", "compartment": "mb", "mods": ["P"], "source": "s1"},
        {"id": "K1", "label": "Kin1", "kind": "protein", "compartment": "cyt", "source": "s2"},
        {"id": "K2", "label": "Kin2", "kind": "protein", "compartment": "cyt", "mods": ["P"], "source": "s2"},
        {"id": "G", "label": "TFG", "kind": "gene", "compartment": "nuc", "source": "s3"}],
    "edges": [
        {"from": "L", "to": "R", "type": "binding", "source": "s1"},
        {"from": "R", "to": "K1", "type": "recruitment", "label": "pY", "source": "s2"},
        {"from": "K1", "to": "K2", "type": "phosphorylation", "label": "P-T", "source": "s2"},
        {"from": "K2", "to": "G", "type": "translocation", "source": "s3"},
        {"from": "G", "to": "K2", "type": "inhibition", "label": "feedback",
         "dashed": True, "route": "feedback", "source": "s3"}],
}
CHART = {
    "mode": "chart", "title": "selftest chart",
    "chart": {"x_label": "gene", "y_label": "fold change",
              "bars": [{"label": "A", "value": 2.5, "err": 0.3, "group": "stim"},
                       {"label": "B", "value": 1.0, "err": 0.1, "group": "ctrl"}],
              "stars": [{"pair": [0, 1], "text": "*"}]},
}
OPTIN = dict(MECH)
OPTIN["title"] = "selftest opt-in layout"
OPTIN["layout"] = {"auto_arc": True, "tighten_bands": True, "evidence_auto_style": True}
OPTIN["edges"] = MECH["edges"] + [{"from": "K1", "to": "K2", "type": "activation",
                                   "evidence": "reported", "source": "s4"},
                                  {"from": "R", "to": "G", "type": "other",
                                   "evidence": "weak", "source": "s4"}]

CASES = [("mechanism", MECH), ("chart", CHART), ("optin", OPTIN)]

def main():
    from viz_check import check
    from check_figure import audit
    work = Path(sys.argv[sys.argv.index("--workdir") + 1]) if "--workdir" in sys.argv \
        else Path(tempfile.mkdtemp(prefix="biofig_selftest_"))
    work.mkdir(parents=True, exist_ok=True)
    failures = []
    for name, spec in CASES:
        outdir = work / name
        summary = render(spec, dpi=150, outdir=outdir, basename=name)
        checks = summary["checks"]
        svg_text = (outdir / f"{name}.svg").read_text(encoding="utf-8")
        audit_res = audit(svg_text)
        ok_png = (outdir / f"{name}.png").exists() and (outdir / f"{name}.png").stat().st_size > 1000
        ok_pdf = (outdir / f"{name}.pdf").exists() and (outdir / f"{name}.pdf").stat().st_size > 500
        row = {"case": name, "built_in": checks["n_violations"],
               "audit": audit_res["n_violations"], "png": ok_png, "pdf": ok_pdf}
        print(json.dumps(row))
        if row["built_in"] or row["audit"] or not (ok_png and ok_pdf):
            failures.append(row)
    (work / "selftest-results.json").write_text(
        json.dumps({"failures": failures}, indent=1), encoding="utf-8")
    print("SELFTEST", "FAIL" if failures else "PASS", f"-> {work}")
    sys.exit(1 if failures else 0)

if __name__ == "__main__":
    main()
