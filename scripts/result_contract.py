#!/usr/bin/env python3
"""result_contract.py — init/patch/validate /app/output/result.json against the output contract.

Fields (exact): case_id, status, editable_source, export_artifact, content_map,
compliance_checks, exceptions.  status in {ok, partial, failed}.
Usage:
  python3 result_contract.py --init CASE_ID /app/output/result.json
  python3 result_contract.py --patch /app/output/result.json --set-visual "Verified ..." [--set-status ok]
  python3 result_contract.py --check /app/output/result.json
"""
from __future__ import annotations
import sys, json, argparse
from pathlib import Path

REQUIRED = ["case_id", "status", "editable_source", "export_artifact", "content_map",
            "compliance_checks", "exceptions"]

def skeleton(case_id):
    return {"case_id": case_id, "status": "partial",
            "editable_source": None,
            "export_artifact": [],
            "content_map": [],
            "compliance_checks": {"geometry": None, "legend_consistency": None,
                                  "export_checks": [], "visual_inspection": None},
            "exceptions": []}

def check_file(path, case_json=None):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = []
    warnings = []
    req = list(REQUIRED)
    if case_json and Path(case_json).exists():
        try:
            cd = json.loads(Path(case_json).read_text(encoding="utf-8"))
            for k in (cd.get("output_contract") or []):
                if k not in req:
                    req.append(k)
            if cd.get("case_id") and str(d.get("case_id") or "") != str(cd["case_id"]):
                problems.append(f"case_id mismatch: got {d.get('case_id')!r}, expected {cd['case_id']!r}")
        except Exception:
            pass
    for k in req:
        if k not in d:
            problems.append(f"missing field: {k}")
    st = d.get("status")
    if st not in ("ok", "partial", "failed"):
        problems.append(f"status must be ok|partial|failed, got {st!r}")
    if not str(d.get("case_id") or "").strip():
        problems.append("case_id empty")
    es = d.get("editable_source")
    if es:
        p = es["path"] if isinstance(es, dict) else es
        if not Path(p).exists():
            problems.append(f"editable_source path not found: {p}")
        elif isinstance(es, dict) and str(es.get("format", "")).lower() not in ("svg", "drawio", "svg source"):
            warnings.append(f"editable_source format is {es.get('format')!r}; SVG expected for editability")
    else:
        problems.append("editable_source missing")
    arts = d.get("export_artifact") or []
    fmts = set()
    for a in arts:
        p = a["path"] if isinstance(a, dict) else a
        if p and not Path(p).exists():
            problems.append(f"export artifact not found: {p}")
            continue
        if not isinstance(a, dict) or not a.get("format"):
            continue
        fmt = str(a["format"]).lower()
        fmts.add(fmt)
        sig = Path(p).read_bytes()[:600]
        if fmt == "png" and not sig.startswith(b"\x89PNG"):
            problems.append(f"{p} is not a valid PNG (bad signature)")
        if fmt == "pdf" and not sig.startswith(b"%PDF"):
            problems.append(f"{p} is not a valid PDF (bad signature)")
        if fmt == "svg" and b"<svg" not in sig:
            problems.append(f"{p} is not a valid SVG")
    if arts and "png" not in fmts:
        warnings.append("no PNG export listed (raster preview expected for inspection)")
    cm = d.get("content_map") or []
    for i, e in enumerate(cm):
        if isinstance(e, dict) and not str(e.get("source") or "").strip():
            problems.append(f"content_map[{i}] ({e.get('element')}) has empty source")
        elif isinstance(e, dict) and "unspecified — fill" in str(e.get("source") or ""):
            warnings.append(f"content_map[{i}] ({e.get('element')}) has placeholder source")
    if not cm:
        problems.append("content_map empty (need element->source provenance)")
    cc = d.get("compliance_checks")
    if isinstance(cc, dict):
        if not cc.get("geometry"):
            warnings.append("compliance_checks.geometry empty (paste fig.checks.json)")
        vi = str(cc.get("visual_inspection") or "")
        if not vi.strip() or "inspect the png" in vi.lower() or "pending:" in vi.lower() or "todo" in vi.lower():
            warnings.append("compliance_checks.visual_inspection missing or still placeholder")
    if not isinstance(d.get("exceptions"), list):
        problems.append("exceptions must be a list")
    if st == "ok" and isinstance(d.get("exceptions"), list) and d["exceptions"]:
        if any(any(tok in json.dumps(e, ensure_ascii=False).lower()
                   for tok in ("missing", "corrupt", "unavailable", "status=partial", "status=failed"))
               for e in d["exceptions"]):
            warnings.append("status=ok with exceptions referencing missing/failed deliverables: verify status")
    return {"valid": not problems, "problems": problems, "warnings": warnings,
            "fields_present": [k for k in REQUIRED if k in d]}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", metavar="CASE_ID")
    ap.add_argument("--patch", metavar="RESULT_JSON")
    ap.add_argument("--set-visual", default=None)
    ap.add_argument("--set-status", default=None)
    ap.add_argument("--add-exception", action="append", default=[])
    ap.add_argument("--check", metavar="RESULT_JSON")
    ap.add_argument("--case-json", default=None)
    ap.add_argument("path", nargs="?", default="result.json")
    a = ap.parse_args()
    if a.init:
        Path(a.path).write_text(json.dumps(skeleton(a.init), ensure_ascii=False, indent=1),
                                encoding="utf-8")
        print(f"initialized {a.path} for case {a.init}; fill all fields before finishing")
        return
    if a.patch:
        p = Path(a.patch)
        d = json.loads(p.read_text(encoding="utf-8"))
        if a.set_visual is not None:
            d.setdefault("compliance_checks", {})["visual_inspection"] = a.set_visual
        if a.set_status in ("ok", "partial", "failed"):
            d["status"] = a.set_status
        for raw_ex in a.add_exception:
            ex = json.loads(raw_ex) if raw_ex.strip().startswith("{") else {"issue": raw_ex, "handling": "noted"}
            d.setdefault("exceptions", []).append(ex)
        p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
        r = check_file(p, case_json=a.case_json)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        sys.exit(0 if r["valid"] else 1)
    r = check_file(a.check or a.path, case_json=a.case_json)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    sys.exit(0 if r["valid"] else 1)

if __name__ == "__main__":
    main()
