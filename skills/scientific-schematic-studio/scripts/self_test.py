#!/usr/bin/env python3
"""self_test.py — one-command health check of the whole skill (maintainer tool).

Runs canonical synthetic cases end-to-end:
  1) mechanism + CSV-driven line chart with errorbars + geometry & export audit
  2) source-preserving SVG edit (--inspect, swap_edge, replace_text, retext, set_marker)
  3) make_result output_contract passthrough & auto-aliasing
Usage: python3 self_test.py [--workdir DIR]   (default: system temp)
"""
import argparse, json, os, sys, tempfile, subprocess, zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

CSV_DATA = "Dose,ctrl,treat,treat_sd\n0,1.0,1.0,0.1\n1,1.1,2.3,0.2\n10,0.9,4.1,0.3\n"

EDIT_SVG = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="140" '
    'viewBox="0 0 300 140"><defs><marker id="arr" markerWidth="8" '
    'markerHeight="6" refX="7" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 z" '
    'fill="#333"/></marker></defs>'
    '<g id="node-A"><rect x="20" y="50" width="90" height="36" rx="6" '
    'fill="#EAF2FB" stroke="#2E5E8C"/><text x="65" y="72" text-anchor="middle" '
    'font-family="sans-serif" font-size="12"><tspan x="65" y="72">A node</tspan></text></g>'
    '<g id="node-B"><rect x="180" y="50" width="90" height="36" rx="6" '
    'fill="#FADBD8" stroke="#8C3B33"/><text x="225" y="72" text-anchor="middle" '
    'font-family="sans-serif" font-size="12">B node</text></g>'
    '<g id="edge-A-B" marker-end="url(#arr)"><line x1="225" y1="50" x2="110" '
    'y2="50" stroke="#333" stroke-width="1.5"/></g></svg>'
)

EDIT_OPS = {
    "ops": [
        {"op": "swap_edge", "gid": "edge-A-B"},
        {"op": "retext", "gid": "node-B", "text": "B corrected"},
        {"op": "replace_text", "find": "A node", "replace": "A verified"},
        {"op": "set_marker", "gid": "edge-A-B", "marker": "tbar"},
    ]
}


