#!/usr/bin/env python3
"""selftest.py — end-to-end regression suite for the bio-pathway figure engine.

Renders 8 built-in sandbox fixtures (mechanism+groups+data_map, cross-compartment feedback,
bar, hbar, line, volcano/scatter, heatmap, composite 2-panel) plus source-preserving edit_svg
and asserts:
  - built-in geometry + boundary-attachment checker: 0 violations
  - independent raw-SVG audit (check_figure.py): 0 violations + named layers
  - PNG + PDF + preview PNG exist and are non-empty
Exit 0 iff all pass. Usage: python3 selftest.py [--workdir DIR]
"""
from __future__ import annotations
import sys, json, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from make_figure import render
from check_figure import audit
from edit_svg import apply_edits, preservation_stats
from bio_lint import bio_audit
from render_preview import parse_svg_dimensions, _stamp_png_dpi

MECH = {
    "mode": "mechanism", "title": "RTK-MAPK mechanism with complex group and feedback",
    "caption": "Solid: direct; dashed: indirect negative feedback. Fill encodes expression.",
    "compartments": [
        {"id": "ext", "label": "Extracellular", "kind": "exterior"},
        {"id": "mb", "label": "Plasma membrane", "kind": "membrane"},
        {"id": "cyt", "label": "Cytosol", "kind": "cytosol"},
        {"id": "nuc", "label": "Nucleus", "kind": "nucleus"}],
    "groups": [
        {"id": "mapk_mod", "label": "MAPK kinase tier", "members": ["K1", "K2"], "source": "s2"}],
    "data_map": {"palette": "blues", "min": "0", "max": "10", "caption": "Log2 TPM (Table S1)"},
    "width_map": {"min": 0.2, "max": 1.0, "caption": "Interaction confidence"},
    "nodes": [
        {"id": "L", "label": "Ligand", "kind": "metabolite", "compartment": "ext", "source": "s1"},
        {"id": "R", "label": "RecA", "kind": "receptor", "compartment": "mb", "mods": ["P"], "source": "s1"},
        {"id": "A", "label": "Adapt1", "kind": "protein", "compartment": "cyt", "value": 3.0, "source": "s2"},
        {"id": "K1", "label": "Kin1", "kind": "protein", "compartment": "cyt", "mods": ["P"], "value": 6.5, "source": "s2"},
        {"id": "K2", "label": "Kin2", "kind": "protein", "compartment": "cyt", "mods": ["P"], "alias": "ERK2", "value": 9.2, "source": "s2"},
        {"id": "G", "label": "TFG", "kind": "gene", "compartment": "nuc", "source": "s3"},
        {"id": "PH", "label": "Proliferation", "kind": "process", "compartment": "nuc", "source": "s3"}],
    "edges": [
        {"from": "L", "to": "R", "type": "binding", "weight": 0.9, "source": "s1"},
        {"from": "R", "to": "A", "type": "recruitment", "label": "pY1045", "weight": 0.7, "source": "s2"},
        {"from": "A", "to": "K1", "type": "activation", "evidence": "direct", "weight": 1.0, "source": "s2"},
        {"from": "K1", "to": "K2", "type": "phosphorylation", "label": "P-T202", "weight": 0.85, "source": "s2"},
        {"from": "K2", "to": "G", "type": "translocation", "weight": 0.6, "source": "s3"},
        {"from": "G", "to": "PH", "type": "expression", "weight": 0.5, "source": "s3"},
        {"from": "G", "to": "R", "type": "inhibition", "label": "feedback", "weight": 0.35,
         "dashed": True, "route": "feedback", "source": "s3"}],
}

BAR = {
    "mode": "chart", "title": "qPCR validation of target genes",
    "chart": {"kind": "bar", "x_label": "Gene", "y_label": "Relative expression",
              "y_note": "Mean +/- SEM, n=3 (Table S2)",
              "bars": [{"label": "MYC", "value": 4.2, "err": 0.4, "group": "Stim", "points": [3.8, 4.2, 4.6]},
                       {"label": "MYC", "value": 1.0, "err": 0.1, "group": "Ctrl", "points": [0.9, 1.0, 1.1]},
                       {"label": "CCND1", "value": 3.1, "err": 0.3, "group": "Stim"},
                       {"label": "CCND1", "value": 1.0, "err": 0.12, "group": "Ctrl"}],
              "stars": [{"pair": [0, 1], "text": "***"}, {"pair": [2, 3], "text": "**"}]},
}

