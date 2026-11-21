#!/usr/bin/env python3
"""result_contract.py — init/validate /app/output/result.json against the output contract.

Fields (exact): case_id, status, editable_source, export_artifact, content_map,
compliance_checks, exceptions.  status in {ok, partial, failed}.
Usage:
  python3 result_contract.py --init CASE_ID result.json
  python3 result_contract.py --check result.json
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

def check_file(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = []
    warnings = []
    for k in REQUIRED:
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
    if not cm:
        problems.append("content_map empty (need element->source provenance)")
    cc = d.get("compliance_checks")
    if isinstance(cc, dict) and not cc.get("geometry"):
        warnings.append("compliance_checks.geometry empty (paste fig.checks.json)")
    if not isinstance(d.get("exceptions"), list):
        problems.append("exceptions must be a list")
    if st == "ok" and isinstance(d.get("exceptions"), list) and d["exceptions"]:
        warnings.append("status=ok with exceptions: ensure they describe interpretation caveats, not missing deliverables")
    return {"valid": not problems, "problems": problems, "warnings": warnings,
            "fields_present": [k for k in REQUIRED if k in d]}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init", metavar="CASE_ID")
    ap.add_argument("--check", metavar="RESULT_JSON")
    ap.add_argument("path", nargs="?", default="result.json")
    a = ap.parse_args()
    if a.init:
        Path(a.path).write_text(json.dumps(skeleton(a.init), ensure_ascii=False, indent=1),
                                encoding="utf-8")
        print(f"initialized {a.path} for case {a.init}; fill all fields before finishing")
        return
    r = check_file(a.check or a.path)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    sys.exit(0 if r["valid"] else 1)

if __name__ == "__main__":
    main()