def run(cmd, **kw):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run([sys.executable, "-B"] + cmd, capture_output=True,
                          text=True, timeout=240, env=env, **kw)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--workdir", default=None)
    a = ap.parse_args()
    wd = a.workdir or tempfile.mkdtemp(prefix="schematic_selftest_")
    os.makedirs(wd, exist_ok=True)
    results = []

    def check(name, cond, detail=""):
        results.append((name, bool(cond), detail))

    # Case 1: mechanism (with group, binds, inhibits, detour) + CSV-driven line chart with errorbars
    csv_path = os.path.join(wd, "dose.csv")
    open(csv_path, "w", encoding="utf-8").write(CSV_DATA)
    spec_a = {
        "canvas": {"width_mm": 180},
        "panels": [
            {"id": "p1", "type": "schematic", "title": "Self-test signaling cascade", "direction": "LR",
             "nodes": [
                 {"id": "S", "label": "Signal", "shape": "ellipse", "fill": "#FDEBD0",
                  "source": {"file": "paper.pdf", "locator": "p.1"}},
                 {"id": "K", "label": "Kinase", "sublabel": "active", "shape": "round",
                  "source": {"file": "paper.pdf", "locator": "p.2"}},
                 {"id": "I", "label": "Inhibitor", "shape": "round", "fill": "#FADBD8",
                  "source": {"file": "paper.pdf", "locator": "p.2"}},
                 {"id": "T", "label": "Target", "shape": "stadium", "fill": "#D5F5E3",
                  "source": {"file": "paper.pdf", "locator": "p.3"}}],
             "edges": [
                 {"from": "S", "to": "K", "kind": "binds", "label": "binding",
                  "source": {"file": "paper.pdf", "locator": "p.1"}},
                 {"from": "K", "to": "I", "kind": "inhibits", "label": "degradation",
                  "source": {"file": "paper.pdf", "locator": "p.2"}},
                 {"from": "I", "to": "T", "kind": "inhibits", "label": "retention",
                  "source": {"file": "paper.pdf", "locator": "p.2"}},
                 {"from": "T", "to": "S", "kind": "activates", "label": "feedback",
                  "source": {"file": "paper.pdf", "locator": "p.3"}}],
             "groups": [{"id": "nuc", "label": "Nucleus", "members": ["T"], "dash": True}],
             "legend": {"title": "Interaction types",
                        "items": [{"kind": "binds", "label": "binding"},
                                  {"kind": "inhibits", "label": "inhibition"},
                                  {"kind": "activates", "label": "activation"}]}},
            {"id": "p2", "type": "chart", "title": "Self-test CSV dose response", "height_mm": 54,
             "chart": {"kind": "line", "data_file": csv_path, "x_col": "Dose",
                       "y_cols": ["ctrl", "treat"], "err_cols": {"treat": "treat_sd"},
                       "unit": "nM", "y_label": "Response", "x_label": "Dose"}}
        ]
    }
    spec1 = os.path.join(wd, "spec_a.json")
    json.dump(spec_a, open(spec1, "w", encoding="utf-8"), indent=1)
    out1 = os.path.join(wd, "out_a")
    r = run([os.path.join(HERE, "build_figure.py"), spec1, "--out-dir", out1,
             "--stem", "fig", "--geom", os.path.join(wd, "geom_a.json")])
    check("build: mechanism+CSV line chart w/ errorbars", r.returncode == 0, r.stderr[-200:])
    for f in ("fig.svg", "fig.pdf", "fig.png", "fig_preview.png"):
        check("deliverable %s" % f, os.path.exists(os.path.join(out1, f)))
    r = run([os.path.join(HERE, "audit_figure.py"),
             os.path.join(wd, "geom_a.json"), "--spec", spec1])
    check("audit: zero errors", '"status": "pass"' in r.stdout or '"n_errors": 0' in r.stdout,
          r.stdout[-200:])
    r = run([os.path.join(HERE, "export_check.py"),
             "--png", os.path.join(out1, "fig.png"),
             "--pdf", os.path.join(out1, "fig.pdf"),
             "--svg", os.path.join(out1, "fig.svg"),
             "--width-mm", "180", "--dpi", "300", "--probe", "Kinase,Dose"])
    check("export compliance", '"status": "pass"' in r.stdout, r.stdout[-200:])

    # Case 2: edit path (--inspect + swap_edge + retext + replace_text + set_marker)
    svg = os.path.join(wd, "input.svg")
    open(svg, "w", encoding="utf-8").write(EDIT_SVG)
    r = run([os.path.join(HERE, "edit_svg.py"), svg, "--inspect"])
    check("edit: --inspect JSON", r.returncode == 0 and '"node-A"' in r.stdout, r.stderr[-160:])
    ops = os.path.join(wd, "ops.json")
    json.dump(EDIT_OPS, open(ops, "w", encoding="utf-8"))
    out2 = os.path.join(wd, "out_edit")
    r = run([os.path.join(HERE, "edit_svg.py"), svg, ops, "--out-dir", out2, "--no-render"])
    check("edit: ops applied", r.returncode == 0, r.stderr[-200:])
    edited = open(os.path.join(out2, "input_edited.svg"), encoding="utf-8").read()
    check("edit: swap_edge + tbar + replace_text",
          'x1="110"' in edited and 'x2="225"' in edited and
          'mh-tbar' in edited and 'A verified' in edited and 'B corrected' in edited)
    check("edit: original preserved",
          os.path.exists(os.path.join(out2, "original_input.svg")))

    # Case 3: make_result output_contract passthrough & auto-aliasing
    case_j = os.path.join(wd, "case.json")
    json.dump({"case_id": "st-01", "output_contract": {"required": ["case_id", "editable_source", "custom_summary"]}},
              open(case_j, "w", encoding="utf-8"))
    man_j = os.path.join(wd, "manifest.json")
    json.dump({"deliverables": {"editable_source": {"path": os.path.join(out1, "fig.svg"), "format": "svg"},
                                "exports": [{"path": os.path.join(out1, "fig.png"), "format": "png"}]},
               "custom_summary": "all ok"}, open(man_j, "w", encoding="utf-8"))
    res_j = os.path.join(wd, "result.json")
    r = run([os.path.join(HERE, "make_result.py"), "--case-id", "st-01",
             "--case-json", case_j, "--manifest", man_j,
             "--auto-from-spec", spec1, "--geometry", os.path.join(wd, "geom_a.json"),
             "--out", res_j])
    res_d = json.load(open(res_j, encoding="utf-8")) if os.path.exists(res_j) else {}
    check("make_result: output_contract passthrough",
          r.returncode == 0 and res_d.get("custom_summary") == "all ok" and
          isinstance(res_d.get("editable_source"), dict) and not res_d.get("missing_fields"))

    # 5) 2-step run_pipeline.py prepare + deliver (generate + edit)
    p_in = os.path.join(wd, "pipe_in")
    p_wk = os.path.join(wd, "pipe_wk")
    p_out = os.path.join(wd, "pipe_out")
    os.makedirs(p_in, exist_ok=True)
    json.dump({
        "case_id": "pipe-01",
        "task": "Draw EGFR cascade + CSV dose chart",
        "output_contract": {"required": ["case_id", "editable_source", "exports", "custom_tag"]}
    }, open(os.path.join(p_in, "case.json"), "w"))
    with open(os.path.join(p_in, "dose.csv"), "w") as f:
        f.write("Dose,Ctrl,Ctrl_SD\n0,1.0,0.1\n10,3.2,0.2\n")
    r_prep = run([os.path.join(HERE, "run_pipeline.py"), "prepare",
                  "--input", p_in, "--work", p_wk, "--out", p_out])
    p_res0 = json.load(open(os.path.join(p_out, "result.json"), encoding="utf-8")) if os.path.exists(os.path.join(p_out, "result.json")) else {}
    check("pipeline: prepare + partial safety net",
          r_prep.returncode == 0 and p_res0.get("status") == "partial" and
          "PREPARE BRIEF" in r_prep.stdout, r_prep.stderr)

    plan_j = os.path.join(p_wk, "plan.json")
    plan_data = json.load(open(spec1, encoding="utf-8"))
    plan_data["case_id"] = "pipe-01"
    plan_data["custom_tag"] = "verified"
    plan_data["panels"][1]["chart"]["data_file"] = os.path.join(p_in, "dose.csv")
    plan_data["panels"][1]["chart"]["x_col"] = "Dose"
    plan_data["panels"][1]["chart"]["y_cols"] = ["Ctrl"]
    plan_data["panels"][1]["chart"]["err_cols"] = {"Ctrl": "Ctrl_SD"}
    json.dump(plan_data, open(plan_j, "w"))
    r_del = run([os.path.join(HERE, "run_pipeline.py"), "deliver", plan_j,
                 "--input", p_in, "--work", p_wk, "--out", p_out])
    p_res1 = json.load(open(os.path.join(p_out, "result.json"), encoding="utf-8")) if os.path.exists(os.path.join(p_out, "result.json")) else {}
    check("pipeline: deliver generate ALL CHECKS PASSED",
          r_del.returncode == 0 and p_res1.get("status") == "ok" and
          p_res1.get("custom_tag") == "verified" and
          "ALL CHECKS PASSED" in r_del.stdout, r_del.stdout + r_del.stderr)

    # 8) Grid row layout + sig_brackets + replicate agg + heatmap + footnote
    grid_csv = os.path.join(wd, "reps.csv")
    with open(grid_csv, "w", encoding="utf-8") as f:
        f.write("Condition,Value\nCtrl,1.0\nCtrl,1.1\nCtrl,0.9\nDrug,3.8\nDrug,4.2\nDrug,4.0\n")
    grid_spec = os.path.join(wd, "grid_spec.json")
    json.dump({
        "canvas": {"width_mm": 180},
        "footnote": "Source: synthetic self_test grid.",
        "panels": [
            {"id": "g1", "row": 0, "type": "schematic", "title": "Grid Top Mechanism", "direction": "LR",
             "nodes": [
                 {"id": "S1", "label": "Very Long Extracellular Stimulus Name", "shape": "ellipse", "fill": "#0072B2", "rank": 0,
                  "source": {"file": "t.pdf", "locator": "p.1"}},
                 {"id": "S2", "label": "Effector", "shape": "stadium", "fill": "#D5F5E3", "rank": 1,
                  "source": {"file": "t.pdf", "locator": "p.1"}}],
             "edges": [{"from": "S1", "to": "S2", "kind": "activates", "label": "induces",
                        "source": {"file": "t.pdf", "locator": "p.1"}}],
             "legend": {"title": "Legend", "items": [{"kind": "activates", "label": "Activation"}]}},
            {"id": "g2", "row": 1, "type": "chart", "title": "Replicates + Sig", "height_mm": 50,
             "chart": {"kind": "bar", "data_file": grid_csv, "x_col": "Condition", "y_cols": ["Value"],
                       "agg": "mean_sd", "show_points": True, "unit": "fold", "legend_loc": "top",
                       "sig_brackets": [{"x1": "Ctrl", "x2": "Drug", "label": "***"}]}},
            {"id": "g3", "row": 1, "type": "chart", "title": "Matrix Heatmap", "height_mm": 50,
             "chart": {"kind": "heatmap", "categories": ["0h", "6h", "24h"], "unit": "log2FC",
                       "series": [{"name": "GeneA", "values": [0.1, 1.8, 3.2]},
                                  {"name": "GeneB", "values": [0.0, -0.9, -2.1]}]}}
        ]
    }, open(grid_spec, "w", encoding="utf-8"))
    grid_geom = os.path.join(wd, "grid_geom.json")
    r_g = run([os.path.join(HERE, "build_figure.py"), grid_spec, "--out-dir", wd, "--stem", "gridfig", "--geom", grid_geom])
    r_ga = run([os.path.join(HERE, "audit_figure.py"), grid_geom, "--spec", grid_spec])
    check("grid: 2-row multi-panel + agg/sig/heatmap + audit",
          r_g.returncode == 0 and r_ga.returncode == 0 and os.path.exists(os.path.join(wd, "gridfig.svg")),
          r_g.stderr + r_ga.stdout)

    # 9) External SVG edit with by_text + add_legend + auto viewBox expansion
    ext_svg = os.path.join(wd, "noid.svg")
    with open(ext_svg, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg" width="320" height="120" viewBox="0 0 320 120">'
                '<rect x="20" y="30" width="90" height="40" fill="#EAF2FB" stroke="#2E5E8C"/>'
                '<text x="65" y="55" text-anchor="middle" font-size="12">Alpha</text>'
                '<rect x="200" y="30" width="90" height="40" fill="#D5F5E3" stroke="#2E5E8C"/>'
                '<text x="245" y="55" text-anchor="middle" font-size="12">Beta</text></svg>')
    ext_ops = os.path.join(wd, "ext_ops.json")
    json.dump({"ops": [
        {"op": "set_attr", "by_text": "Alpha", "attr": "fill", "value": "#FADBD8"},
        {"op": "add_edge", "id": "e-ab", "x1": 110, "y1": 50, "x2": 198, "y2": 50, "marker": "tbar", "label": "blocks"},
        {"op": "add_legend", "items": [{"kind": "inhibits", "label": "Inhibition"}]}
    ]}, open(ext_ops, "w", encoding="utf-8"))
    r_ex = run([os.path.join(HERE, "edit_svg.py"), ext_svg, ext_ops, "--out-dir", wd, "--stem", "noid_ed"])
    ex_d = json.loads(r_ex.stdout) if r_ex.returncode == 0 else {}
    check("edit: by_text + add_edge + add_legend + viewBox expand",
          r_ex.returncode == 0 and not ex_d.get("errors") and ex_d.get("viewBox_after") != ex_d.get("viewBox_before"),
          r_ex.stdout + r_ex.stderr)

    # 10) Wide-format column replicates + stacked sub-table stop + nested TB compartments + data_verification
    wide_csv = os.path.join(wd, "wide_sub.csv")
    with open(wide_csv, "w", encoding="utf-8") as f:
        f.write("Source Data Fig 3a\nReplicate,WT,KO,KO+Rescue\nRep1,1.0,4.2,1.3\nRep2,1.1,4.6,1.5\nRep3,0.9,4.1,1.2\n"
                "Source Data Fig 3b (second subtable must be ignored)\nX,Y\n99,99\n")
    tb_spec = os.path.join(wd, "tb_nested.json")
    json.dump({
        "canvas": {"width_mm": 180},
        "panels": [
            {"id": "t1", "row": 0, "width_weight": 1.0, "type": "schematic", "title": "Nested TB Pathway", "direction": "TB",
             "nodes": [
                 {"id": "Lig", "label": "Ligand", "shape": "ellipse", "fill": "#FDEBD0", "rank": 0, "source": {"file": "p.pdf", "locator": "p.2"}},
                 {"id": "Rec", "label": "Receptor", "shape": "round", "fill": "#EAF2FB", "rank": 1, "source": {"file": "p.pdf", "locator": "p.2"}},
                 {"id": "TF", "label": "STAT3", "shape": "stadium", "fill": "#D5F5E3", "rank": 2, "source": {"file": "p.pdf", "locator": "p.2"}}],
             "edges": [
                 {"from": "Lig", "to": "Rec", "kind": "binds", "label": "binds", "source": {"file": "p.pdf", "locator": "p.2"}},
                 {"from": "Rec", "to": "TF", "kind": "translocates", "label": "entry", "source": {"file": "p.pdf", "locator": "p.2"}}],
             "groups": [
                 {"id": "cell", "label": "Host Cell", "members": ["Rec", "TF"], "dash": True},
                 {"id": "nuc", "label": "Nucleus", "members": ["TF"], "dash": True}],
             "legend": {"title": "Legend", "items": [{"kind": "binds", "label": "Binding"}, {"kind": "translocates", "label": "Translocation"}]}},
            {"id": "t2", "row": 0, "width_weight": 1.0, "type": "chart", "title": "Wide Replicates", "height_mm": 54,
             "chart": {"kind": "bar", "data_file": wide_csv, "orient": "columns", "y_cols": ["WT", "KO", "KO+Rescue"],
                       "agg": "mean_sd", "show_points": True, "unit": "fold",
                       "sig_brackets": [{"x1": "WT", "x2": "KO", "label": "***"}]}}
        ]
    }, open(tb_spec, "w", encoding="utf-8"))
    tb_geom = os.path.join(wd, "tb_geom.json")
    tb_aud = os.path.join(wd, "tb_aud.json")
    r_tb = run([os.path.join(HERE, "build_figure.py"), tb_spec, "--out-dir", wd, "--stem", "tbfig", "--geom", tb_geom])
    r_tba = run([os.path.join(HERE, "audit_figure.py"), tb_geom, "--spec", tb_spec, "--out", tb_aud])
    aud_d = json.load(open(tb_aud, encoding="utf-8")) if os.path.exists(tb_aud) else {}
    dv = (aud_d.get("data_verification") or {}).get("t2") or {}
    check("wide+nested: orient:columns + subtable-stop + TB nesting + SHA data_verification",
          r_tb.returncode == 0 and r_tba.returncode == 0 and dv.get("verified") is True and dv.get("n_values_checked") == 3,
          r_tb.stderr + r_tba.stdout)

    # 11) Sparse XLSX coordinate-aware col_range + biological shapes/membrane/preset + unnamed SVG edge_idx & from_text/to_text
    import zipfile as _zf
    sparse_xlsx = os.path.join(wd, "sparse_nature.xlsx")
    with _zf.ZipFile(sparse_xlsx, "w", _zf.ZIP_DEFLATED) as zf:
        zf.writestr("xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Fig3" sheetId="1" r:id="rId1"/></sheets></workbook>')
        zf.writestr("xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        # Side-by-side blocks: Col A empty, Col B=WT(n=2, row 4 missing!), Col C=KO(n=3)
        zf.writestr("xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            '<row r="1"><c r="B1" t="inlineStr"><is><t>WT</t></is></c><c r="C1" t="inlineStr"><is><t>KO</t></is></c></row>'
            '<row r="2"><c r="B2"><v>1.0</v></c><c r="C2"><v>5.0</v></c></row>'
            '<row r="3"><c r="B3"><v>1.2</v></c><c r="C3"><v>5.4</v></c></row>'
            '<row r="4"><c r="C4"><v>5.2</v></c></row>'
            '</sheetData></worksheet>')
    v16_spec = os.path.join(wd, "v16_spec.json")
    json.dump({
        "preset": "nature_double",
        "panels": [
            {"id": "p1", "row": 0, "type": "schematic", "title": "Bio Grammar", "direction": "TB",
             "nodes": [
                 {"id": "R", "label": "Receptor", "shape": "complex", "rank": 0, "source": {"file": "p.pdf", "locator": "p.1"}},
                 {"id": "D", "label": "Drug", "shape": "hexagon", "fill": "#FADBD8", "rank": 1, "source": {"file": "p.pdf", "locator": "p.1"}},
                 {"id": "G", "label": "Target", "shape": "gene", "badge": "5.2x", "rank": 1, "source": {"file": "p.pdf", "locator": "p.1"}}],
             "edges": [
                 {"from": "R", "to": "G", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.1"}},
                 {"from": "D", "to": "G", "kind": "inhibits", "source": {"file": "p.pdf", "locator": "p.1"}}],
             "groups": [{"id": "cell", "label": "Cell", "members": ["D", "G"], "membrane": True}]},
            {"id": "p2", "row": 0, "type": "chart", "title": "Sparse XLSX", "height_mm": 50,
             "chart": {"kind": "bar", "data_file": sparse_xlsx, "sheet_name": "Fig3", "col_range": "B:C",
                       "orient": "columns", "y_cols": ["WT", "KO"], "agg": "mean_sd", "show_points": True, "unit": "fold"}}
        ]
    }, open(v16_spec, "w", encoding="utf-8"))
    v16_geom = os.path.join(wd, "v16_geom.json")
    r_v16 = run([os.path.join(HERE, "build_figure.py"), v16_spec, "--out-dir", wd, "--stem", "v16fig", "--geom", v16_geom])
    g16 = json.load(open(v16_geom, encoding="utf-8")) if os.path.exists(v16_geom) else {}
    s_vals = (((g16.get("panels") or {}).get("p2") or {}).get("series_data") or [{}])[0].get("values", [])
    # WT mean MUST be 1.1 (NOT polluted by KO's 5.2 from row 4!), KO mean MUST be 5.2!
    sparse_ok = (len(s_vals) == 2 and abs(s_vals[0] - 1.1) < 0.01 and abs(s_vals[1] - 5.2) < 0.01)
    # Unnamed external SVG edge_idx + from_text/to_text test
    un_svg = os.path.join(wd, "unnamed.svg")
    open(un_svg, "w", encoding="utf-8").write(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 150" width="360" height="150">'
        '<rect x="20" y="40" width="90" height="36" fill="#EAF2FB" stroke="#2E5E8C"/>'
        '<text x="65" y="62" text-anchor="middle" font-size="12">SRC</text>'
        '<rect x="230" y="40" width="90" height="36" fill="#D5F5E3" stroke="#1E8449"/>'
        '<text x="275" y="62" text-anchor="middle" font-size="12">DST</text>'
        '<line x1="110" y1="58" x2="230" y2="58" stroke="#2C3A47" stroke-width="2"/>'
        '</svg>')
    un_ops = os.path.join(wd, "un_ops.json")
    json.dump({"ops": [
        {"op": "set_marker", "edge_idx": 0, "marker": "tbar"},
        {"op": "add_node", "id": "node-C", "label": "OUT", "x": 230, "y": 100, "w": 90, "h": 34},
        {"op": "add_edge", "id": "edge-auto", "from_text": "DST", "to_text": "OUT", "marker": "arrow", "label": "drives"}
    ]}, open(un_ops, "w", encoding="utf-8"))
    r_un = run([os.path.join(HERE, "edit_svg.py"), un_svg, un_ops, "--out-dir", wd, "--stem", "un_ed", "--no-render"])
    un_d = json.loads(r_un.stdout) if r_un.returncode == 0 else {}
    check("v16: sparse XLSX col-align + bio shapes/membrane/preset + unnamed SVG edge_idx & from_text",
          r_v16.returncode == 0 and sparse_ok and r_un.returncode == 0 and not un_d.get("errors"),
          "vals=%s %s %s" % (s_vals, r_v16.stderr, r_un.stdout + r_un.stderr))

    # 12) v17: TB vertical side-channel feedback + group-aware ordering + stacked XLSX section_match + error verification
    stacked_xlsx = os.path.join(wd, "stacked_nature.xlsx")
    with _zf.ZipFile(stacked_xlsx, "w", _zf.ZIP_DEFLATED) as zf:
        zf.writestr("xl/workbook.xml",
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<sheets><sheet name="Fig3" sheetId="1" r:id="rId1"/></sheets></workbook>')
        zf.writestr("xl/_rels/workbook.xml.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        zf.writestr("xl/worksheets/sheet1.xml",
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
            '<row r="1"><c r="A1" t="inlineStr"><is><t>Fig. 3a Dummy</t></is></c></row>'
            '<row r="2"><c r="A2" t="inlineStr"><is><t>Ctrl</t></is></c><c r="B2" t="inlineStr"><is><t>Treated</t></is></c></row>'
            '<row r="3"><c r="A3"><v>1.0</v></c><c r="B3"><v>2.0</v></c></row>'
            '<row r="16"><c r="A16" t="inlineStr"><is><t>Fig. 3c Target mRNA</t></is></c></row>'
            '<row r="17"><c r="A17" t="inlineStr"><is><t>Ctrl</t></is></c><c r="B17" t="inlineStr"><is><t>Stim</t></is></c></row>'
            '<row r="18"><c r="A18"><v>1.0</v></c><c r="B18"><v>4.0</v></c></row>'
            '<row r="19"><c r="A19"><v>1.2</v></c><c r="B19"><v>4.6</v></c></row>'
            '<row r="20"><c r="A20"><v>0.8</v></c><c r="B20"><v>4.9</v></c></row>'
            '</sheetData></worksheet>')
    v17_spec = os.path.join(wd, "v17_spec.json")
    json.dump({
        "preset": "nature_double",
        "panels": [
            {"id": "p1", "row": 0, "type": "schematic", "title": "TB Feedback + Group-Aware", "direction": "TB",
             "nodes": [
                 {"id": "A", "label": "Receptor", "shape": "complex", "rank": 0, "source": {"file": "p.pdf", "locator": "p.3"}},
                 {"id": "B", "label": "Kinase1", "rank": 1, "source": {"file": "p.pdf", "locator": "p.3"}},
                 {"id": "X", "label": "Outside", "rank": 1, "source": {"file": "p.pdf", "locator": "p.3"}},
                 {"id": "C", "label": "Kinase2", "rank": 1, "source": {"file": "p.pdf", "locator": "p.3"}},
                 {"id": "D", "label": "TF", "shape": "round", "fill": "#0072B2", "badge": "4.5x", "rank": 2, "source": {"file": "p.pdf", "locator": "p.3"}},
                 {"id": "E", "label": "Gene", "shape": "gene", "rank": 3, "source": {"file": "p.pdf", "locator": "p.3"}}],
             "edges": [
                 {"from": "A", "to": "B", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.3"}},
                 {"from": "A", "to": "C", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.3"}},
                 {"from": "A", "to": "X", "kind": "assoc", "source": {"file": "p.pdf", "locator": "p.3"}},
                 {"from": "B", "to": "D", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.3"}},
                 {"from": "C", "to": "D", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.3"}},
                 {"from": "A", "to": "D", "kind": "activates", "label": "bypass", "source": {"file": "p.pdf", "locator": "p.3"}},
                 {"from": "D", "to": "E", "kind": "translocates", "label": "nuclear", "source": {"file": "p.pdf", "locator": "p.3"}},
                 {"from": "E", "to": "A", "kind": "inhibits", "label": "feedback", "source": {"file": "p.pdf", "locator": "p.3"}}],
             "groups": [{"id": "g_kin", "label": "Kinase Core", "members": ["B", "C", "D"], "membrane": True}]},
            {"id": "p2", "row": 0, "type": "chart", "title": "Stacked Subtable 3c", "height_mm": 54,
             "chart": {"kind": "bar", "data_file": stacked_xlsx, "sheet_name": "Fig3",
                       "section_match": "Fig. 3c", "orient": "columns",
                       "y_cols": ["Ctrl", "Stim"], "agg": "mean_sd", "show_points": True, "unit": "fold"}}
        ]
    }, open(v17_spec, "w", encoding="utf-8"))
    v17_geom = os.path.join(wd, "v17_geom.json")
    v17_aud = os.path.join(wd, "v17_aud.json")
    r_v17 = run([os.path.join(HERE, "build_figure.py"), v17_spec, "--out-dir", wd, "--stem", "v17fig", "--geom", v17_geom])
    r_v17a = run([os.path.join(HERE, "audit_figure.py"), v17_geom, "--spec", v17_spec, "--out", v17_aud])
    a17 = json.load(open(v17_aud, encoding="utf-8")) if os.path.exists(v17_aud) else {}
    g17 = json.load(open(v17_geom, encoding="utf-8")) if os.path.exists(v17_geom) else {}
    dv17 = (a17.get("data_verification") or {}).get("p2", {})
    v17_vals = (((g17.get("panels") or {}).get("p2") or {}).get("series_data") or [{}])[0].get("values", [])
    enc_warns = [w for w in a17.get("warnings", []) if "visually encloses" in w]
    check("v17: TB side-channel + group-aware + section_match + error SHA verification",
          r_v17.returncode == 0 and r_v17a.returncode == 0 and not enc_warns
          and dv17.get("verified") is True and dv17.get("n_errors_checked") == 2
          and len(v17_vals) == 2 and abs(v17_vals[1] - 4.5) < 0.01,
          "vals=%s dv=%s warns=%s %s" % (v17_vals, dv17, a17.get("warnings"), r_v17.stderr))

    # 13) v17: Transform-nested external SVG + color-keyed marker + multi-row auto-wrapping legend
    tf_svg = os.path.join(wd, "transformed.svg")
    open(tf_svg, "w", encoding="utf-8").write(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 320 140" width="320" height="140">'
        '<g id="grp-a" transform="translate(20, 30)"><rect x="0" y="0" width="80" height="36" fill="#EAF2FB" stroke="#2E5E8C"/>'
        '<text x="40" y="22" text-anchor="middle" font-size="12">ALPHA</text></g>'
        '<g id="grp-b" transform="translate(200, 30)"><rect x="0" y="0" width="80" height="36" fill="#D5F5E3" stroke="#1E8449"/>'
        '<text x="40" y="22" text-anchor="middle" font-size="12">BETA</text></g>'
        '</svg>')
    tf_ops = os.path.join(wd, "tf_ops.json")
    json.dump({"ops": [
        {"op": "add_edge", "id": "e-ab", "from_text": "ALPHA", "to_text": "BETA",
         "marker": "tbar", "color": "#C0392B", "label": "blocks"},
        {"op": "add_legend", "items": [
            {"kind": "activates", "label": "Activation"},
            {"kind": "inhibits", "label": "Inhibition"},
            {"kind": "translocates", "label": "Nuclear Entry"},
            {"kind": "swatch", "fill": "#0072B2", "label": "Core Kinase Hub"}]}
    ]}, open(tf_ops, "w", encoding="utf-8"))
    r_tf = run([os.path.join(HERE, "edit_svg.py"), tf_svg, tf_ops, "--out-dir", wd, "--stem", "tf_ed", "--no-render"])
    tf_d = json.loads(r_tf.stdout) if r_tf.returncode == 0 else {}
    tf_body = open(os.path.join(wd, "tf_ed.svg"), encoding="utf-8").read() if os.path.exists(os.path.join(wd, "tf_ed.svg")) else ""
    # Edge must connect world x=100 -> x=200 (NOT local x=80 -> x=0!), and use color-keyed tbar marker!
    check("v17: transform-nested SVG world auto-connect + color-keyed marker + wrap legend",
          r_tf.returncode == 0 and not tf_d.get("errors")
          and "100.00 48.00" in tf_body and "200.00 48.00" in tf_body and "mh-tbar-C0392B" in tf_body,
          r_tf.stdout + r_tf.stderr)

    # 14) v18: Synonym canonicalization + tolerant label endpoint resolution + composite SVG layers + unique IDs
    v18_spec = os.path.join(wd, "v18_spec.json")
    json.dump({
        "preset": "nature_double",
        "panels": [{
            "id": "p1", "type": "schematic", "title": "Synonym & Composite SVG Test", "direction": "LR",
            "nodes": [
                {"id": "Drug", "label": "Drug A", "shape": "small_molecule", "rank": 0, "source": {"file": "p.pdf", "locator": "p.2"}},
                {"id": "Kin", "label": "Target Kinase", "shape": "receptor", "badge": "↑ 4.2×", "rank": 1, "source": {"file": "p.pdf", "locator": "p.2"}},
                {"id": "TF", "label": "Factor Z", "shape": "promoter", "rank": 2, "source": {"file": "p.pdf", "locator": "p.2"}},
            ],
            "edges": [
                # Uses biological synonym "represses" AND node label "Target Kinase" instead of id "Kin"!
                {"from": "Drug", "to": "Target Kinase", "kind": "represses", "label": "blocks", "source": {"file": "p.pdf", "locator": "p.2"}},
                {"from": "Kin", "to": "Kin", "kind": "activates", "label": "auto-P", "source": {"file": "p.pdf", "locator": "p.2"}},
                {"from": "Kin", "to": "TF", "kind": "nuclear_import", "label": "import", "source": {"file": "p.pdf", "locator": "p.2"}},
            ],
            "groups": [{"id": "cell", "label": "Cell", "members": ["Kin", "TF"], "membrane": True}],
        }]
    }, open(v18_spec, "w", encoding="utf-8"))
    v18_geom = os.path.join(wd, "v18_geom.json")
    v18_chk = os.path.join(wd, "v18_chk.json")
    r_v18 = run([os.path.join(HERE, "build_figure.py"), v18_spec, "--out-dir", wd, "--stem", "v18fig", "--geom", v18_geom])
    r_v18c = run([os.path.join(HERE, "export_check.py"), "--svg", os.path.join(wd, "v18fig.svg"),
                  "--pdf", os.path.join(wd, "v18fig.pdf"), "--png", os.path.join(wd, "v18fig.png"),
                  "--width-mm", "180", "--dpi", "300", "--out", v18_chk])
    g18 = json.load(open(v18_geom, encoding="utf-8")) if os.path.exists(v18_geom) else {}
    c18 = json.load(open(v18_chk, encoding="utf-8")) if os.path.exists(v18_chk) else {}
    e18_kinds = [e.get("kind") for e in ((g18.get("panels") or {}).get("p1") or {}).get("edges", [])]
    svg18 = open(os.path.join(wd, "v18fig.svg"), encoding="utf-8").read() if os.path.exists(os.path.join(wd, "v18fig.svg")) else ""
    check("v18: synonym canonicalization + self-loop + label endpoint resolve + composite layers & unique XML IDs",
          r_v18.returncode == 0 and r_v18c.returncode == 0
          and e18_kinds == ["inhibits", "activates", "translocates"]
          and len(((g18.get("panels") or {}).get("p1") or {}).get("edges", [])[1].get("points", [])) == 4
          and c18.get("svg", {}).get("duplicate_ids") == 0
          and c18.get("svg", {}).get("composite_layers", 0) >= 6
          and 'data-source="p.pdf | p.2"' in svg18,
          "kinds=%s chk=%s %s" % (e18_kinds, c18.get("svg"), r_v18.stderr))

    # 15) v18: Round-trip composite SVG editing (retext badge-preserving + set_attr + swap_edge + delete)
    rt_ops = os.path.join(wd, "rt_ops.json")
    json.dump({"ops": [
        {"op": "retext", "gid": "node-Drug", "text": "Compound B"},
        {"op": "retext", "gid": "node-Kin", "text": "Kinase X"},
        {"op": "set_attr", "gid": "node-Drug", "attr": "fill", "value": "#FADBD8"},
        {"op": "swap_edge", "gid": "edge-Drug-Kin"},
        {"op": "delete", "gid": "edge-Kin-TF"},
    ]}, open(rt_ops, "w", encoding="utf-8"))
    r_rt = run([os.path.join(HERE, "edit_svg.py"), os.path.join(wd, "v18fig.svg"), rt_ops,
                "--out-dir", wd, "--stem", "v18_rt", "--no-render"])
    rt_d = json.loads(r_rt.stdout) if r_rt.returncode == 0 else {}
    rt_body = open(os.path.join(wd, "v18_rt.svg"), encoding="utf-8").read() if os.path.exists(os.path.join(wd, "v18_rt.svg")) else ""
    check("v18: round-trip composite SVG edit (badge-safe retext/set_attr/swap_edge/delete)",
          r_rt.returncode == 0 and not rt_d.get("errors")
          and "Compound B" in rt_body and "Kinase X" in rt_body and "↑ 4.2×" in rt_body
          and "#FADBD8" in rt_body and 'id="edge-Kin-TF"' not in rt_body,
          r_rt.stdout + r_rt.stderr)

    # 16) v18.1: Illustrator/BioRender SVG (CSS <style> class + matrix() + <tspan> coords + curved Bezier C)
    ai_svg = os.path.join(wd, "ai_curved.svg")
    open(ai_svg, "w", encoding="utf-8").write(
        '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="200" viewBox="0 0 400 200">'
        '<style>.st0{fill:#E0E0E0;stroke:#333;}</style>'
        '<g id="layer-a" transform="matrix(1 0 0 1 60 30)">'
        '<rect class="st0" x="0" y="0" width="80" height="36" rx="5"/>'
        '<text><tspan x="40" y="22">Ligand</tspan></text>'
        '</g>'
        '<path d="M 140 48 C 180 18 220 18 260 48" fill="none" stroke="#2C3A47" stroke-width="2"/>'
        '<g id="layer-b" transform="translate(260,30)">'
        '<rect class="st0" x="0" y="0" width="80" height="36" rx="5"/>'
        '<text><tspan x="40" y="22">Target</tspan></text>'
        '</g></svg>'
    )
    r_ai_ins = run([os.path.join(HERE, "edit_svg.py"), ai_svg, "--inspect"])
    ai_ins = json.loads(r_ai_ins.stdout) if r_ai_ins.returncode == 0 else {}
    ai_ops = os.path.join(wd, "ai_ops.json")
    json.dump({"ops": [
        {"op": "set_attr", "gid": "layer-a", "attr": "fill", "value": "#FADBD8"},
        {"op": "swap_edge", "edge_idx": 0},
        {"op": "set_marker", "edge_idx": 0, "marker": "tbar", "color": "#C0392B"},
    ]}, open(ai_ops, "w", encoding="utf-8"))
    r_ai_ed = run([os.path.join(HERE, "edit_svg.py"), ai_svg, ai_ops,
                   "--out-dir", wd, "--stem", "ai_edited", "--no-render"])
    ai_ed = json.loads(r_ai_ed.stdout) if r_ai_ed.returncode == 0 else {}
    ai_body = open(os.path.join(wd, "ai_edited.svg"), encoding="utf-8").read() if os.path.exists(os.path.join(wd, "ai_edited.svg")) else ""
    ai_t0 = (ai_ins.get("texts") or [{}])[0]
    check("v18.1: Illustrator CSS override + matrix()/<tspan> coords + curved Bezier edge_idx & reversal",
          r_ai_ins.returncode == 0 and r_ai_ed.returncode == 0 and not ai_ed.get("errors")
          and len(ai_ins.get("edges", [])) == 1
          and ai_t0.get("x") == 100.0 and ai_t0.get("y") == 52.0
          and "style=\"fill:#FADBD8\"" in ai_body
          and "M 260.000 48.000 C 220.000 18.000 180.000 18.000 140.000 48.000" in ai_body
          and "mh-tbar-C0392B" in ai_body,
          "ins=%s ed=%s body=%s" % (ai_ins, ai_ed, ai_body[:300]))

    # 17) v19: LR horizontal compartment separation + shape legend swatches + title prefix dedup + mean±SD CSV + compartments/legend_mapping in result.json
    v19_csv = os.path.join(wd, "pm_data.csv")
    open(v19_csv, "w", encoding="utf-8").write(
        "Group,Response\nVehicle,1.0 ± 0.12\nDrugA,4.8 +/- 0.35\nCombo,1.6 ± 0.18\n"
    )
    v19_in = os.path.join(wd, "v19_in")
    v19_wk = os.path.join(wd, "v19_wk")
    v19_out = os.path.join(wd, "v19_out")
    os.makedirs(v19_in, exist_ok=True)
    open(os.path.join(v19_in, "case.json"), "w", encoding="utf-8").write(json.dumps({
        "case_id": "v19-selftest", "task": "Build multi-compartment LR figure + pm_data chart."
    }))
    v19_plan = os.path.join(v19_wk, "plan.json")
    os.makedirs(v19_wk, exist_ok=True)
    json.dump({
        "case_id": "v19-selftest", "stem": "v19fig", "preset": "nature_double",
        "panels": [
            {"id": "p1", "row": 0, "type": "schematic", "title": "A. Three-Compartment LR Cascade", "direction": "LR",
             "nodes": [
                 {"id": "L", "label": "Ligand", "shape": "ellipse", "fill": "#FDEBD0", "rank": 0, "source": {"file": "p.pdf", "locator": "p.1"}},
                 {"id": "R", "label": "Receptor", "shape": "complex", "fill": "#EAF2FB", "rank": 1, "source": {"file": "p.pdf", "locator": "p.1"}},
                 {"id": "K", "label": "Kinase", "shape": "round", "fill": "#0072B2", "badge": "↑ 4.8×", "rank": 1, "source": {"file": "p.pdf", "locator": "p.1"}},
                 {"id": "G", "label": "Gene X", "shape": "gene", "fill": "#D5F5E3", "rank": 2, "source": {"file": "p.pdf", "locator": "p.1"}},
             ],
             "edges": [
                 {"from": "L", "to": "R", "kind": "binds", "source": {"file": "p.pdf", "locator": "p.1"}},
                 {"from": "R", "to": "K", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.1"}},
                 {"from": "K", "to": "G", "kind": "translocates", "source": {"file": "p.pdf", "locator": "p.1"}},
             ],
             "groups": [
                 {"id": "ext", "label": "Extracellular", "members": ["L"]},
                 {"id": "cyto", "label": "Cytoplasm", "members": ["R", "K"], "membrane": True},
                 {"id": "nuc", "label": "Nucleus", "members": ["G"]},
             ],
             "legend": {"title": "Legend", "items": [
                 {"shape": "ellipse", "fill": "#FDEBD0", "label": "Ligand"},
                 {"kind": "binds", "label": "Binding"},
                 {"kind": "activates", "label": "Activation"},
                 {"kind": "translocates", "label": "Nuclear import"},
             ]}},
            {"id": "p2", "row": 1, "type": "chart", "title": "B. Mean ± SD Auto-Parsed Quantification", "height_mm": 50,
             "chart": {"kind": "bar", "data_file": v19_csv, "x_col": "Group", "y_cols": ["Response"],
                       "y_label": "Signal", "unit": "fold", "legend": False}},
        ],
    }, open(v19_plan, "w", encoding="utf-8"))
    r_v19 = run([os.path.join(HERE, "run_pipeline.py"), "deliver", v19_plan,
                 "--input", v19_in, "--work", v19_wk, "--out", v19_out])
    v19_res = json.load(open(os.path.join(v19_out, "result.json"), encoding="utf-8")) if os.path.exists(os.path.join(v19_out, "result.json")) else {}
    v19_svg = open(os.path.join(v19_out, "v19fig.svg"), encoding="utf-8").read() if os.path.exists(os.path.join(v19_out, "v19fig.svg")) else ""
    v19_dm_errs = ((v19_res.get("data_mapping") or {}).get("p2") or {}).get("series", [{}])[0].get("errors")
    check("v19: LR multi-compartment gap + shape swatches + title dedup + mean±SD auto-err + result compartments/legend_mapping",
          r_v19.returncode == 0 and v19_res.get("status") == "ok"
          and not (v19_res.get("checks", {}).get("geometry_audit", {}).get("warnings") or [])
          and len(v19_res.get("compartments") or []) == 3
          and len(((v19_res.get("legend_mapping") or {}).get("p1") or {}).get("entries") or []) == 4
          and v19_dm_errs == [0.12, 0.35, 0.18]
          and "A. Three-Compartment" not in v19_svg and "Three-Compartment LR Cascade" in v19_svg,
          "status=%s warns=%s errs=%s" % (
              v19_res.get("status"),
              v19_res.get("checks", {}).get("geometry_audit", {}).get("warnings"),
              v19_dm_errs))

    # 18) v19: XLSX horizontal <mergeCell> header propagation
    mx_path = os.path.join(wd, "merged_hdr.xlsx")
    with zipfile.ZipFile(mx_path, "w") as zf:
        zf.writestr("[Content_Types].xml",
                    '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                    '<Default Extension="xml" ContentType="application/xml"/></Types>')
        zf.writestr("xl/workbook.xml",
                    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    '<sheets><sheet name="Merged" sheetId="1" r:id="rId1"/></sheets></workbook>')
        zf.writestr("xl/_rels/workbook.xml.rels",
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        zf.writestr("xl/worksheets/sheet1.xml",
                    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    '<sheetData>'
                    '<row r="1"><c r="A1" t="inlineStr"><is><t>Condition</t></is></c>'
                    '<c r="B1" t="inlineStr"><is><t>TreatmentGroup</t></is></c></row>'
                    '<row r="2"><c r="A2" t="inlineStr"><is><t>Day1</t></is></c>'
                    '<c r="B2"><v>1.2</v></c><c r="C2"><v>2.4</v></c><c r="D2"><v>3.6</v></c></row>'
                    '</sheetData>'
                    '<mergeCells count="1"><mergeCell ref="B1:D1"/></mergeCells>'
                    '</worksheet>')
    import read_case as _RC
    with zipfile.ZipFile(mx_path, "r") as zf:
        mrows = _RC._read_xlsx_sheet_rows(zf, "xl/worksheets/sheet1.xml", [], max_rows=10)
    check("v19: XLSX horizontal mergeCell header propagation",
          len(mrows) >= 2 and mrows[0][:4] == ["Condition", "TreatmentGroup", "TreatmentGroup", "TreatmentGroup"],
          str(mrows))

    # 19) v20: PDF excerpt budget separation (captions + cross-page mentions NEVER starve full pages) + DELIVER plotted values
    import run_pipeline as _RP
    fake_pdf = "\n\n".join([
        "--- PAGE %d ---\n" % pno + (
            ("Fig. 3 | Mechanistic pathway of Compound-X (50 nM) inhibiting kinase K.\n"
             + "Detailed results line " * 40 + "\n" + "Additional methods line " * 40)
            if pno == 4 else
            ("In Fig. 3b, Compound-X reduced p-Target by 78% (P=0.0002).\n" + "Body text " * 120)
            if pno in (2, 3, 6, 7) else
            ("Background discussion " * 120)
        )
        for pno in range(1, 10)
    ])
    _, ex20 = _RP._extract_target_pdf_excerpts(fake_pdf, "Reproduce Fig. 3 from paper.pdf", budget=6500)
    check("v20: PDF excerpt keeps coherent full pages (>=2) alongside verbatim caption & cross-page mentions",
          "=== TARGET CAPTIONS (VERBATIM) ===" in ex20
          and ex20.count("--- PAGE ") >= 2
          and "plotted[Response]: [1.0±0.12, 4.8±0.35, 1.6±0.18]" in r_v19.stdout
          and "compartments: Extracellular[" in r_v19.stdout
          and "ns2:" not in v19_svg,
          "pages=%d stdout=%s" % (ex20.count("--- PAGE "), r_v19.stdout[-260:]))

    # 20) v21: Adjacent-rank mutual feedback parallel pair + TB same-rank non-adjacent horizontal arc (zero node crossings!)
    v21_spec = os.path.join(wd, "v21_tb.json")
    json.dump({
        "preset": "nature_double",
        "panels": [{
            "id": "p1", "type": "schematic", "title": "Mutual Feedback & Same-Rank Arc (TB)", "direction": "TB",
            "nodes": [
                {"id": "Stress", "label": "DNA Damage", "shape": "ellipse", "rank": 0, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "p53", "label": "p53", "shape": "round", "fill": "#0072B2", "rank": 1, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "MDM2", "label": "MDM2", "shape": "hexagon", "fill": "#FADBD8", "rank": 2, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "p21", "label": "p21", "shape": "gene", "fill": "#D5F5E3", "rank": 2, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "PUMA", "label": "PUMA", "shape": "gene", "fill": "#D5F5E3", "rank": 2, "source": {"file": "p.pdf", "locator": "p.1"}},
            ],
            "edges": [
                {"from": "Stress", "to": "p53", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "p53", "to": "MDM2", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "MDM2", "to": "p53", "kind": "inhibits", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "p53", "to": "p21", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "p53", "to": "PUMA", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.1"}},
                # Same-rank non-adjacent edge (MDM2 -> PUMA across middle node p21!)
                {"from": "MDM2", "to": "PUMA", "kind": "inhibits", "label": "blocks", "source": {"file": "p.pdf", "locator": "p.1"}},
            ],
        }]
    }, open(v21_spec, "w", encoding="utf-8"))
    v21_geom = os.path.join(wd, "v21_geom.json")
    v21_aud = os.path.join(wd, "v21_aud.json")
    r_v21b = run([os.path.join(HERE, "build_figure.py"), v21_spec, "--out-dir", wd, "--stem", "v21tb", "--geom", v21_geom])
    r_v21a = run([os.path.join(HERE, "audit_figure.py"), v21_geom, "--spec", v21_spec, "--out", v21_aud])
    aud21 = json.load(open(v21_aud, encoding="utf-8")) if os.path.exists(v21_aud) else {}
    g21 = json.load(open(v21_geom, encoding="utf-8")) if os.path.exists(v21_geom) else {}
    e_mdm_p53 = next((e for e in g21.get("panels", {}).get("p1", {}).get("edges", []) if e["id"] == "MDM2-p53"), {})
    e_same_rk = next((e for e in g21.get("panels", {}).get("p1", {}).get("edges", []) if e["id"] == "MDM2-PUMA"), {})
    check("v21: adjacent mutual feedback parallel pair + TB same-rank arc (0 warnings / 0 crossings)",
          r_v21b.returncode == 0 and r_v21a.returncode == 0
          and aud21.get("n_errors") == 0 and aud21.get("n_warnings") == 0
          and len(e_mdm_p53.get("points", [])) == 2
          and len(e_same_rk.get("points", [])) == 4,
          "aud=%s mdm_p53=%s same_rk=%s" % (aud21.get("warnings"), e_mdm_p53.get("points"), e_same_rk.get("points")))

    # 21) v21: col_groups replicate-column chart aggregation + tall XLSX sub-table scanner past row 28
    cg_csv = os.path.join(wd, "col_groups.csv")
    open(cg_csv, "w", encoding="utf-8").write(
        "Gene,Ctrl_1,Ctrl_2,Ctrl_3,Drug_1,Drug_2,Drug_3\n"
        "IL6,1.0,1.1,0.9,5.0,5.2,4.8\n"
        "STAT3,1.0,0.95,1.05,3.2,3.0,3.4\n"
    )
    import fig_chart as _FC
    cg_res = _FC.load_chart_table({
        "kind": "bar", "data_file": cg_csv, "x_col": "Gene",
        "col_groups": {"Control": ["Ctrl_1", "Ctrl_2", "Ctrl_3"], "Drug": ["Drug_1", "Drug_2", "Drug_3"]},
        "agg": "mean_sd",
    })
    check("v21: col_groups replicate-column aggregation (mean ± SD + replicate points)",
          cg_res.get("categories") == ["IL6", "STAT3"]
          and len(cg_res.get("series", [])) == 2
          and abs(cg_res["series"][1]["values"][0] - 5.0) < 1e-6
          and len(cg_res["series"][1]["points"][0]) == 3,
          str(cg_res.get("series")))

    # 22) v21: edit_svg add_group compartment behind nodes + synced edge stroke arrowhead recoloring
    ag_ops = os.path.join(wd, "ag_ops.json")
    json.dump({"ops": [
        {"op": "add_group", "id": "group-sig", "label": "Signaling Zone", "members_text": ["Ligand", "Target"], "membrane": True},
        {"op": "set_marker", "edge_idx": 0, "marker": "arrow", "color": "#1E3A5F"},
        {"op": "set_attr", "gid": "layer-a", "attr": "font-weight", "value": "bold"},
    ]}, open(ag_ops, "w", encoding="utf-8"))
    r_ag = run([os.path.join(HERE, "edit_svg.py"), ai_svg, ag_ops, "--out-dir", wd, "--stem", "ai_grp", "--no-render"])
    ag_d = json.loads(r_ag.stdout) if r_ag.returncode == 0 else {}
    ag_body = open(os.path.join(wd, "ai_grp.svg"), encoding="utf-8").read() if os.path.exists(os.path.join(wd, "ai_grp.svg")) else ""
    check("v21: edit_svg add_group (behind art + membrane) + direct text style set_attr",
          r_ag.returncode == 0 and not ag_d.get("errors")
          and 'id="group-sig"' in ag_body and "Signaling Zone" in ag_body
          and ag_body.index('id="group-sig"') < ag_body.index('id="layer-a"')
          and "font-weight:bold" in ag_body,
          r_ag.stdout + r_ag.stderr)

    # 23) v22: Compartment non-member separation (zero false enclosure in multi-rank TB compartment!)
    v22_sep_spec = os.path.join(wd, "v22_sep.json")
    json.dump({
        "preset": "nature_double",
        "panels": [{
            "id": "p1", "type": "schematic", "title": "Compartment Non-Member Separation", "direction": "TB",
            "nodes": [
                {"id": "DDR", "label": "DNA Damage", "shape": "ellipse", "rank": 0, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "ATM", "label": "ATM/CHK2", "shape": "complex", "rank": 1, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "Nutlin", "label": "Nutlin-3a", "shape": "hexagon", "fill": "#FADBD8", "rank": 2, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "p53", "label": "p53", "shape": "round", "fill": "#0072B2", "rank": 2, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "MDM2", "label": "MDM2", "shape": "hexagon", "rank": 3, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "p21", "label": "CDKN1A", "shape": "gene", "rank": 3, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "PUMA", "label": "BBC3", "shape": "gene", "rank": 3, "source": {"file": "p.pdf", "locator": "p.1"}},
            ],
            "edges": [
                {"from": "DDR", "to": "ATM", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "ATM", "to": "p53", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "Nutlin", "to": "MDM2", "kind": "inhibits", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "p53", "to": "MDM2", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "MDM2", "to": "p53", "kind": "inhibits", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "p53", "to": "p21", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "p53", "to": "PUMA", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.1"}},
            ],
            "groups": [{"id": "nuc", "label": "Nucleus", "members": ["ATM", "p53", "MDM2", "p21", "PUMA"], "membrane": True}],
        }]
    }, open(v22_sep_spec, "w", encoding="utf-8"))
    v22_g, v22_a = os.path.join(wd, "v22_g.json"), os.path.join(wd, "v22_a.json")
    r22b = run([os.path.join(HERE, "build_figure.py"), v22_sep_spec, "--out-dir", wd, "--stem", "v22sep", "--geom", v22_g])
    r22a = run([os.path.join(HERE, "audit_figure.py"), v22_g, "--spec", v22_sep_spec, "--out", v22_a])
    aud22 = json.load(open(v22_a, encoding="utf-8")) if os.path.exists(v22_a) else {}
    check("v22: compartment non-member separation (0 errors & 0 false-enclosure warnings)",
          r22b.returncode == 0 and r22a.returncode == 0
          and aud22.get("n_errors") == 0
          and not any("encloses non-member" in w for w in aud22.get("warnings", [])),
          str(aud22.get("warnings")) + str(aud22.get("errors")))

    # 24) v22: Repeated/merged 2-row headers auto-aggregation + partial None/NaN error bar audit pass
    dup_csv = os.path.join(wd, "dup_headers.csv")
    open(dup_csv, "w", encoding="utf-8").write(
        ",WT,WT,WT,KO,KO,KO\n"
        "Gene,Rep1,Rep2,Rep3,Rep1,Rep2,Rep3\n"
        "IL6,1.0,1.1,0.9,5.0,5.2,4.8\n"
        "TNF,1.0,,,3.2,3.0,3.4\n"
    )
    dup_spec = os.path.join(wd, "v22_dup_chart.json")
    json.dump({
        "preset": "nature_single",
        "panels": [{
            "id": "p1", "type": "chart", "title": "Merged Replicate Headers", "height_mm": 50,
            "chart": {"kind": "bar", "data_file": dup_csv, "x_col": "Gene", "y_cols": ["WT", "KO"],
                      "agg": "mean_sd", "show_points": True, "y_label": "mRNA", "unit": "fold"}
        }]
    }, open(dup_spec, "w", encoding="utf-8"))
    v22_cg, v22_ca = os.path.join(wd, "v22_cg.json"), os.path.join(wd, "v22_ca.json")
    r22cb = run([os.path.join(HERE, "build_figure.py"), dup_spec, "--out-dir", wd, "--stem", "v22dup", "--geom", v22_cg])
    r22ca = run([os.path.join(HERE, "audit_figure.py"), v22_cg, "--spec", dup_spec, "--out", v22_ca])
    aud22c = json.load(open(v22_ca, encoding="utf-8")) if os.path.exists(v22_ca) else {}
    dv22 = (aud22c.get("data_verification") or {}).get("p1") or {}
    check("v22: repeated 2-row replicate headers auto-agg + partial NaN error bar audit pass",
          r22cb.returncode == 0 and r22ca.returncode == 0
          and aud22c.get("n_errors") == 0 and dv22.get("verified") is True
          and dv22.get("n_values_checked") == 4,
          str(aud22c))

    # 25) v22: edit_svg removes orphaned unnamed polygon arrowheads on swap_edge & set_marker
    poly_svg = os.path.join(wd, "drawio_poly.svg")
    open(poly_svg, "w", encoding="utf-8").write(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 300 120" width="300" height="120">\n'
        '  <rect x="20" y="40" width="70" height="36" fill="#EAF2FB" stroke="#1E3A5F"/>\n'
        '  <text x="55" y="62" text-anchor="middle" font-size="12">Src</text>\n'
        '  <rect x="200" y="40" width="70" height="36" fill="#D5F5E3" stroke="#1E3A5F"/>\n'
        '  <text x="235" y="62" text-anchor="middle" font-size="12">Dst</text>\n'
        '  <line x1="90" y1="58" x2="196" y2="58" stroke="#1E3A5F" stroke-width="2"/>\n'
        '  <polygon points="192,53 200,58 192,63" fill="#1E3A5F"/>\n'
        '</svg>\n'
    )
    poly_ops = os.path.join(wd, "poly_ops.json")
    json.dump({"ops": [
        {"op": "swap_edge", "edge_idx": 0},
        {"op": "set_marker", "edge_idx": 0, "marker": "tbar", "color": "#C0392B"},
    ]}, open(poly_ops, "w", encoding="utf-8"))
    r22p = run([os.path.join(HERE, "edit_svg.py"), poly_svg, poly_ops, "--out-dir", wd, "--stem", "poly_ed", "--no-render"])
    p22_body = open(os.path.join(wd, "poly_ed.svg"), encoding="utf-8").read() if os.path.exists(os.path.join(wd, "poly_ed.svg")) else ""
    check("v22: edit_svg removes orphaned unnamed polygon arrowhead on swap_edge + set_marker(tbar)",
          r22p.returncode == 0 and "<polygon" not in p22_body and "mh-tbar" in p22_body,
          p22_body[:240])

    # 26) v22: Main Fig. 3 outranks Extended Data Fig. 3 + emits [PDF_READ_HINT] + EDIT_ERRORS blocks ALL CHECKS PASSED
    pdf22 = (
        "--- PAGE 1 ---\nIntro " + ("w " * 1800) + "\n\n"
        "--- PAGE 2 ---\nExtended Data Fig. 3 | Supplementary control assay.\n" + ("ext " * 900) + "\n\n"
        "--- PAGE 3 ---\nFig. 3 | Main p53-MDM2 mechanism and qPCR quantification.\n" + ("main " * 1100) + "\n\n"
        "--- PAGE 4 ---\nResults continued: As shown in Fig. 3d, Nutlin increases p21 by 6.2-fold.\n" + ("res " * 1100) + "\n\n"
        "--- PAGE 5 ---\nDiscussion referencing Fig. 3e kinetics.\n" + ("disc " * 1100)
    )
    _, ex22 = _RP._extract_target_pdf_excerpts(pdf22, "Reproduce Fig. 3 mechanism", budget=5000)
    bad_edit_plan = os.path.join(wd, "bad_edit_plan.json")
    json.dump({"case_id": "v22-edit-err", "mode": "edit", "edit_svg": poly_svg, "stem": "bad_ed",
               "ops": [{"op": "retext", "gid": "does-not-exist", "text": "X"}]},
              open(bad_edit_plan, "w", encoding="utf-8"))
    r22ed = run([os.path.join(HERE, "run_pipeline.py"), "deliver", bad_edit_plan,
                 "--input", wd, "--work", wd, "--out", os.path.join(wd, "bad_ed_out")])
    check("v22: main Fig.3 outranks Extended Data + [PDF_READ_HINT] + EDIT_ERRORS blocks ALL CHECKS PASSED",
          ex22.index("Main p53-MDM2") < ex22.index("Extended Data Fig. 3")
          and "[PDF_READ_HINT]" in ex22
          and "EDIT_ERRORS:" in r22ed.stdout
          and "ALL CHECKS PASSED" not in r22ed.stdout,
          "hint=%s out=%s" % ("[PDF_READ_HINT]" in ex22, r22ed.stdout[-240:]))

    # 27) v23: Wrapped multi-row LR routing (0 node crossings across wrapped rows + multi-compartment + side feedback)
    v23_spec = os.path.join(wd, "v23_wraplr.json")
    json.dump({
        "preset": "nature_double",
        "panels": [{
            "id": "p1", "type": "schematic", "title": "Wrapped LR Cascade", "direction": "LR",
            "nodes": [
                {"id": "IGF1", "label": "IGF-1", "shape": "ellipse", "rank": 0, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "RTK", "label": "IGF1R", "shape": "complex", "rank": 1, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "Drug", "label": "Alpelisib", "shape": "hexagon", "rank": 2, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "PI3K", "label": "PI3K", "shape": "round", "rank": 2, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "PTEN", "label": "PTEN", "shape": "hexagon", "rank": 3, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "AKT", "label": "AKT", "shape": "round", "rank": 3, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "TSC", "label": "TSC1/2", "shape": "complex", "rank": 4, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "mTOR", "label": "mTORC1", "shape": "round", "rank": 5, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "S6K", "label": "S6K1", "shape": "round", "rank": 6, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "FOXO", "label": "FOXO3a", "shape": "gene", "rank": 6, "source": {"file": "p.pdf", "locator": "p.1"}},
                {"id": "Grow", "label": "Growth", "shape": "stadium", "rank": 7, "source": {"file": "p.pdf", "locator": "p.1"}},
            ],
            "edges": [
                {"from": "IGF1", "to": "RTK", "kind": "binds", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "RTK", "to": "PI3K", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "Drug", "to": "PI3K", "kind": "inhibits", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "PI3K", "to": "AKT", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "PTEN", "to": "AKT", "kind": "inhibits", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "AKT", "to": "TSC", "kind": "inhibits", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "TSC", "to": "mTOR", "kind": "inhibits", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "mTOR", "to": "S6K", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "S6K", "to": "RTK", "kind": "inhibits", "label": "feedback", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "AKT", "to": "FOXO", "kind": "inhibits_dashed", "source": {"file": "p.pdf", "locator": "p.1"}},
                {"from": "S6K", "to": "Grow", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.1"}},
            ],
            "groups": [
                {"id": "ext", "label": "Extracellular", "members": ["IGF1"]},
                {"id": "cyto", "label": "Cytoplasm", "members": ["PI3K", "PTEN", "AKT", "TSC", "mTOR", "S6K"], "membrane": True},
                {"id": "nuc", "label": "Nucleus", "members": ["FOXO", "Grow"]},
            ],
        }]
    }, open(v23_spec, "w", encoding="utf-8"))
    v23_g, v23_a = os.path.join(wd, "v23_g.json"), os.path.join(wd, "v23_a.json")
    r23b = run([os.path.join(HERE, "build_figure.py"), v23_spec, "--out-dir", wd, "--stem", "v23lr", "--geom", v23_g])
    r23a = run([os.path.join(HERE, "audit_figure.py"), v23_g, "--spec", v23_spec, "--out", v23_a])
    aud23 = json.load(open(v23_a, encoding="utf-8")) if os.path.exists(v23_a) else {}
    check("v23: wrapped multi-row LR multi-compartment routing (0 errors & 0 warnings / 0 crossings)",
          r23b.returncode == 0 and r23a.returncode == 0
          and aud23.get("n_errors") == 0 and aud23.get("n_warnings") == 0,
          str(aud23.get("warnings")) + str(aud23.get("errors")))

    # 28) v23: Unicode minus + sci-notation + section_match in col A with col_range="B:D"
    uni_csv = os.path.join(wd, "uni_sec.csv")
    open(uni_csv, "w", encoding="utf-8").write(
        "Fig. 3a: Top,,,\n"
        ",Pathway,NES,FDR\n"
        ",Skip,0.1,0.9\n"
        "Fig. 3b: GSEA,,,\n"
        ",Pathway,NES,FDR\n"
        ",MYC,\u22122.45 \u00b1 0.18,1.2e-4\n"
        ",p53,2.38 \u00b1 0.16,1.0e-4\n"
    )
    uni_res = _FC.load_chart_table({
        "kind": "barh", "data_file": uni_csv, "section_match": "Fig. 3b", "col_range": "B:D",
        "x_col": "Pathway", "y_cols": ["NES"],
    })
    check("v23: Unicode minus/sci-notation + section_match in col A before col_range B:D",
          uni_res.get("categories") == ["MYC", "p53"]
          and abs(uni_res["series"][0]["values"][0] - (-2.45)) < 1e-6
          and abs(uni_res["series"][0]["errors"][0] - 0.18) < 1e-6,
          str(uni_res.get("series")))

    # 29) v23: edit_svg set_attr(stroke) syncs inline-CSS matplotlib arrowhead color
    sync_ops = os.path.join(wd, "v23_sync_ops.json")
    json.dump({"ops": [{"op": "set_attr", "gid": "edge-RTK-PI3K", "attr": "stroke", "value": "#009E73"}]},
              open(sync_ops, "w", encoding="utf-8"))
    r23s = run([os.path.join(HERE, "edit_svg.py"), os.path.join(wd, "v23lr.svg"), sync_ops,
                "--out-dir", wd, "--stem", "v23lr_ed", "--no-render"])
    s23_body = open(os.path.join(wd, "v23lr_ed.svg"), encoding="utf-8").read() if os.path.exists(os.path.join(wd, "v23lr_ed.svg")) else ""
    import xml.etree.ElementTree as _ET23
    r23_root = _ET23.fromstring(s23_body) if s23_body else None
    hd_el = next((el for el in r23_root.iter() if el.get("id") == "edge-RTK-PI3K-head"), None) if r23_root is not None else None
    hd_txt = _ET23.tostring(hd_el, encoding="unicode") if hd_el is not None else ""
    check("v23: edit_svg set_attr(stroke) syncs inline-CSS matplotlib composite arrowhead fill",
          r23s.returncode == 0 and "#009E73" in hd_txt,
          hd_txt[:220])

    # 30) v24: semantic SVG edge endpoint inference + from_text/to_text targeting + closed <path> node + post-edit relation_inventory
    v24_svg = os.path.join(wd, "v24_unnamed_path.svg")
    open(v24_svg, "w", encoding="utf-8").write(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 140" width="360" height="140">\n'
        '  <path d="M 20 50 L 90 50 L 90 86 L 20 86 Z" fill="#EAF2FB" stroke="#1E3A5F"/>\n'
        '  <text x="55" y="72" text-anchor="middle" font-size="12">TLR4</text>\n'
        '  <path d="M 145 50 L 215 50 L 215 86 L 145 86 Z" fill="#EAF2FB" stroke="#1E3A5F"/>\n'
        '  <text x="180" y="72" text-anchor="middle" font-size="12">MyD88</text>\n'
        '  <rect x="270" y="50" width="70" height="36" fill="#D5F5E3" stroke="#1E3A5F"/>\n'
        '  <text x="305" y="72" text-anchor="middle" font-size="12">NFkB</text>\n'
        '  <line x1="90" y1="68" x2="141" y2="68" stroke="#1E3A5F" stroke-width="2"/>\n'
        '  <polygon points="137,63 145,68 137,73" fill="#1E3A5F"/>\n'
        '  <line x1="215" y1="68" x2="266" y2="68" stroke="#1E3A5F" stroke-width="2"/>\n'
        '  <polygon points="262,63 270,68 262,73" fill="#1E3A5F"/>\n'
        '</svg>\n'
    )
    r24i = run([os.path.join(HERE, "edit_svg.py"), v24_svg, "--inspect"])
    ins24 = json.loads(r24i.stdout) if r24i.returncode == 0 else {}
    e24 = ins24.get("edges", [])
    v24_plan = os.path.join(wd, "v24_edit_plan.json")
    json.dump({
        "case_id": "v24-sem-edit", "mode": "edit", "edit_svg": v24_svg, "stem": "v24_ed",
        "ops": [
            {"op": "set_marker", "from_text": "MyD88", "to_text": "NFkB", "marker": "tbar", "color": "#C0392B"},
            {"op": "set_attr", "by_text": "TLR4", "attr": "fill", "value": "#FDEBD0"},
        ]
    }, open(v24_plan, "w", encoding="utf-8"))
    v24_e_in = os.path.join(wd, "v24_e_in")
    os.makedirs(v24_e_in, exist_ok=True)
    v24_out = os.path.join(wd, "v24_ed_out")
    r24d = run([os.path.join(HERE, "run_pipeline.py"), "deliver", v24_plan,
                "--input", v24_e_in, "--work", wd, "--out", v24_out])
    res24_ed = json.load(open(os.path.join(v24_out, "result.json"), encoding="utf-8")) if os.path.exists(os.path.join(v24_out, "result.json")) else {}
    ed24_svg_body = open(os.path.join(v24_out, "v24_ed.svg"), encoding="utf-8").read() if os.path.exists(os.path.join(v24_out, "v24_ed.svg")) else ""
    rels24 = res24_ed.get("relation_inventory", [])
    check("v24: semantic SVG edge inference + from_text/to_text targeting + closed <path> fill + full post-edit relations",
          len(e24) == 2 and e24[0].get("from_label") == "TLR4" and e24[1].get("to_label") == "NFkB"
          and r24d.returncode == 0 and "ALL CHECKS PASSED" in r24d.stdout
          and "#FDEBD0" in ed24_svg_body
          and any(r.get("subject") == "MyD88" and r.get("object") == "NFkB" and r.get("kind") == "inhibits" for r in rels24)
          and "edit_relations" in r24d.stdout,
          "e24=%s rels=%s out=%s" % (e24, rels24, r24d.stdout[-180:]))

    # 31) v24: multi-PDF non-colliding page index + multi-paragraph blank-line Fig. 3 caption verbatim
    mpdf24 = (
        "=== FILE: /input/main_paper.pdf ===\n"
        "--- PAGE 1 ---\nTitle & Abstract " + ("a " * 1400) + "\n\n"
        "--- PAGE 2 ---\nFig. 3 | PI3K-AKT-mTOR cascade and IC50 response.\n\n"
        "a, Schematic of IGF1R-PI3K-AKT axis.\n\n"
        "b, GSEA NES bar plot.\n\n"
        "c, IC50 quantification across replicates.\n" + ("m " * 900) + "\n\n"
        "=== FILE: /input/supp_info.pdf ===\n"
        "--- PAGE 1 ---\nExtended Data Fig. 3 | Supplementary control.\n" + ("s " * 900)
    )
    pidx24, ex24 = _RP._extract_target_pdf_excerpts(mpdf24, "Reproduce Fig. 3", budget=5500)
    check("v24: multi-PDF non-colliding page index + blank-line multi-paragraph Fig. 3 caption intact",
          any("main_paper.pdf p.2" in x for x in pidx24)
          and any("supp_info.pdf p.1" in x for x in pidx24)
          and "c, IC50 quantification" in ex24.split("=== TARGET CAPTIONS (VERBATIM) ===")[1][:600],
          "pidx=%s cap=%s" % (pidx24, ex24[:320]))

    # 32) v24: XLSX vertical merged group labels (A2:A4=WT) + CSV stacked subtable preview
    vmerge_xlsx = os.path.join(wd, "v24_vmerge.xlsx")
    with zipfile.ZipFile(vmerge_xlsx, "w") as zf:
        zf.writestr("xl/workbook.xml",
                    '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                    '<sheets><sheet name="Fig3" sheetId="1" r:id="rId1"/></sheets></workbook>')
        zf.writestr("xl/_rels/workbook.xml.rels",
                    '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
        zf.writestr("xl/sharedStrings.xml",
                    '<?xml version="1.0"?><sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    '<si><t>Group</t></si><si><t>Signal</t></si><si><t>WT</t></si><si><t>KO</t></si></sst>')
        zf.writestr("xl/worksheets/sheet1.xml",
                    '<?xml version="1.0"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                    '<sheetData>'
                    '<row r="1"><c r="A1" t="s"><v>0</v></c><c r="B1" t="s"><v>1</v></c></row>'
                    '<row r="2"><c r="A2" t="s"><v>2</v></c><c r="B2"><v>10</v></c></row>'
                    '<row r="3"><c r="B3"><v>12</v></c></row>'
                    '<row r="4"><c r="B4"><v>14</v></c></row>'
                    '<row r="5"><c r="A5" t="s"><v>3</v></c><c r="B5"><v>2</v></c></row>'
                    '<row r="6"><c r="B6"><v>4</v></c></row>'
                    '</sheetData>'
                    '<mergeCells count="2"><mergeCell ref="A2:A4"/><mergeCell ref="A5:A6"/></mergeCells>'
                    '</worksheet>')
    vm_res = _FC.load_chart_table({"kind": "bar", "data_file": vmerge_xlsx, "sheet_name": "Fig3",
                                   "x_col": "Group", "y_cols": ["Signal"], "agg": "mean_sd"})
    check("v24: XLSX vertical merged group labels (A2:A4=WT) preserve all replicates in mean_sd agg",
          vm_res.get("categories") == ["WT", "KO"]
          and abs(vm_res["series"][0]["values"][0] - 12.0) < 1e-6
          and vm_res["series"][0].get("n") == [3, 2],
          str(vm_res.get("series")))

    # 33) v24: hex legend_mapping + provenance_summary + source_manifest + contract aliases + opposing-edge/dangling-group audit
    v24_in = os.path.join(wd, "v24_c_in")
    os.makedirs(v24_in, exist_ok=True)
    json.dump({
        "case_id": "v24-meta",
        "output_contract": {"required": ["case_id", "editable_svg", "entities", "relations", "data_verification", "provenance"]},
    }, open(os.path.join(v24_in, "case.json"), "w", encoding="utf-8"))
    import shutil as _sh24
    _sh24.copy(vmerge_xlsx, os.path.join(v24_in, "v24_vmerge.xlsx"))
    v24_cplan = os.path.join(wd, "v24_cplan.json")
    json.dump({
        "case_id": "v24-meta", "stem": "v24_fig", "preset": "nature_double",
        "panels": [
            {"id": "p1", "row": 0, "type": "schematic", "title": "Check Audit", "direction": "LR",
             "nodes": [
                 {"id": "A", "label": "Alpha", "rank": 0, "source": {"file": "p.pdf", "locator": "p.1"}},
                 {"id": "B", "label": "Beta", "rank": 1, "source": {"file": "p.pdf", "locator": "p.1"}},
             ],
             "edges": [
                 {"from": "A", "to": "B", "kind": "activates", "source": {"file": "p.pdf", "locator": "p.1"}},
                 {"from": "A", "to": "B", "kind": "inhibits", "source": {"file": "p.pdf", "locator": "p.1"}},
             ],
             "groups": [{"id": "g1", "label": "Zone", "members": ["A", "GHOST"]}]},
            {"id": "p2", "row": 1, "type": "chart", "title": "Signal", "height_mm": 48,
             "chart": {"kind": "bar", "data_file": "v24_vmerge.xlsx", "sheet_name": "Fig3",
                       "x_col": "Group", "y_cols": ["Signal"], "agg": "mean_sd", "legend": False, "unit": "AU"}},
        ]
    }, open(v24_cplan, "w", encoding="utf-8"))
    v24_cout = os.path.join(wd, "v24_c_out")
    r24p = run([os.path.join(HERE, "run_pipeline.py"), "prepare", "--input", v24_in, "--work", wd, "--out", v24_cout])
    r24cd = run([os.path.join(HERE, "run_pipeline.py"), "deliver", v24_cplan, "--input", v24_in, "--work", wd, "--out", v24_cout])
    res24_c = json.load(open(os.path.join(v24_cout, "result.json"), encoding="utf-8")) if os.path.exists(os.path.join(v24_cout, "result.json")) else {}
    lm24 = (res24_c.get("legend_mapping") or {}).get("p2", {}).get("entries", [{}])[0]
    warns24 = (res24_c.get("checks") or {}).get("geometry_audit", {}).get("warnings", [])
    check("v24: hex legend_mapping + provenance_summary + source_manifest + contract aliases + opposing/dangling audit",
          r24p.returncode == 0 and r24cd.returncode == 0
          and not res24_c.get("missing_fields")
          and bool(lm24.get("color")) and isinstance(lm24.get("category_colors"), dict)
          and (res24_c.get("provenance_summary") or {}).get("charts_sha256_verified") == "1/1"
          and len(res24_c.get("source_manifest") or []) >= 1
          and any("opposing edges" in w for w in warns24)
          and any("unknown node(s)" in w for w in warns24),
          "mf=%s lm=%s warns=%s" % (res24_c.get("missing_fields"), lm24, warns24))

    # 34) v25: external SVG custom <marker> clone-recolor sync + multi-node <g> op_move moves box+text together
    ext_mk_svg = os.path.join(wd, "v25_ext_marker.svg")
    open(ext_mk_svg, "w", encoding="utf-8").write(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 340 120" width="340" height="120">\n'
        '  <defs><marker id="Arrow1Mend" markerWidth="8" markerHeight="6" refX="7" refY="3" orient="auto">'
        '<path d="M0,0 L8,3 L0,6 z" fill="#1E3A5F"/></marker></defs>\n'
        '  <g transform="translate(10,10)">\n'
        '    <rect x="10" y="30" width="75" height="36" fill="#EAF2FB" stroke="#1E3A5F"/>\n'
        '    <text x="47" y="52" text-anchor="middle" font-size="12">SrcA</text>\n'
        '    <rect x="140" y="30" width="75" height="36" fill="#EAF2FB" stroke="#1E3A5F"/>\n'
        '    <text x="177" y="52" text-anchor="middle" font-size="12">MidB</text>\n'
        '    <rect x="245" y="30" width="75" height="36" fill="#D5F5E3" stroke="#1E3A5F"/>\n'
        '    <text x="282" y="52" text-anchor="middle" font-size="12">DstC</text>\n'
        '    <line x1="85" y1="48" x2="140" y2="48" stroke="#1E3A5F" stroke-width="2" marker-end="url(#Arrow1Mend)"/>\n'
        '    <line x1="215" y1="48" x2="245" y2="48" stroke="#1E3A5F" stroke-width="2" marker-end="url(#Arrow1Mend)"/>\n'
        '  </g>\n'
        '</svg>\n'
    )
    v25_ops = os.path.join(wd, "v25_ops.json")
    json.dump({"ops": [
        {"op": "set_attr", "from_text": "SrcA", "to_text": "MidB", "attr": "stroke", "value": "#C0392B"},
        {"op": "move", "by_text": "DstC", "dx": 20, "dy": 15},
    ]}, open(v25_ops, "w", encoding="utf-8"))
    r25e = run([os.path.join(HERE, "edit_svg.py"), ext_mk_svg, v25_ops, "--out-dir", wd, "--stem", "v25_ed", "--no-render"])
    s25 = open(os.path.join(wd, "v25_ed.svg"), encoding="utf-8").read() if os.path.exists(os.path.join(wd, "v25_ed.svg")) else ""
    check("v25: external <marker> clone-recolor preserves original + op_move moves box & text together",
          r25e.returncode == 0
          and 'id="Arrow1Mend"' in s25
          and 'id="Arrow1Mend-C0392B"' in s25
          and "url(#Arrow1Mend-C0392B)" in s25
          and s25.count("translate(20.000,15.000)") == 2,
          s25[:300])

    # 35) v25: LLM schema forgiveness (vertical/subject/object/relation/entity/group-by-label/type=barh) + symlog x_scale w/ 0
    v25_spec = os.path.join(wd, "v25_forgive.json")
    json.dump({
        "preset": "nature_double",
        "panels": [
            {"id": "p1", "row": 0, "type": "schematic", "direction": "vertical", "title": "Schema Forgiveness",
             "nodes": [
                 {"entity": "Receptor Alpha", "shape": "complex", "rank": 0, "source": {"file": "p.pdf", "locator": "p.1"}},
                 {"id": "K1", "label": "Kinase Beta", "shape": "round", "rank": 1, "source": {"file": "p.pdf", "locator": "p.1"}},
             ],
             "edges": [{"subject": "Receptor Alpha", "object": "Kinase Beta", "relation": "phosphorylates", "source": {"file": "p.pdf", "locator": "p.1"}}],
             "groups": [{"id": "g1", "label": "Membrane Zone", "members": ["Receptor Alpha", "Kinase Beta"]}]},
            {"id": "p2", "row": 1, "width_weight": 1.0, "type": "barh", "title": "Long Pathway Barh", "height_mm": 50,
             "chart": {"categories": ["Negative Regulation of Intrinsic Apoptotic Signaling", "Interferon Gamma Response"],
                       "series": [{"name": "NES", "values": [-2.35, 2.74], "errors": [0.15, 0.12],
                                   "points": [[-2.2, -2.5, -2.35], [2.62, 2.86, 2.74]]}],
                       "color_by_sign": True, "show_points": True, "show_values": True, "legend": False, "unit": "NES"}},
            {"id": "p3", "row": 1, "width_weight": 1.0, "type": "line", "title": "Zero-Dose Log Curve", "height_mm": 50,
             "chart": {"categories": ["0", "1", "10", "100"], "x_scale": "log",
                       "series": [{"name": "Drug", "values": [1.0, 0.72, 0.31, 0.08], "errors": [0.05, 0.04, 0.03, 0.01]}],
                       "y_label": "Viability", "x_label": "Dose (nM)", "unit": "rel"}},
        ]
    }, open(v25_spec, "w", encoding="utf-8"))
    v25_g, v25_a = os.path.join(wd, "v25_g.json"), os.path.join(wd, "v25_a.json")
    r25b = run([os.path.join(HERE, "build_figure.py"), v25_spec, "--out-dir", wd, "--stem", "v25f", "--geom", v25_g])
    r25a = run([os.path.join(HERE, "audit_figure.py"), v25_g, "--spec", v25_spec, "--out", v25_a])
    aud25 = json.load(open(v25_a, encoding="utf-8")) if os.path.exists(v25_a) else {}
    check("v25: LLM schema forgiveness + long-label wrapped barh w/ points + zero-dose log x_scale safe",
          r25b.returncode == 0 and r25a.returncode == 0 and aud25.get("n_errors") == 0,
          (r25b.stderr or "") + str(aud25.get("errors")))

    # 36) v25: CJK _auto_probes fallback when figure has only Chinese labels
    cjk_probe = _RP._auto_probes({"panels": [{"id": "p1", "nodes": [{"id": "n1", "label": "肿瘤微环境"}, {"id": "n2", "label": "巨噬细胞"}]}]})
    check("v25: CJK _auto_probes fallback selects Chinese labels when no ASCII labels exist",
          "肿瘤微环境" in cjk_probe and "巨噬细胞" in cjk_probe,
          repr(cjk_probe))

    ok = all(c for _, c, _ in results)
    print("== self_test %s ==" % ("PASS" if ok else "FAIL"))
    for name, cond, detail in results:
        print("  [%s] %s%s" % ("ok" if cond else "FAIL", name,
                               ("" if cond else "  :: " + detail[:160])))
    print("workdir:", wd)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