HBAR = {
    "mode": "chart", "title": "Top enriched pathways",
    "chart": {"kind": "hbar", "x_label": "-log10(FDR)", "y_note": "GSEA hallmark (Table S3)",
              "bars": [{"label": "MAPK signalling", "value": 6.4, "group": "Up"},
                       {"label": "Cell cycle G1/S", "value": 4.9, "group": "Up"},
                       {"label": "Apoptosis", "value": 2.3, "group": "Down"}]},
}

LINE = {
    "mode": "chart", "title": "Phospho-ERK activation kinetics",
    "chart": {"kind": "line", "x_label": "Time (min)", "y_label": "pERK / total ERK",
              "y_note": "Western blot densitometry (Fig. 2C)",
              "hlines": [{"y": 1.0, "label": "baseline"}],
              "series": [
                  {"name": "WT", "x": [0, 5, 15, 30, 60], "y": [1.0, 4.8, 5.2, 3.1, 1.6], "err": [0.1, 0.4, 0.5, 0.3, 0.2]},
                  {"name": "KO", "x": [0, 5, 15, 30, 60], "y": [1.0, 1.3, 1.5, 1.2, 1.0], "err": [0.1, 0.2, 0.2, 0.15, 0.1], "dashed": True}]},
}

SCATTER = {
    "mode": "chart", "title": "Differential expression volcano",
    "chart": {"kind": "scatter", "x_label": "log2(Fold Change)", "y_label": "-log10(padj)",
              "y_note": "DESeq2 output (Table S4)",
              "hlines": [1.3], "vlines": [-1.0, 1.0],
              "points": [
                  {"x": 2.4, "y": 5.2, "group": "Up", "label": "MYC"},
                  {"x": 1.8, "y": 3.8, "group": "Up", "label": "CCND1"},
                  {"x": -2.1, "y": 4.5, "group": "Down", "label": "CDKN1A"},
                  {"x": 0.2, "y": 0.6, "group": "NS"},
                  {"x": -0.4, "y": 0.9, "group": "NS"}]},
}

HEATMAP = {
    "mode": "chart", "title": "Pathway gene expression Z-score",
    "chart": {"kind": "heatmap", "palette": "fold", "cbar_label": "Z-score",
              "italic_rows": True, "y_note": "Row-scaled TPM (Table S5)",
              "rows": ["MYC", "CCND1", "DUSP6", "CDKN1A"],
              "cols": ["Ctrl_1", "Ctrl_2", "Stim_1", "Stim_2"],
              "values": [[-1.1, -0.9, 1.2, 1.3], [-0.8, -1.0, 0.9, 1.1],
                         [-0.6, -0.7, 1.0, 0.8], [1.1, 0.9, -1.2, -1.0]]},
}

COMPOSITE = {
    "mode": "composite",
    "title": "Composite publication figure: mechanism + expression",
    "caption": "(A) Core pathway mechanism. (B) Quantitative qPCR validation.",
    "layout": {"cols": 2, "panel_gap": 24},
    "panels": [
        {"id": "A", "spec": MECH},
        {"id": "B", "spec": BAR},
    ],
}

GROUPED_BAR = {
    "mode": "chart",
    "title": "Self-test grouped bar chart",
    "chart": {
        "kind": "grouped_bar",
        "x_label": "Target gene",
        "y_label": "Relative mRNA",
        "y_note": "Mean +/- SD (n=3, synthetic)",
        "italic_x": True,
        "categories": ["MYC", "CCND1", "DUSP6"],
        "series": [
            {"name": "DMSO", "values": [1.0, 1.0, 1.0], "errs": [0.1, 0.12, 0.08],
             "points": [[0.9, 1.0, 1.1], [0.88, 1.0, 1.12], [0.92, 1.0, 1.08]]},
            {"name": "Drug", "values": [0.35, 0.42, 0.25], "errs": [0.06, 0.08, 0.05],
             "points": [[0.29, 0.35, 0.41], [0.34, 0.42, 0.50], [0.20, 0.25, 0.30]]},
        ],
    },
}

DOTPLOT = {
    "mode": "chart", "title": "Pathway enrichment dotplot (synthetic)",
    "chart": {
        "kind": "dotplot", "x_label": "Gene Ratio", "color_label": "-log10(padj)",
        "size_label": "Gene count", "palette": "reds", "y_note": "Source: synthetic GO",
        "items": [
            {"label": "MAPK signaling cascade", "x": 0.42, "size": 24, "color": 8.2, "source": "syn"},
            {"label": "PI3K-AKT survival pathway", "x": 0.35, "size": 19, "color": 6.4, "source": "syn"},
            {"label": "Cell cycle G1/S transition", "x": 0.28, "size": 14, "color": 4.9, "source": "syn"},
            {"label": "Oxidative stress response", "x": 0.19, "size": 9, "color": 3.1, "source": "syn"},
        ],
    },
}

