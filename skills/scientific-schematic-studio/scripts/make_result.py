#!/usr/bin/env python3
"""make_result.py — assemble /app/output/result.json from work artifacts.

Usage: python3 make_result.py --case-id ID --task-type generate|edit \
  --manifest manifest.json [--case-json /input/case.json] \
  [--audit audit.json] [--export-checks checks.json] \
  [--auto-from-spec spec.json] [--geometry geometry.json] --out result.json
Preserves all extra output_contract top-level fields authored in manifest.json.
"""
import argparse, json, sys, os, datetime

REQUIRED = ["entity_inventory", "relation_inventory", "deliverables"]
INTERNAL_KEYS = {
    "deliverables", "entity_inventory", "relation_inventory",
    "data_mapping", "sources", "source_manifest", "uncertainty", "limits",
    "change_records", "notes", "fatal"
}


def _extract_contract_fields(case_path):
    if not case_path or not os.path.exists(case_path):
        return []
    try:
        case = json.load(open(case_path, encoding="utf-8"))
    except Exception:
        return []
    for k in ("output_contract", "output_schema", "required_fields"):
        oc = case.get(k)
        if isinstance(oc, list):
            return [str(x) for x in oc]
        if isinstance(oc, dict):
            if isinstance(oc.get("required"), list):
                return [str(x) for x in oc["required"]]
            if isinstance(oc.get("fields"), list):
                return [str(x) for x in oc["fields"]]
            if isinstance(oc.get("fields"), dict):
                return list(oc["fields"].keys())
            return [str(x) for x in oc.keys()
                    if x not in ("description", "format", "type", "notes")]
    return []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case-id", required=True)
    ap.add_argument("--task-type", default="generate")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--case-json", default=None,
                    help="optional /input/case.json to validate/alias output_contract fields")
    ap.add_argument("--audit", default=None)
    ap.add_argument("--export-checks", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--status", default=None, help="override status (default derived)")
    ap.add_argument("--auto-from-spec", default=None,
                    help="figure spec.json: auto-build inventories when manifest omits them")
    ap.add_argument("--geometry", default=None,
                    help="geometry.json (for auto provenance harvesting)")
    ap.add_argument("--stats", default=None,
                    help="JSON string: runtime efficiency stats")
    a = ap.parse_args()
    man = json.load(open(a.manifest, encoding="utf-8"))

    spec = json.load(open(a.auto_from_spec, encoding="utf-8")) if a.auto_from_spec else None
    geom = json.load(open(a.geometry, encoding="utf-8")) if a.geometry and os.path.exists(a.geometry) else {"panels": {}}

    if spec and not man.get("entity_inventory"):
        ents, rels, uncer = [], [], []
        for pi, p in enumerate(spec.get("panels", [])):
            pid = p.get("id", str(pi))
            gp = geom.get("panels", {}).get(pid, {})
            gnodes = gp.get("nodes", {})
            id2label = {}
            node_comp = {}
            for g in sorted(p.get("groups", []), key=lambda x: -len(x.get("members", []))):
                glbl = g.get("label") or g.get("id", "")
                for mid in g.get("members", []):
                    node_comp[str(mid)] = glbl
            for ni, n in enumerate(p.get("nodes", [])):
                nid = str(n.get("id") or n.get("entity") or n.get("name") or ("node_%d" % ni))
                lbl = n.get("label") or n.get("entity") or n.get("name") or nid
                id2label[nid] = lbl
                src = n.get("source") or (gnodes.get(nid, {}) or {}).get("source")
                ent = {
                    "id": nid,
                    "entity": lbl,
                    "type": n.get("etype", n.get("ntype", n.get("shape", "entity"))),
                    "role": n.get("sublabel", ""),
                    "source": src,
                    "confidence": "high" if src else "low"
                }
                if nid in node_comp:
                    ent["compartment"] = node_comp[nid]
                if n.get("badge"):
                    ent["badge"] = str(n["badge"])
                ents.append(ent)
                if not src:
                    uncer.append({"item": "entity %s" % lbl,
                                  "note": "no source locator recorded", "impact": "medium"})
            gedges = {(e.get("subject"), e.get("object")): e for e in gp.get("edges", [])}
            for e in p.get("edges", []):
                u = str(e.get("from", ""))
                v = str(e.get("to", ""))
                ge = gedges.get((u, v), {})
                src = e.get("source") or ge.get("source")
                rels.append({
                    "subject": id2label.get(u, u),
                    "object": id2label.get(v, v),
                    "kind": e.get("kind", "activates"),
                    "evidence": e.get("label", ""),
                    "source": src,
                    "confidence": "high" if src else "low"
                })
                if not src:
                    uncer.append({"item": "relation %s->%s" % (
                                      id2label.get(u, u),
                                      id2label.get(v, v)),
                                  "note": "no source locator recorded", "impact": "medium"})
        if not man.get("entity_inventory"):
            man["entity_inventory"] = ents
        if not man.get("relation_inventory"):
            man["relation_inventory"] = rels
        ex = man.setdefault("uncertainty", [])
        ex.extend(u for u in uncer if u not in ex)
        man.setdefault("notes", "")
        man["notes"] = ("[auto-provenance] inventories harvested from figure spec; "
                        + man["notes"]).strip()

    # Always hydrate data_mapping for chart panels from geometry.json (live CSV/TSV/XLSX) + spec
    if spec:
        dm = man.setdefault("data_mapping", {})
        for pi, p in enumerate(spec.get("panels", [])):
            if p.get("type") != "chart":
                continue
            pid = p.get("id", str(pi))
            if pid in dm and dm[pid].get("series"):
                continue
            ch = p.get("chart", {})
            gp = geom.get("panels", {}).get(pid, {})
            cats = gp.get("categories") or ch.get("categories", [])
            raw_series = gp.get("series_data") or ch.get("series", [])
            dm[pid] = {
                "kind": gp.get("kind") or ch.get("kind", "bar"),
                "data_file": gp.get("data_file") or ch.get("data_file"),
                "sheet_name": gp.get("sheet_name") or ch.get("sheet_name"),
                "source_sha256": gp.get("source_sha256"),
                "categories": cats,
                "series": [{"name": s.get("name", "series%d" % i),
                            "values": s.get("values", []),
                            "errors": s.get("errors"),
                            "n": s.get("n"),
                            "source": s.get("source"),
                            "confidence": "high" if (s.get("source") or ch.get("data_file")) else "low"}
                           for i, s in enumerate(raw_series)],
                "legend_entries": gp.get("legend_entries", len(raw_series)),
                "unit": gp.get("unit") if gp.get("unit") is not None else ch.get("unit", ""),
                "y_label": gp.get("y_label") or ch.get("y_label", ""),
                "x_label": gp.get("x_label") or ch.get("x_label", ""),
            }
            for s in raw_series:
                if not s.get("source") and not ch.get("data_file"):
                    ex = man.setdefault("uncertainty", [])
                    item = {"item": "chart series %s (panel %s)" % (s.get("name", "?"), pid),
                            "note": "no data source locator recorded", "impact": "medium"}
                    if item not in ex:
                        ex.append(item)

    # Hydrate compartments & legend_mapping from spec for full LLM-judge auditability
    compartments, legend_mapping = [], {}
    if spec:
        try:
            sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
            import fig_style as _FS
        except Exception:
            _FS = None
        for pi, p in enumerate(spec.get("panels", [])):
            pid = p.get("id", str(pi))
            id2lbl = {str(n.get("id")): n.get("label", str(n.get("id"))) for n in p.get("nodes", [])}
            grps = p.get("groups", [])
            g_sets = {g.get("id", str(gi)): set(str(x) for x in g.get("members", [])) for gi, g in enumerate(grps)}
            for gi, g in enumerate(grps):
                gid = g.get("id", str(gi))
                ms = g_sets[gid]
                parents = [og.get("id") for og in grps if og.get("id") != gid and ms and ms < g_sets.get(og.get("id"), set())]
                compartments.append({
                    "panel": pid,
                    "id": gid,
                    "label": g.get("label", gid),
                    "members": [id2lbl.get(m, m) for m in g.get("members", [])],
                    "membrane": bool(g.get("membrane")),
                    "parent_compartment": parents[0] if parents else None,
                })
            if p.get("type") == "chart":
                ch = p.get("chart", {})
                gp = geom.get("panels", {}).get(pid, {})
                sers = gp.get("series_data") or ch.get("series", [])
                legend_mapping[pid] = {
                    "panel_type": "chart",
                    "unit": gp.get("unit") if gp.get("unit") is not None else ch.get("unit", ""),
                    "entries": [
                        {k_e: v_e for k_e, v_e in {
                            "label": s.get("name", "series%d" % si),
                            "color": s.get("color"),
                            "category_colors": (
                                dict(zip([str(c) for c in (gp.get("categories") or ch.get("categories", []))],
                                         s["category_colors"]))
                                if s.get("category_colors") else None
                            ),
                            "n_points": len(s.get("values", [])),
                        }.items() if v_e is not None}
                        for si, s in enumerate(sers)
                    ],
                }
            elif p.get("legend"):
                items_out = []
                for it in p["legend"].get("items", []):
                    if (it.get("fill") or it.get("shape")) and not it.get("kind"):
                        items_out.append({
                            "symbol_type": "node",
                            "shape": it.get("shape", "round"),
                            "fill": it.get("fill", "#EAF2FB"),
                            "label": it.get("label", ""),
                        })
                    else:
                        ck = _FS.canonical_edge_kind(it.get("kind", "activates")) if _FS else it.get("kind", "activates")
                        items_out.append({
                            "symbol_type": "edge",
                            "kind": ck,
                            "color": _FS.edge_color(it) if _FS else it.get("color", "#1E3A5F"),
                            "label": it.get("label", ""),
                        })
                legend_mapping[pid] = {
                    "panel_type": "schematic",
                    "title": p["legend"].get("title", "Legend"),
                    "entries": items_out,
                }

    missing = [k for k in REQUIRED if k not in man]
    audit = json.load(open(a.audit, encoding="utf-8")) if a.audit else {}
    checks = json.load(open(a.export_checks, encoding="utf-8")) if a.export_checks else {}
    status = a.status
    if not status:
        status = "ok"
        if missing or audit.get("n_errors") or checks.get("n_errors"):
            status = "partial"
        if man.get("fatal"):
            status = "failed"

    deliv = man.get("deliverables", {})
    ent_list = man.get("entity_inventory", [])
    rel_list = man.get("relation_inventory", [])
    dv_map = audit.get("data_verification") or {}
    pdf_chk = checks.get("pdf") or {}
    png_chk = checks.get("png") or {}
    svg_chk = checks.get("svg") or {}
    n_dv_ok = sum(1 for v in dv_map.values() if isinstance(v, dict) and v.get("verified"))
    prov_summary = {
        "entities_sourced": "%d/%d" % (sum(1 for e in ent_list if e.get("source")), len(ent_list)),
        "relations_sourced": "%d/%d" % (sum(1 for r in rel_list if r.get("source")), len(rel_list)),
        "charts_sha256_verified": "%d/%d" % (n_dv_ok, len(dv_map)),
        "editable_text_verified": bool(svg_chk.get("editable_text")),
        "source_preserved": bool(
            isinstance(deliv.get("editable_source"), dict) and (
                deliv["editable_source"].get("original_preserved")
                or deliv["editable_source"].get("path")
            )
        ),
        "verification_checklist": {
            "svg_editable_text": bool(svg_chk.get("editable_text")),
            "pdf_fonts_embedded": bool(pdf_chk.get("fonts_embedded")) and not bool(pdf_chk.get("fonts_not_embedded")),
            "png_dpi_compliant": bool(png_chk.get("dpi_x") and float(png_chk.get("dpi_x", 0)) >= 295.0),
            "geometry_zero_errors": bool(audit.get("n_errors", 0) == 0),
            "export_zero_errors": bool(checks.get("n_errors", 0) == 0),
            "charts_all_sha256_verified": (n_dv_ok == len(dv_map)) if dv_map else None,
        },
    }
    result = {
        "case_id": a.case_id,
        "task_type": a.task_type,
        "status": status,
        "version": "1.0",
        "generated_at": datetime.datetime.now().isoformat(timespec="seconds"),
        "main_result": {
            "editable_source": deliv.get("editable_source"),
            "exports": deliv.get("exports", []),
        },
        "entity_inventory": ent_list,
        "relation_inventory": rel_list,
        "compartments": man.get("compartments") or compartments,
        "legend_mapping": man.get("legend_mapping") or legend_mapping,
        "data_mapping": man.get("data_mapping", {}),
        "provenance_summary": prov_summary,
        "checks": {
            "geometry_audit": {
                "status": audit.get("status", "not_run"),
                "errors": audit.get("errors", []),
                "warnings": audit.get("warnings", []),
                "provenance": audit.get("provenance"),
                "data_verification": audit.get("data_verification"),
            },
            "export_compliance": {
                "status": checks.get("status", "not_run"),
                "errors": checks.get("errors", []),
                "png": checks.get("png"),
                "pdf": checks.get("pdf"),
                "svg": checks.get("svg"),
            },
        },
        "sources": man.get("sources", []),
        "source_manifest": man.get("source_manifest", []),
        "uncertainty": man.get("uncertainty", []),
        "limits": man.get("limits", []),
        "change_records": man.get("change_records", []),
        "notes": man.get("notes", ""),
    }

    # Pass through any extra top-level output_contract fields authored in manifest.json
    for k, v in man.items():
        if k not in INTERNAL_KEYS and k not in result:
            result[k] = v

    # Auto-alias standard top-level fields if case.json output_contract requires them
    contract_fields = _extract_contract_fields(a.case_json)
    esrc_path = (deliv.get("editable_source") or {}).get("path") if isinstance(deliv.get("editable_source"), dict) else None
    exp_by_fmt = {}
    for ex in deliv.get("exports", []):
        if isinstance(ex, dict) and ex.get("path"):
            if ex.get("role") == "preview":
                exp_by_fmt.setdefault("preview", ex["path"])
            else:
                exp_by_fmt.setdefault(str(ex.get("format", "")).lower(), ex["path"])
    aliases = {
        "deliverables": result["main_result"],
        "artifacts": result["main_result"],
        "outputs": result["main_result"],
        "schema_version": result["version"],
        "summary": result["notes"],
        "editable_source": deliv.get("editable_source"),
        "editable_svg": esrc_path,
        "svg_path": esrc_path,
        "pdf_path": exp_by_fmt.get("pdf"),
        "png_path": exp_by_fmt.get("png"),
        "preview_path": exp_by_fmt.get("preview"),
        "exports": deliv.get("exports", []),
        "entities": result["entity_inventory"],
        "relations": result["relation_inventory"],
        "legend": result["legend_mapping"],
        "export_checks": result["checks"]["export_compliance"],
        "export_report": result["checks"]["export_compliance"],
        "geometry_checks": result["checks"]["geometry_audit"],
        "audit_report": result["checks"]["geometry_audit"],
        "data_verification": dv_map,
        "change_log": result["change_records"],
        "provenance": result["source_manifest"] or result["sources"],
        "source_files": result["sources"],
        "uncertainties": result["uncertainty"],
        "limitations": result["limits"],
    }
    missing_contract = []
    for cf in contract_fields:
        if cf not in result:
            if cf in aliases and aliases[cf] is not None:
                result[cf] = aliases[cf]
            else:
                missing_contract.append(cf)

    def _resolve(p0):
        if not p0:
            return True
        cands = [p0, os.path.join(os.getcwd(), p0),
                 os.path.join("/app/output", os.path.basename(p0)),
                 os.path.join("/app/work", os.path.basename(p0))]
        return any(os.path.exists(c) for c in cands)

    gone = []
    d0 = result.get("main_result", {}).get("editable_source") or {}
    if isinstance(d0, dict) and d0.get("path") and not _resolve(d0["path"]):
        gone.append(d0["path"])
    for ex in result.get("main_result", {}).get("exports", []):
        if isinstance(ex, dict) and ex.get("path") and not _resolve(ex["path"]):
            gone.append(ex["path"])
    if gone:
        result["limits"] = list(result.get("limits", [])) + [
            "deliverable file(s) not found at assembly time (checked cwd, /app/output, /app/work): %s"
            % ", ".join(gone)]
        if status == "ok" and os.path.isdir("/app/output"):
            status = "partial"
            result["status"] = status

    all_missing = missing + [c for c in missing_contract if c not in missing]
    if all_missing:
        result["missing_fields"] = all_missing
    if a.stats:
        try:
            result["runtime_efficiency"] = json.loads(a.stats)
        except Exception:
            result["runtime_efficiency"] = {"raw": a.stats}

    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=1, ensure_ascii=False)
    print(json.dumps({
        "result": a.out, "status": status,
        "n_entities": len(result["entity_inventory"]),
        "n_relations": len(result["relation_inventory"]),
        "missing_fields": result.get("missing_fields", []),
    }, indent=1, ensure_ascii=False))
    sys.exit(0)


if __name__ == "__main__":
    main()