STACKED_BAR = {
    "mode": "chart", "title": "Cell-type composition (100% stacked, synthetic)",
    "chart": {
        "kind": "stacked_bar", "normalize": True, "y_label": "Proportion (%)",
        "y_note": "Source: synthetic scRNA-seq",
        "categories": ["Control", "Treated", "Resistant"],
        "series": [
            {"name": "CD8+ T", "values": [42, 61, 24], "source": "syn"},
            {"name": "Macrophage", "values": [33, 22, 48], "source": "syn"},
            {"name": "Treg", "values": [25, 17, 28], "source": "syn"},
        ],
    },
}

BOXPLOT = {
    "mode": "chart", "title": "Target phosphorylation distribution (synthetic)",
    "chart": {
        "kind": "box", "y_label": "p-ERK intensity (a.u.)", "y_note": "Source: synthetic WB",
        "groups": [
            {"label": "Vehicle", "values": [1.0, 1.2, 0.9, 1.1, 1.3, 1.05], "source": "syn"},
            {"label": "EGF", "values": [3.8, 4.2, 4.5, 4.1, 3.9, 4.7], "source": "syn"},
            {"label": "EGF + MEKi", "values": [1.3, 1.5, 1.2, 1.6, 1.4, 1.1], "source": "syn"},
        ],
        "sig_brackets": [{"a": 0, "b": 1, "label": "***"}, {"a": 1, "b": 2, "label": "***"}],
    },
}

CASES = [("mechanism", MECH), ("bar", BAR), ("grouped_bar", GROUPED_BAR), ("hbar", HBAR),
         ("line", LINE), ("scatter", SCATTER), ("heatmap", HEATMAP), ("dotplot", DOTPLOT),
         ("stacked_bar", STACKED_BAR), ("box", BOXPLOT), ("composite", COMPOSITE)]

def main():
    work = Path(sys.argv[sys.argv.index("--workdir") + 1]) if "--workdir" in sys.argv \
        else Path(tempfile.mkdtemp(prefix="biofig_selftest_"))
    work.mkdir(parents=True, exist_ok=True)
    failures = []
    for name, spec in CASES:
        outdir = work / name
        summary = render(spec, dpi=150, outdir=outdir, basename=name, verbose=False, preview_dpi=100)
        checks = summary["checks"]
        svg_text = (outdir / f"{name}.svg").read_text(encoding="utf-8")
        audit_res = audit(svg_text)
        ok_png = (outdir / f"{name}.png").exists() and (outdir / f"{name}.png").stat().st_size > 1000
        ok_pdf = (outdir / f"{name}.pdf").exists() and (outdir / f"{name}.pdf").stat().st_size > 500
        ok_prev = (outdir / f"{name}.preview.png").exists()
        ok_pix = bool((checks.get("pixel_audit") or {}).get("ok"))
        ok_leg = bool((checks.get("legend_consistency") or {}).get("all_consistent", True))
        row = {"case": name, "built_in": checks["n_violations"],
               "audit": audit_res["n_violations"], "pixel_ok": ok_pix, "legend_ok": ok_leg,
               "layers": audit_res["layers_named"],
               "png": ok_png, "pdf": ok_pdf, "preview": ok_prev}
        print(json.dumps(row))
        if row["built_in"] or row["audit"] or not (ok_png and ok_pdf and ok_prev and ok_pix and ok_leg and row["layers"]):
            failures.append({"row": row, "built_in_v": checks["violations"][:5],
                             "audit_v": audit_res["violations"][:5], "pixel": checks.get("pixel_audit")})

    # Test bio_lint detection on deliberate biological defects (off-membrane receptor + contradiction)
    bad_bio = {
        "mode": "mechanism",
        "compartments": [{"id": "mb", "kind": "membrane"}, {"id": "nuc", "kind": "nucleus"}],
        "nodes": [
            {"id": "R1", "label": "HER2", "kind": "receptor", "compartment": "nuc", "source": "Ex"},
            {"id": "G1", "label": "p53", "kind": "protein", "compartment": "nuc", "source": "Ex"},
        ],
        "edges": [
            {"from": "R1", "to": "G1", "type": "activation", "label": "inhibits", "source": "Ex"},
            {"from": "R1", "to": "G1", "type": "undirected", "source": "Ex"},
        ],
    }
    ba = bio_audit(bad_bio)
    codes = {x["code"] for x in ba["issues"]}
    bio_ok = ("receptor_off_membrane" in codes and "edge_semantic_contradiction" in codes
              and ba["stats"]["n_canonical_resolved"] == 2 and ba["stats"]["n_undirected"] == 1)
    print(json.dumps({"case": "bio_lint", "ok": bio_ok, "detected": sorted(codes)}))
    if not bio_ok:
        failures.append({"case": "bio_lint", "result": ba})

    # Test source-preserving SVG edit
    src = (work / "mechanism" / "mechanism.svg").read_text(encoding="utf-8")
    edited, rec = apply_edits(src, [
        {"op": "set_text_by_id", "id": "label-R", "text": "EGFR"},
        {"op": "set_style_by_id", "id": "shape-R", "prop": "stroke", "value": "#0f766e"},
    ])
    pstats = preservation_stats(src, edited)
    edit_ok = all(r["status"] == "ok" for r in rec) and pstats["unchanged_line_ratio"] > 0.90
    print(json.dumps({"case": "edit_svg", "ok": edit_ok, "preservation": pstats}))
    if not edit_ok:
        failures.append({"case": "edit_svg", "rec": rec, "preservation": pstats})

    # Test root <svg> dimension, unit conversion, and pHYs DPI stamping edge cases
    svg_dim_cases = [
        ("no_root_w_inner_rect",
         '<!-- <svg width="50"> --><svg xmlns="http://www.w3.org/2000/svg" stroke-width="2" viewBox="0 0 1400 800">'
         '<rect x="10" y="10" width="140" height="80" fill="#2563eb"/></svg>',
         1400.0, 1400.0, 800.0, 4375, 300),
        ("pct_100_fallback_vb",
         '<svg xmlns="http://www.w3.org/2000/svg" width="100%" height="100%" viewBox="0 0 1200 750">'
         '<rect x="10" y="10" width="120" height="60" fill="#0f766e"/></svg>',
         1200.0, 1200.0, 750.0, 3750, 300),
        ("mm_unit",
         '<svg xmlns="http://www.w3.org/2000/svg" width="180mm" height="120mm" viewBox="0 0 180 120">'
         '<rect x="5" y="5" width="40" height="20" fill="#b91c1c"/></svg>',
         180.0 * 96.0 / 25.4, 180.0, 120.0, 2126, 300),
        ("pt_single_quote_inner_symbol",
         "<svg xmlns='http://www.w3.org/2000/svg' width='500pt' height='300pt'>"
         "<defs><symbol id='ic' viewBox='0 0 24 24'><rect width='24' height='24'/></symbol></defs>"
         "<rect x='10' y='10' width='50' height='30' fill='#7c3aed'/></svg>",
         500.0 * 96.0 / 72.0, 500.0 * 96.0 / 72.0, 300.0 * 96.0 / 72.0, 2083, 300),
        ("cm_and_in_units",
         '<svg xmlns="http://www.w3.org/2000/svg" width="7.5in" height="12.7cm">'
         '<rect x="10" y="10" width="80" height="40" fill="#334155"/></svg>',
         720.0, 720.0, 480.0, 2250, 300),
    ]
    dim_errs = []
    for cname, stxt, exp_css_w, exp_uw, exp_uh, px_w, exp_dpi in svg_dim_cases:
        d = parse_svg_dimensions(stxt)
        a_res = audit(stxt)
        if abs(d["css_w"] - exp_css_w) > 0.2:
            dim_errs.append(f"{cname}: css_w={d['css_w']:.2f} != {exp_css_w:.2f}")
        if abs(a_res["canvas"][0] - exp_uw) > 0.2 or abs(a_res["canvas"][1] - exp_uh) > 0.2:
            dim_errs.append(f"{cname}: audit.canvas={a_res['canvas']} != [{exp_uw:.2f}, {exp_uh:.2f}]")
        try:
            from PIL import Image
            p_png = work / f"dpi_{cname}.png"
            Image.new("RGB", (px_w, 100), "white").save(p_png, dpi=(72, 72))
            _stamp_png_dpi(stxt, p_png)
            with Image.open(p_png) as im_chk:
                got_dpi = float((im_chk.info.get("dpi") or (0, 0))[0])
            if abs(got_dpi - exp_dpi) > 2.0:
                dim_errs.append(f"{cname}: stamped_dpi={got_dpi:.1f} != {exp_dpi}")
        except ImportError:
            pass
    dim_ok = (len(dim_errs) == 0)
    print(json.dumps({"case": "svg_dims_dpi", "ok": dim_ok, "checked": len(svg_dim_cases), "errors": dim_errs}))
    if not dim_ok:
        failures.append({"case": "svg_dims_dpi", "errors": dim_errs})

    (work / "selftest-results.json").write_text(
        json.dumps({"failures": failures}, indent=1), encoding="utf-8")
    print("SELFTEST", "FAIL" if failures else "PASS", f"-> {work}")
    sys.exit(1 if failures else 0)

if __name__ == "__main__":
    main()
