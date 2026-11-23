"""Data-driven chart panel (bar/barh/stacked_bar/line/scatter) with CSV/TSV/XLSX loading."""
import csv
import hashlib
import math
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fig_style as S


_PM_RE = re.compile(
    r"^\s*([-+]?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*(?:±|\+/-|\+-)\s*"
    r"([-+]?\d+(?:,\d{3})*(?:\.\d+)?(?:[eE][-+]?\d+)?)\s*%?\s*$"
)


def _parse_val_err(raw):
    """Parse numeric cell or 'mean ± SD' / 'mean +/- SD' string into (val, err_or_None)."""
    if raw is None:
        return float("nan"), None
    if isinstance(raw, (int, float)):
        return float(raw), None
    s = str(raw).strip()
    if not s or s.lower() in ("na", "n/a", "nan", "nd", "n.d.", "none", "-", "—", "–", "−"):
        return float("nan"), None
    # Normalize Unicode minus (−) and en-dash (–) used as negative sign in Nature/Cell tables
    s_norm = re.sub(r"[−–](?=\s*\d|\.)", "-", s)
    m = _PM_RE.match(s_norm)
    if m:
        return float(m.group(1).replace(",", "")), abs(float(m.group(2).replace(",", "")))
    s2 = s_norm.replace(",", "")
    if s2.endswith("%"):
        s2 = s2[:-1].strip()
    try:
        return float(s2), None
    except ValueError:
        return float("nan"), None


def _parse_float(raw):
    """Forgiving numeric parser for real-world Source Data cells (supports %, commas, mean ± SD)."""
    return _parse_val_err(raw)[0]


def _xlsx_sheet_entries(zf):
    names = set(zf.namelist())
    rels = {}
    if "xl/_rels/workbook.xml.rels" in names:
        try:
            rroot = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
            for rel in rroot:
                rid = rel.get("Id")
                tgt = rel.get("Target", "").lstrip("/")
                if rid and tgt:
                    if not tgt.startswith("xl/"):
                        tgt = "xl/" + tgt
                    rels[rid] = tgt
        except Exception:
            pass
    entries = []
    if "xl/workbook.xml" in names:
        try:
            wroot = ET.fromstring(zf.read("xl/workbook.xml"))
            for sh in wroot.iter():
                if sh.tag.endswith("}sheet"):
                    sname = sh.get("name", "Sheet")
                    rid = next((v for k, v in sh.attrib.items()
                                if k.endswith("}id") or k == "id"), None)
                    tgt = rels.get(rid)
                    if tgt and tgt in names:
                        entries.append((sname, tgt))
        except Exception:
            pass
    if not entries:
        for i, m in enumerate(sorted(n for n in names
                                     if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))):
            entries.append(("Sheet%d" % (i + 1), m))
    return entries


def _col_ref_to_idx(ref):
    """Convert Excel cell ref like 'C5' or 'AA12' to 0-based column index."""
    if not ref:
        return None
    m = re.match(r"^\s*([A-Za-z]+)", str(ref))
    if not m:
        return None
    idx = 0
    for ch in m.group(1).upper():
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def _parse_col_range(cr):
    """Parse col_range like 'A:D', 'F:J', or [0, 3] into (c0, c1_inclusive)."""
    if not cr:
        return None
    if isinstance(cr, (list, tuple)) and len(cr) == 2:
        return int(cr[0]), int(cr[1])
    m = re.match(r"^\s*([A-Za-z]+)\s*[:\-]\s*([A-Za-z]+)\s*$", str(cr))
    if m:
        return _col_ref_to_idx(m.group(1)), _col_ref_to_idx(m.group(2))
    return None


def _read_xlsx_rows(path, sheet_idx=0, sheet_name=None):
    """Read rows from an XLSX file using only Python stdlib (coordinate-aware for sparse cells)."""
    with zipfile.ZipFile(path, "r") as zf:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.iter():
                if si.tag.endswith("}si"):
                    parts = [t.text or "" for t in si.iter() if t.tag.endswith("}t")]
                    shared.append("".join(parts))
        entries = _xlsx_sheet_entries(zf)
        if not entries:
            return []
        target_member = None
        if sheet_name:
            low = str(sheet_name).strip().lower()
            for sn, mem in entries:
                if sn.strip().lower() == low:
                    target_member = mem
                    break
            if not target_member:
                for sn, mem in entries:
                    if low in sn.strip().lower():
                        target_member = mem
                        break
        if not target_member:
            target_member = entries[min(max(int(sheet_idx), 0), len(entries) - 1)][1]
        sroot = ET.fromstring(zf.read(target_member))
        h_merges, v_merges = [], []
        for mc in sroot.iter():
            if mc.tag.endswith("}mergeCell") and mc.get("ref") and ":" in mc.get("ref"):
                a_r, b_r = mc.get("ref").split(":", 1)
                ma = re.match(r"^\s*([A-Za-z]+)(\d+)\s*$", a_r)
                mb = re.match(r"^\s*([A-Za-z]+)(\d+)\s*$", b_r)
                if ma and mb:
                    r0, r1 = int(ma.group(2)) - 1, int(mb.group(2)) - 1
                    c0, c1 = _col_ref_to_idx(ma.group(1)), _col_ref_to_idx(mb.group(1))
                    if c0 is not None and c1 is not None:
                        if r0 == r1 and c1 > c0:
                            h_merges.append((r0, c0, c1))
                        elif c0 == c1 and r1 > r0 and c0 <= 2:
                            v_merges.append((c0, r0, r1))
        rows_by_r = {}
        row_order = []
        for row in sroot.iter():
            if not row.tag.endswith("}row"):
                continue
            r_attr = row.get("r")
            r_idx = (int(r_attr) - 1) if (r_attr and r_attr.isdigit()) else len(row_order)
            vals = []
            for c in row:
                if not c.tag.endswith("}c"):
                    continue
                cidx = _col_ref_to_idx(c.get("r"))
                if cidx is None:
                    cidx = len(vals)
                if cidx >= len(vals):
                    vals.extend([""] * (cidx - len(vals) + 1))
                t = c.get("t", "")
                v_el = next((ch for ch in c if ch.tag.endswith("}v")), None)
                is_el = next((ch for ch in c if ch.tag.endswith("}is")), None)
                if t == "s" and v_el is not None and v_el.text is not None:
                    idx = int(v_el.text)
                    val = shared[idx] if 0 <= idx < len(shared) else ""
                elif t == "inlineStr" and is_el is not None:
                    val = "".join(x.text or "" for x in is_el.iter() if x.tag.endswith("}t"))
                elif t == "b" and v_el is not None and v_el.text is not None:
                    val = "TRUE" if v_el.text.strip() == "1" else "FALSE"
                elif v_el is not None and v_el.text is not None:
                    val = v_el.text
                else:
                    val = ""
                vals[cidx] = val
            if any(v != "" for v in vals):
                rows_by_r[r_idx] = vals
                row_order.append(r_idx)
        for r_i, c0, c1 in h_merges:
            rv = rows_by_r.get(r_i)
            if not rv or c0 >= len(rv) or not str(rv[c0]).strip():
                continue
            txt = str(rv[c0]).strip()
            if not math.isnan(_parse_float(txt)):
                continue
            if c1 >= len(rv):
                rv.extend([""] * (c1 - len(rv) + 1))
            for ci in range(c0 + 1, c1 + 1):
                if not str(rv[ci]).strip():
                    rv[ci] = txt
        for c_i, r0, r1 in v_merges:
            rv0 = rows_by_r.get(r0)
            if not rv0 or c_i >= len(rv0) or not str(rv0[c_i]).strip():
                continue
            txt = str(rv0[c_i]).strip()
            if not math.isnan(_parse_float(txt)):
                continue
            for r_cur in range(r0 + 1, r1 + 1):
                rv_cur = rows_by_r.get(r_cur)
                if rv_cur is None:
                    continue
                if c_i >= len(rv_cur):
                    rv_cur.extend([""] * (c_i - len(rv_cur) + 1))
                if not str(rv_cur[c_i]).strip():
                    rv_cur[c_i] = txt
        return [rows_by_r[r_i] for r_i in row_order]


def _clean_cat_str(s):
    """Strip Excel '.0' artifact on integer-like category strings (e.g., '24.0' -> '24')."""
    t = str(s or "").strip()
    if re.match(r"^-?\d+\.0+$", t):
        return t.split(".")[0]
    return t


def effective_legend_loc(ch):
    """Consistent legend placement shared by build_figure (top inset) and draw_chart."""
    if not ch or ch.get("kind") == "heatmap" or ch.get("legend") is False:
        return None
    if ch.get("legend_loc"):
        return str(ch["legend_loc"])
    n_ser = len(ch.get("series") or [])
    if n_ser >= 2:
        return "top"
    return "best"
def _lookup_col(col_idx, name):
    if name in col_idx:
        return col_idx[name]
    low = name.strip().lower()
    for k, i in col_idx.items():
        if k.strip().lower() == low:
            return i
    norm = re.sub(r"[^a-z0-9]+", "", low)
    if norm:
        for k, i in col_idx.items():
            if re.sub(r"[^a-z0-9]+", "", k.lower()) == norm:
                return i
        hits = [i for k, i in col_idx.items() if norm in re.sub(r"[^a-z0-9]+", "", k.lower())]
        if len(hits) == 1:
            return hits[0]
    raise KeyError("column %r not found; available: %s" % (name, list(col_idx.keys())))


def _summarize_group(vs, agg="mean_sd"):
    """Compute (center, err) for a non-empty list of floats."""
    if not vs:
        return float("nan"), 0.0
    mean_v = sum(vs) / len(vs)
    sd_v = math.sqrt(sum((v - mean_v) ** 2 for v in vs) / max(len(vs) - 1, 1)) if len(vs) > 1 else 0.0
    if agg == "median":
        sv = sorted(vs)
        m = len(sv)
        center = sv[m // 2] if m % 2 else 0.5 * (sv[m // 2 - 1] + sv[m // 2])
    else:
        center = mean_v
    err = sd_v / math.sqrt(len(vs)) if agg == "mean_sem" and len(vs) > 1 else sd_v
    return center, err


def load_chart_table(ch, spec_dir=None):
    """Hydrate categories & series from data_file (CSV/TSV/XLSX) when specified."""
    df = ch.get("data_file")
    if not df:
        return ch
    path = df
    if not os.path.isabs(path) and spec_dir:
        cand = os.path.join(spec_dir, path)
        if os.path.exists(cand):
            path = cand
    if not os.path.exists(path):
        raise FileNotFoundError("chart data_file not found: %s" % df)
    src_sha = hashlib.sha256(open(path, "rb").read()).hexdigest()[:12]
    ext = os.path.splitext(path)[1].lower()
    if ext == ".xlsx":
        rows = _read_xlsx_rows(path, int(ch.get("sheet_index", 0)),
                               sheet_name=ch.get("sheet_name"))
    else:
        delim = "\t" if ext == ".tsv" else ch.get("delimiter", ",")
        with open(path, newline="", encoding="utf-8-sig", errors="ignore") as f:
            rows = [r for r in csv.reader(f, delimiter=delim) if any(c.strip() for c in r)]
    skip = int(ch.get("skip_rows", 0))
    rows = rows[skip:]
    # Run stacked sub-table jump BEFORE col_range slicing so a section title in col A isn't erased by col_range="B:D"
    sec_q = ch.get("section_match") or ch.get("table_title")
    if sec_q:
        low_s = str(sec_q).strip().lower()
        for ri, r in enumerate(rows):
            if low_s in " ".join(str(c) for c in r).lower():
                rows = rows[ri + 1:]
                break
    cr = _parse_col_range(ch.get("col_range"))
    if cr:
        c0, c1 = cr
        rows = [r[c0:c1 + 1] for r in rows if len(r) > c0 and any(str(v).strip() for v in r[c0:c1 + 1])]
    if not rows:
        raise ValueError("chart data_file %s has no rows" % df)
    # Auto-detect header row (leading Nature Source Data title/banner rows)
    hdr_i = 0
    want_x = ch.get("x_col")
    want_y = ch.get("y_cols") or []
    scan_lim = min(len(rows), 60)
    if want_x:
        low_x = str(want_x).strip().lower()
        for ri in range(scan_lim):
            if any(c.strip().lower() == low_x for c in rows[ri]):
                hdr_i = ri
                break
    elif want_y:
        low_y0 = str(want_y[0]).strip().lower()
        for ri in range(scan_lim):
            if any(c.strip().lower() == low_y0 for c in rows[ri]):
                hdr_i = ri
                break
    else:
        for ri in range(min(len(rows) - 1, 8)):
            non_empty = [c for c in rows[ri] if c.strip()]
            nxt_non_empty = [c for c in rows[ri + 1] if c.strip()]
            if len(non_empty) <= 1 and len(nxt_non_empty) >= 2:
                hdr_i = ri + 1
            else:
                break
    header, body = rows[hdr_i], rows[hdr_i + 1:]
    # Combine 2-row Nature merged headers when x_col is on row hdr_i and y_cols (group names) are on row hdr_i-1
    if hdr_i > 0 and want_y:
        low_row = {c.strip().lower() for c in rows[hdr_i] if c.strip()}
        low_prev = {c.strip().lower() for c in rows[hdr_i - 1] if c.strip()}
        if (not any(str(y).strip().lower() in low_row for y in want_y)
                and any(str(y).strip().lower() in low_prev for y in want_y)):
            prev_r = list(rows[hdr_i - 1])
            cur_r = list(rows[hdr_i])
            mlen = max(len(prev_r), len(cur_r))
            prev_r.extend([""] * (mlen - len(prev_r)))
            cur_r.extend([""] * (mlen - len(cur_r)))
            header = [prev_r[ci].strip() or cur_r[ci].strip() for ci in range(mlen)]
            body = rows[hdr_i + 1:]
    if ch.get("max_rows"):
        body = body[:int(ch["max_rows"])]
    col_idx = {h.strip(): i for i, h in enumerate(header) if h.strip()}
    col_multi = {}
    for i, h in enumerate(header):
        hs = h.strip()
        if hs:
            col_multi.setdefault(hs, []).append(i)
    # Handle 2-row Nature merged headers where row hdr_i has group names ("WT|WT|WT|KO|KO|KO")
    # and row hdr_i+1 has x_col / sub-headers ("Gene|Rep1|Rep2|Rep3|...")
    if body and any(len(v) >= 2 for v in col_multi.values()):
        sub_row = body[0]
        sub_has_nums = sum(1 for c in sub_row[1:] if not math.isnan(_parse_float(c)))
        if sub_has_nums == 0 and any(str(c).strip() for c in sub_row):
            if not header[0].strip() and sub_row and str(sub_row[0]).strip():
                header = list(header)
                header[0] = str(sub_row[0]).strip()
                col_idx[header[0]] = 0
                col_multi.setdefault(header[0], []).append(0)
            body = body[1:]
    sheet_loc = ("sheet %s, " % ch["sheet_name"]) if ch.get("sheet_name") else ""
    agg = (ch.get("agg") or "").strip().lower()

    # Column-grouped replicates mode: explicit col_groups OR auto-detected repeated/merged replicate headers
    col_groups = ch.get("col_groups")
    if (not col_groups and str(ch.get("orient", "")).lower() != "columns"
            and not ch.get("wide_replicates") and not ch.get("err_cols")):
        cand_ys = list(want_y) if want_y else [k for k in col_multi if k != (want_x or (header[0].strip() if header else ""))]
        # Resolve case-insensitively against col_multi
        multi_map = {}
        for yc in cand_ys:
            if yc in col_multi:
                multi_map[yc] = col_multi[yc]
            else:
                low_y = yc.strip().lower()
                hit_k = next((k for k in col_multi if k.lower() == low_y), None)
                if hit_k:
                    multi_map[yc] = col_multi[hit_k]
        if multi_map and any(len(idxs) >= 2 for idxs in multi_map.values()):
            x_col = want_x or header[0].strip()
            xi = _lookup_col(col_idx, x_col)
            all_yi = [yi for idxs in multi_map.values() for yi in idxs]
            data_rows = []
            for r in body:
                if len(r) <= xi or not r[xi].strip():
                    continue
                if any(not math.isnan(_parse_float(r[yi] if len(r) > yi else None)) for yi in all_yi):
                    data_rows.append(r)
                elif data_rows and ch.get("stop_on_subtable", True):
                    break
            cats = [_clean_cat_str(r[xi]) for r in data_rows]
            series = []
            for gn, idxs in multi_map.items():
                vals, errs, pts_list, ns = [], [], [], []
                for r in data_rows:
                    vs = [_parse_float(r[yi] if len(r) > yi else None) for yi in idxs]
                    vs = [v for v in vs if not math.isnan(v)]
                    c_v, e_v = _summarize_group(vs, agg or "mean_sd")
                    vals.append(c_v); errs.append(e_v); pts_list.append(vs); ns.append(len(vs))
                series.append({
                    "name": gn, "values": vals, "errors": errs, "points": pts_list, "n": ns,
                    "source": {"file": os.path.basename(path),
                               "locator": "%sheader %s x%d (%s)" % (sheet_loc, gn, len(idxs), agg or "mean_sd")},
                })
            out = dict(ch)
            out["categories"] = cats
            out["series"] = series
            out["_source_sha256"] = src_sha
            return out

    if isinstance(col_groups, dict) and col_groups:
        x_col = want_x or header[0].strip()
        xi = _lookup_col(col_idx, x_col)
        grp_indices = {str(gn): [_lookup_col(col_idx, c) for c in cols] for gn, cols in col_groups.items()}
        all_yi = [yi for idxs in grp_indices.values() for yi in idxs]
        data_rows = []
        for r in body:
            if len(r) <= xi or not r[xi].strip():
                continue
            if any(not math.isnan(_parse_float(r[yi] if len(r) > yi else None)) for yi in all_yi):
                data_rows.append(r)
            elif data_rows and ch.get("stop_on_subtable", True):
                break
        cats = [_clean_cat_str(r[xi]) for r in data_rows]
        series = []
        for gn, idxs in grp_indices.items():
            vals, errs, pts_list, ns = [], [], [], []
            for r in data_rows:
                vs = [_parse_float(r[yi] if len(r) > yi else None) for yi in idxs]
                vs = [v for v in vs if not math.isnan(v)]
                c_v, e_v = _summarize_group(vs, agg or "mean_sd")
                vals.append(c_v); errs.append(e_v); pts_list.append(vs); ns.append(len(vs))
            series.append({
                "name": gn, "values": vals, "errors": errs, "points": pts_list, "n": ns,
                "source": {"file": os.path.basename(path),
                           "locator": "%scols %s (%s)" % (sheet_loc, ",".join(col_groups[gn][:4]), agg or "mean_sd")},
            })
        out = dict(ch)
        out["categories"] = cats
        out["series"] = series
        out["_source_sha256"] = src_sha
        return out

    # Wide-format replicate columns mode: each y_col is a category/condition, rows are biological replicates
    if str(ch.get("orient", "")).lower() == "columns" or ch.get("wide_replicates"):
        y_cols = list(want_y) if want_y else [h.strip() for h in header if h.strip() and h.strip() != (want_x or "")]
        # Drop leading non-numeric ID column if user omitted y_cols and first col is "Replicate"/"Sample"
        if not want_y and len(y_cols) >= 2:
            c0 = col_idx[y_cols[0]]
            if not any(not math.isnan(_parse_float(r[c0] if len(r) > c0 else None)) for r in body[:6]):
                y_cols = y_cols[1:]
        y_indices = [_lookup_col(col_idx, yc) for yc in y_cols]
        # Stop before any subsequent stacked sub-table header in the same sheet
        data_rows = []
        for r in body:
            has_num = any(not math.isnan(_parse_float(r[yi] if len(r) > yi else None)) for yi in y_indices)
            if has_num:
                data_rows.append(r)
            elif data_rows and ch.get("stop_on_subtable", True):
                break
        vals, errs, pts_list, ns = [], [], [], []
        for yc, yi in zip(y_cols, y_indices):
            vs = [_parse_float(r[yi] if len(r) > yi else None) for r in data_rows]
            vs = [v for v in vs if not math.isnan(v)]
            c_v, e_v = _summarize_group(vs, agg or "mean_sd")
            vals.append(c_v)
            errs.append(e_v)
            pts_list.append(vs)
            ns.append(len(vs))
        out = dict(ch)
        out["categories"] = y_cols
        out["series"] = [{
            "name": ch.get("series_name") or ch.get("y_label") or "Value",
            "values": vals, "errors": errs, "points": pts_list, "n": ns,
            "source": {"file": os.path.basename(path),
                       "locator": "%scols %s (%s)" % (sheet_loc, ",".join(y_cols[:5]), agg or "mean_sd")},
        }]
        out["_source_sha256"] = src_sha
        return out

    x_col = want_x or header[0].strip()
    xi = _lookup_col(col_idx, x_col)
    valid_rows = [r for r in body if len(r) > xi and r[xi].strip() != ""]
    y_cols = want_y or [h.strip() for h in header if h.strip() and h.strip() != x_col]
    err_cols = ch.get("err_cols") or {}
    y_indices = [_lookup_col(col_idx, yc) for yc in y_cols]
    # Keep numeric rows; stop cleanly if a second stacked sub-table header begins in the same sheet
    data_rows = []
    for r in valid_rows:
        if any(not math.isnan(_parse_float(r[yi] if len(r) > yi else None)) for yi in y_indices):
            data_rows.append(r)
        elif data_rows and ch.get("stop_on_subtable", True):
            break
    raw_cats = [_clean_cat_str(r[xi]) for r in data_rows]
    # Auto-group replicate rows when agg is specified or kind=='box' with repeated categories
    do_group = bool(agg in ("mean_sd", "mean_sem", "median")) or (
        ch.get("kind") == "box" and len(set(raw_cats)) < len(raw_cats)
    )
    series = []
    if do_group:
        cats = []
        grp_rows = {}
        for r, c in zip(data_rows, raw_cats):
            if c not in grp_rows:
                cats.append(c)
                grp_rows[c] = []
            grp_rows[c].append(r)
        for yc, yi in zip(y_cols, y_indices):
            vals, errs, pts_list, ns = [], [], [], []
            for c in cats:
                vs = [_parse_float(r[yi] if len(r) > yi else None) for r in grp_rows[c]]
                vs = [v for v in vs if not math.isnan(v)]
                pts_list.append(vs)
                ns.append(len(vs))
                c_v, e_v = _summarize_group(vs, agg or "mean_sd")
                vals.append(c_v)
                errs.append(e_v)
            s = {"name": yc, "values": vals, "errors": errs, "points": pts_list, "n": ns,
                 "source": {"file": os.path.basename(path),
                            "locator": "%scol %s (%s)" % (sheet_loc, yc, agg or "replicates")}}
            series.append(s)
    else:
        cats = raw_cats
        for y_pos, (yc, yi) in enumerate(zip(y_cols, y_indices)):
            pairs = [_parse_val_err(r[yi] if len(r) > yi else None) for r in data_rows]
            vals = [v for v, _ in pairs]
            inline_errs = [e for _, e in pairs]
            s = {"name": yc, "values": vals,
                 "source": {"file": os.path.basename(path), "locator": "%scol %s" % (sheet_loc, yc)}}
            if isinstance(err_cols, dict):
                ec = err_cols.get(yc)
            elif isinstance(err_cols, list) and y_pos < len(err_cols):
                ec = err_cols[y_pos]
            elif isinstance(err_cols, str) and len(y_cols) == 1:
                ec = err_cols
            else:
                ec = None
            if ec:
                try:
                    ei = _lookup_col(col_idx, ec)
                    errs = [_parse_float(r[ei] if len(r) > ei else None) for r in data_rows]
                    s["errors"] = [0.0 if math.isnan(v) else v for v in errs]
                except KeyError:
                    pass
            elif any(e is not None for e in inline_errs):
                s["errors"] = [0.0 if e is None else e for e in inline_errs]
            series.append(s)
    out = dict(ch)
    out["categories"] = cats
    out["series"] = series
    out["_source_sha256"] = src_sha
    if ch.get("kind", "bar") in ("line", "scatter") and ch.get("x_numeric", True) and not ch.get("x_values"):
        num_xs = [_parse_float(c) for c in cats]
        if len(num_xs) == len(cats) and len(num_xs) >= 2 and not any(math.isnan(v) for v in num_xs):
            out["x_values"] = num_xs
            uniq_xs = sorted(set(num_xs))
            span_x = (uniq_xs[-1] - uniq_xs[0]) if len(uniq_xs) >= 2 else 0.0
            min_gap_x = min((uniq_xs[i + 1] - uniq_xs[i] for i in range(len(uniq_xs) - 1)), default=0.0)
            # Only force exact data-point xticks when adjacent ticks won't collide visually
            if len(uniq_xs) <= 10 and span_x > 0 and (min_gap_x / span_x) >= 0.075:
                out["_auto_xticks"] = num_xs
    return out


def draw_chart(ax, panel, colors, spec_dir=None):
    ch = load_chart_table(panel["chart"], spec_dir=spec_dir)
    kind = ch.get("kind", "bar")
    cats = ch.get("categories", [])
    x_vals = ch.get("x_values")
    series = ch.get("series", [])
    xs = [float(v) for v in x_vals] if x_vals else list(range(len(cats)))
    n = len(series)
    bottom = [0.0] * len(xs)
    max_y = None
    min_y = None

    if kind == "heatmap":
        mat = [[_parse_float(v) for v in s.get("values", [])] for s in series]
        row_labels = ch.get("row_labels") or [s.get("name", "row%d" % i) for i, s in enumerate(series)]
        cmap = ch.get("cmap", "viridis")
        im = ax.imshow(mat, aspect="auto", cmap=cmap, interpolation="nearest")
        im.set_gid("heatmap-%s" % panel.get("id", "0"))
        ax.set_xticks(list(range(len(cats))))
        rot = 25 if any(len(str(c)) > 8 for c in cats) else 0
        ax.set_xticklabels(cats, fontsize=7.2, rotation=rot, ha="right" if rot else "center")
        ax.set_yticks(list(range(len(row_labels))))
        ax.set_yticklabels(row_labels, fontsize=7.2)
        ax.set_xlabel(ch.get("x_label", ""), fontsize=8.5)
        ax.set_ylabel(ch.get("y_label", ""), fontsize=8.5)
        flat = [v for row in mat for v in row if not math.isnan(v)]
        vmin = min(flat) if flat else 0.0
        vmax = max(flat) if flat else 1.0
        mid = 0.5 * (vmin + vmax)
        if ch.get("show_values", True) and len(mat) * max(len(cats), 1) <= 64:
            for ri, row in enumerate(mat):
                for ci, val in enumerate(row):
                    if not math.isnan(val):
                        tcol = "#FFFFFF" if val < mid else "#10243B"
                        if "r" in cmap.lower() and "rdbu" in cmap.lower():
                            tcol = "#FFFFFF" if abs(val - mid) > 0.32 * max(vmax - vmin, 1e-6) else "#10243B"
                        ax.text(ci, ri, "%.2g" % val, ha="center", va="center",
                                fontsize=6.5, color=tcol, fontweight="bold")
        cbar = ax.figure.colorbar(im, ax=ax, fraction=0.048, pad=0.03)
        cbar.ax.tick_params(labelsize=6.5)
        if ch.get("unit"):
            cbar.set_label(str(ch["unit"]), fontsize=7.2)
        return {
            "kind": kind,
            "categories": [str(c) for c in cats],
            "n_categories": len(cats),
            "n_series": n,
            "series_names": [str(r) for r in row_labels],
            "series_lengths": [len(s.get("values", [])) for s in series],
            "series_data": [
                {"name": str(row_labels[idx]),
                 "values": [None if math.isnan(_parse_float(v)) else round(_parse_float(v), 6)
                            for v in s.get("values", [])],
                 "source": s.get("source")}
                for idx, s in enumerate(series)
            ],
            "legend_entries": 0,
            "unit": ch.get("unit", ""),
            "x_label": ch.get("x_label", ""),
            "y_label": ch.get("y_label", ""),
            "data_file": ch.get("data_file"),
            "sheet_name": ch.get("sheet_name"),
        }

    series_color_meta = []
    for i, s in enumerate(series):
        color = s.get("color") or colors[i % len(colors)]
        cat_cols_used = None
        vals = [_parse_float(v) for v in s["values"]]
        yerr = [0.0 if math.isnan(_parse_float(v)) else _parse_float(v)
                for v in s["errors"]] if s.get("errors") else None
        pts_groups = s.get("points")
        finite_hi = [v + (yerr[k] if yerr else 0.0) for k, v in enumerate(vals) if not math.isnan(v)]
        finite_lo = [v - (yerr[k] if yerr else 0.0) for k, v in enumerate(vals) if not math.isnan(v)]
        if pts_groups:
            for grp in pts_groups:
                for pv in (grp or []):
                    fv = _parse_float(pv)
                    if not math.isnan(fv):
                        finite_hi.append(fv)
                        finite_lo.append(fv)
        if finite_hi:
            hi, lo = max(finite_hi), min(finite_lo)
            max_y = hi if max_y is None else max(max_y, hi)
            min_y = lo if min_y is None else min(min_y, lo)

        if kind == "bar":
            bw = 0.78 / max(n, 1)
            off = (i - (n - 1) / 2.0) * bw
            kw = {}
            if yerr:
                kw.update(yerr=yerr, capsize=2.4, ecolor="#333333",
                          error_kw=dict(lw=0.9))
            bar_xs = [x + off for x in xs]
            if ch.get("bar_colors"):
                b_cols = [ch["bar_colors"][j % len(ch["bar_colors"])] for j in range(len(vals))]
                cat_cols_used = b_cols
            elif n == 1 and not s.get("color") and ch.get("color_by_category", ch.get("legend") is False) and 2 <= len(vals) <= 7:
                cat_pal = ["#8C9BA5", "#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"]
                b_cols = [cat_pal[j % len(cat_pal)] for j in range(len(vals))]
                cat_cols_used = b_cols
            else:
                b_cols = color
            bars = ax.bar(bar_xs, vals, width=max(bw - 0.04, 0.08),
                          color=b_cols, edgecolor="#333333", lw=0.6,
                          label=s["name"], zorder=2.5, **kw)
            for j, r in enumerate(bars):
                r.set_gid("series-%d-bar-%d" % (i, j))
                if pts_groups and j < len(pts_groups) and (ch.get("show_points", True)):
                    grp = [v for v in (pts_groups[j] or []) if not math.isnan(_parse_float(v))]
                    if grp:
                        k_m = len(grp)
                        jit = [bar_xs[j] + ((t - (k_m - 1) / 2.0) * min(bw * 0.18, 0.07))
                               for t in range(k_m)]
                        ax.scatter(jit, grp, s=13, color="#FFFFFF", edgecolors="#222222",
                                   lw=0.65, zorder=3.4)
                if ch.get("show_values") and not math.isnan(vals[j]):
                    span = max(abs(max_y or 0.0), abs(min_y or 0.0), 1.0)
                    y_off = span * 0.025
                    top_pt = max(pts_groups[j]) if (pts_groups and j < len(pts_groups) and pts_groups[j]) else vals[j]
                    if vals[j] >= 0:
                        yv = max(vals[j] + (yerr[j] if yerr else 0.0), top_pt) + y_off
                        va = "bottom"
                    else:
                        yv = vals[j] - (yerr[j] if yerr else 0.0) - y_off
                        va = "top"
                    ax.text(r.get_x() + r.get_width() / 2.0, yv,
                            ("%.3g" % vals[j]), ha="center", va=va,
                            fontsize=6.5, color="#222222")
        elif kind == "box":
            bw = 0.72 / max(n, 1)
            off = (i - (n - 1) / 2.0) * bw
            pos_xs = [x + off for x in xs]
            data_boxes = []
            for j in range(len(xs)):
                if pts_groups and j < len(pts_groups) and pts_groups[j]:
                    data_boxes.append([_parse_float(v) for v in pts_groups[j] if not math.isnan(_parse_float(v))])
                else:
                    v0 = vals[j] if j < len(vals) else float("nan")
                    e0 = yerr[j] if (yerr and j < len(yerr)) else 0.0
                    data_boxes.append([v0 - e0, v0, v0 + e0] if not math.isnan(v0) else [0.0])
            bp = ax.boxplot(data_boxes, positions=pos_xs, widths=max(bw * 0.78, 0.12),
                            patch_artist=True, showfliers=False, zorder=2.5,
                            medianprops=dict(color="#10243B", lw=1.2),
                            whiskerprops=dict(color="#333333", lw=0.8),
                            capprops=dict(color="#333333", lw=0.8),
                            boxprops=dict(facecolor=color, edgecolor="#333333", lw=0.7, alpha=0.82))
            for j, bx in enumerate(bp["boxes"]):
                bx.set_gid("series-%d-box-%d" % (i, j))
                if n == 1 and not s.get("color") and ch.get("color_by_category", ch.get("legend") is False) and 2 <= len(vals) <= 7:
                    cat_pal = ["#8C9BA5", "#0072B2", "#D55E00", "#009E73", "#CC79A7", "#E69F00", "#56B4E9"]
                    bx.set_facecolor(cat_pal[j % len(cat_pal)])
                    cat_cols_used = [cat_pal[k % len(cat_pal)] for k in range(len(vals))]
                if j == 0:
                    bx.set_label(s["name"])
            if ch.get("show_points", True):
                for j, grp in enumerate(data_boxes):
                    k_m = len(grp)
                    jit = [pos_xs[j] + ((t - (k_m - 1) / 2.0) * min(bw * 0.16, 0.06))
                           for t in range(k_m)]
                    ax.scatter(jit, grp, s=13, color="#FFFFFF", edgecolors="#222222",
                               lw=0.65, zorder=3.4)
        elif kind == "stacked_bar":
            bars = ax.bar(xs, vals, width=0.62, bottom=bottom,
                          color=color, edgecolor="#333333", lw=0.6,
                          label=s["name"], zorder=2.5)
            for j, r in enumerate(bars):
                r.set_gid("series-%d-bar-%d" % (i, j))
            bottom = [bottom[k] + vals[k] for k in range(len(vals))]
            max_y = max(bottom) if bottom else max_y
        elif kind == "barh":
            bh = 0.78 / max(n, 1)
            off = (i - (n - 1) / 2.0) * bh
            kw = {}
            if yerr:
                kw.update(xerr=yerr, capsize=2.4, ecolor="#333333",
                          error_kw=dict(lw=0.9))
            if ch.get("bar_colors"):
                bh_cols = [ch["bar_colors"][j % len(ch["bar_colors"])] for j in range(len(vals))]
                cat_cols_used = bh_cols
            elif n == 1 and not s.get("color") and ch.get("color_by_sign") and any(v < 0 for v in vals if not math.isnan(v)) and any(v > 0 for v in vals if not math.isnan(v)):
                bh_cols = ["#0072B2" if (not math.isnan(v) and v >= 0) else "#D55E00" for v in vals]
                cat_cols_used = bh_cols
            else:
                bh_cols = color
            bars = ax.barh([x + off for x in xs], vals, height=max(bh - 0.04, 0.08),
                           color=bh_cols, edgecolor="#333333", lw=0.6,
                           label=s["name"], zorder=2.5, **kw)
            for j, r in enumerate(bars):
                r.set_gid("series-%d-bar-%d" % (i, j))
                if pts_groups and j < len(pts_groups) and (ch.get("show_points", True)):
                    grp = [v for v in (pts_groups[j] or []) if not math.isnan(_parse_float(v))]
                    if grp:
                        k_m = len(grp)
                        y_c = xs[j] + off
                        jit = [y_c + ((t - (k_m - 1) / 2.0) * min(bh * 0.18, 0.07)) for t in range(k_m)]
                        ax.scatter(grp, jit, s=13, color="#FFFFFF", edgecolors="#222222",
                                   lw=0.65, zorder=3.4)
                if ch.get("show_values") and not math.isnan(vals[j]):
                    span = max(abs(max_y or 0.0), abs(min_y or 0.0), 1.0)
                    top_pt = max(pts_groups[j]) if (pts_groups and j < len(pts_groups) and pts_groups[j]) else vals[j]
                    bot_pt = min(pts_groups[j]) if (pts_groups and j < len(pts_groups) and pts_groups[j]) else vals[j]
                    xv = (max(vals[j] + (yerr[j] if yerr else 0.0), top_pt) + span * 0.025) if vals[j] >= 0 else (min(vals[j] - (yerr[j] if yerr else 0.0), bot_pt) - span * 0.025)
                    ax.text(xv, r.get_y() + r.get_height() / 2.0, ("%.3g" % vals[j]),
                            ha="left" if vals[j] >= 0 else "right", va="center",
                            fontsize=6.5, color="#222222")
        elif kind == "line":
            mk = s.get("marker", "o")
            if yerr and ch.get("shade_err"):
                lo_b = [v - e for v, e in zip(vals, yerr)]
                hi_b = [v + e for v, e in zip(vals, yerr)]
                ax.fill_between(xs, lo_b, hi_b, color=color, alpha=0.16, zorder=2.2)
            if yerr:
                eb = ax.errorbar(xs, vals, yerr=yerr, marker=mk, color=color,
                                 lw=1.8, ms=4.5, capsize=2.5, elinewidth=0.9,
                                 label=s["name"], zorder=3.0)
                eb.lines[0].set_gid("series-%d" % i)
            else:
                ln, = ax.plot(xs, vals, marker=mk, color=color, lw=1.8, ms=4.5,
                              label=s["name"], zorder=3.0)
                ln.set_gid("series-%d" % i)
        else:
            sc = ax.scatter(xs, vals, s=42, color=color, edgecolors="#333333",
                            lw=0.6, label=s["name"], zorder=3.0)
            sc.set_gid("series-%d" % i)
            plabs = s.get("point_labels") or ch.get("point_labels")
            if plabs:
                for x_p, y_p, pl_t in zip(xs, vals, plabs):
                    if pl_t and not math.isnan(y_p):
                        ax.annotate(str(pl_t), (x_p, y_p), xytext=(3, 3),
                                    textcoords="offset points", fontsize=6.5, color="#222222")
        series_color_meta.append((color, cat_cols_used))

    if kind == "barh":
        import fig_style as _FS_ch
        wrapped_cats = [_FS_ch.wrap_label(str(c), max_chars=24) if len(str(c)) > 22 else str(c) for c in cats]
        has_wrapped = any("\n" in wc for wc in wrapped_cats)
        ax.set_yticks(xs)
        ax.set_yticklabels(wrapped_cats, fontsize=6.6 if has_wrapped else 7.5, linespacing=1.05)
        ax.set_ylabel(ch.get("x_label", ""), fontsize=8.5)
        xl = str(ch.get("y_label", "") or "").strip()
        u_str = str(ch.get("unit", "") or "").strip()
        if u_str and u_str.lower() != xl.lower() and ("(%s)" % u_str).lower() not in xl.lower():
            xl = (xl + " " if xl else "") + "(%s)" % u_str
        ax.set_xlabel(xl, fontsize=8.5)
        ax.xaxis.grid(True, ls=(0, (2, 3)), lw=0.5, color="#CCCCCC", zorder=0)
        if min_y is not None and min_y < 0:
            ax.axvline(0.0, color="#666666", lw=0.8, zorder=1.5)
        if ch.get("x_lim"):
            ax.set_xlim(ch["x_lim"][0], ch["x_lim"][1])
        elif max_y is not None or min_y is not None:
            pad_f = 0.24 if ch.get("show_values") else 0.14
            hi_x = max(max_y or 0.0, 0.0)
            lo_x = min(min_y or 0.0, 0.0)
            span_x = max(hi_x - lo_x, 1.0)
            ax.set_xlim(
                left=(lo_x - span_x * pad_f) if lo_x < 0 else 0.0,
                right=(hi_x + span_x * pad_f) if hi_x > 0 else (span_x * 0.15),
            )
    else:
        if not x_vals:
            ax.set_xticks(xs)
            rot = 25 if any(len(str(c)) > 10 for c in cats) else 0
            ax.set_xticklabels(cats, fontsize=7.5, rotation=rot,
                               ha="right" if rot else "center")
        elif ch.get("_auto_xticks") and not ch.get("x_scale"):
            ax.set_xticks(ch["_auto_xticks"])
            ax.set_xticklabels([("%g" % v) for v in ch["_auto_xticks"]], fontsize=7.5)
        ax.set_xlabel(ch.get("x_label", ""), fontsize=8.5)
        yl = str(ch.get("y_label", "") or "").strip()
        u_str = str(ch.get("unit", "") or "").strip()
        if u_str and u_str.lower() != yl.lower() and ("(%s)" % u_str).lower() not in yl.lower():
            yl = (yl + " " if yl else "") + "(%s)" % u_str
        ax.set_ylabel(yl, fontsize=8.5)
        ax.yaxis.grid(True, ls=(0, (2, 3)), lw=0.5, color="#CCCCCC", zorder=0)
        if min_y is not None and min_y < 0 and not ch.get("y_scale"):
            ax.axhline(0.0, color="#666666", lw=0.8, zorder=1.5)
        if ch.get("x_scale"):
            if str(ch["x_scale"]).lower() == "log" and xs and any(v <= 0 for v in xs):
                pos_min = min((v for v in xs if v > 0), default=1.0)
                ax.set_xscale("symlog", linthresh=max(pos_min * 0.5, 1e-3))
                uniq_x = sorted(set(xs))
                if len(uniq_x) <= 8:
                    from matplotlib.ticker import NullLocator
                    ax.set_xticks(uniq_x)
                    ax.set_xticklabels([("%g" % v) for v in uniq_x], fontsize=7.5)
                    ax.xaxis.set_minor_locator(NullLocator())
            else:
                ax.set_xscale(ch["x_scale"])
        if ch.get("y_scale"):
            ax.set_yscale(ch["y_scale"])
        elif ch.get("y_lim") is None and (max_y is not None or min_y is not None):
            if min_y is not None and min_y < 0:
                hi_y = max(max_y or 0.0, 0.0) * 1.24
                lo_y = min_y * (1.34 if ch.get("show_values") else 1.22)
                ax.set_ylim(bottom=lo_y, top=hi_y if hi_y > 0 else 0.2 * abs(min_y))
            elif max_y is not None and max_y > 0:
                lo_y = 0.0 if kind in ("bar", "stacked_bar") else None
                ax.set_ylim(bottom=lo_y, top=max_y * 1.24)
        if ch.get("y_lim"):
            lo_req, hi_req = ch["y_lim"][0], ch["y_lim"][1]
            if str(ch.get("y_scale", "")).lower() == "log" and lo_req <= 0:
                lo_req = max(min((v for v in [min_y] if v is not None and v > 0), default=1e-2) * 0.5, 1e-6)
            ax.set_ylim(lo_req, hi_req)

    for hl in ch.get("hlines", []):
        if isinstance(hl, (int, float)):
            hl = {"y": float(hl)}
        yv = float(hl.get("y", 0.0))
        ax.axhline(yv, color=hl.get("color", "#666666"),
                   ls=hl.get("ls", (0, (4, 2))), lw=float(hl.get("lw", 0.9)), zorder=1.8)
        if hl.get("label"):
            ax.text(0.99, yv, " " + str(hl["label"]), transform=ax.get_yaxis_transform(),
                    ha="right", va="bottom", fontsize=6.5, color=hl.get("color", "#444444"),
                    bbox=dict(fc="#FFFFFF", ec="none", alpha=0.86, pad=0.5), zorder=4.2)
    for vl in ch.get("vlines", []):
        if isinstance(vl, (int, float)):
            vl = {"x": float(vl)}
        xv = float(vl.get("x", 0.0))
        ax.axvline(xv, color=vl.get("color", "#666666"),
                   ls=vl.get("ls", (0, (4, 2))), lw=float(vl.get("lw", 0.9)), zorder=1.8)
        if vl.get("label"):
            ax.text(xv, 0.98, " " + str(vl["label"]), transform=ax.get_xaxis_transform(),
                    ha="left", va="top", fontsize=6.5, color=vl.get("color", "#555555"), zorder=4.0)

    # Statistical significance brackets (e.g. [{"x1": 0, "x2": 1, "label": "***"}])
    sig_brackets = ch.get("sig_brackets") or []
    if sig_brackets and kind != "barh":
        cat_to_x = {str(c): xs[idx] for idx, c in enumerate(cats) if idx < len(xs)}
        is_log_y = str(ch.get("y_scale", "")).lower() == "log"
        if is_log_y:
            base_y = max(max_y or 1.0, 1e-6) * (1.70 if ch.get("show_values") else 1.48)
            for bi, br in enumerate(sig_brackets):
                rx1, rx2 = br.get("x1", 0), br.get("x2", 1)
                bx1 = cat_to_x[str(rx1)] if str(rx1) in cat_to_x else float(rx1)
                bx2 = cat_to_x[str(rx2)] if str(rx2) in cat_to_x else float(rx2)
                by = float(br["y"]) if br.get("y") is not None else (base_y * (1.42 ** bi))
                ax.plot([bx1, bx1, bx2, bx2], [by * 0.88, by, by, by * 0.88],
                        color="#222222", lw=0.85, zorder=4.2)
                ax.text(0.5 * (bx1 + bx2), by * 1.06, str(br.get("label", "*")),
                        ha="center", va="bottom", fontsize=7.2, fontweight="bold",
                        color="#222222", zorder=4.3)
            if ch.get("y_lim") is None:
                lo_cur, hi_cur = ax.get_ylim()
                top_need = base_y * (1.42 ** len(sig_brackets)) * 1.15
                if top_need > hi_cur:
                    ax.set_ylim(bottom=lo_cur, top=top_need)
        else:
            span = max(abs(max_y or 0.0), abs((max_y or 0.0) - (min_y or 0.0)), 1.0)
            step = span * 0.11
            cur_y = (max_y if max_y is not None else 1.0) + span * (0.14 if ch.get("show_values") else 0.07)
            for bi, br in enumerate(sig_brackets):
                rx1, rx2 = br.get("x1", 0), br.get("x2", 1)
                bx1 = cat_to_x[str(rx1)] if str(rx1) in cat_to_x else float(rx1)
                bx2 = cat_to_x[str(rx2)] if str(rx2) in cat_to_x else float(rx2)
                by = float(br["y"]) if br.get("y") is not None else (cur_y + bi * step)
                tick_h = span * 0.028
                ax.plot([bx1, bx1, bx2, bx2], [by - tick_h, by, by, by - tick_h],
                        color="#222222", lw=0.85, zorder=4.2)
                ax.text(0.5 * (bx1 + bx2), by + span * 0.012, str(br.get("label", "*")),
                        ha="center", va="bottom", fontsize=7.2, fontweight="bold",
                        color="#222222", zorder=4.3)
            top_need = cur_y + len(sig_brackets) * step + span * 0.08
            if ch.get("y_lim") is None and not ch.get("y_scale"):
                lo_cur, hi_cur = ax.get_ylim()
                if top_need > hi_cur:
                    ax.set_ylim(bottom=lo_cur, top=top_need)

    for ann in ch.get("annotations", []):
        ax.text(ann.get("x", 0), ann.get("y", 0), ann.get("text", ""),
                ha="center", va="bottom", fontsize=ann.get("fs", 8.0),
                fontweight="bold", color=ann.get("color", "#222222"), zorder=4.0)

    ax.tick_params(labelsize=7.5, length=2.5, width=0.7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_linewidth(0.9)
    ax.spines["bottom"].set_linewidth(0.9)
    ax.set_axisbelow(True)

    show_leg = ch.get("legend", True) and n > 0
    if show_leg:
        loc = effective_legend_loc(ch) or "best"
        if loc == "top":
            leg = ax.legend(fontsize=7.0, frameon=True, edgecolor="#CCCCCC",
                            facecolor="#FFFFFF", framealpha=0.95, fancybox=False,
                            loc="lower center", bbox_to_anchor=(0.5, 1.02),
                            ncol=min(n, 4))
        else:
            leg = ax.legend(fontsize=7.2, frameon=True, edgecolor="#CCCCCC",
                            facecolor="#FFFFFF", framealpha=0.92,
                            fancybox=False, loc=loc)
        leg.set_gid("legend-%s" % panel.get("id", "0"))
        leg.get_frame().set_linewidth(0.7)

    return {
        "kind": kind,
        "categories": [str(c) for c in cats],
        "n_categories": len(cats) if cats else len(xs),
        "n_series": n,
        "series_names": [s.get("name", "") for s in series],
        "series_lengths": [len(s.get("values", [])) for s in series],
        "series_data": [
            {"name": s.get("name", "series%d" % idx),
             "color": series_color_meta[idx][0] if idx < len(series_color_meta) else None,
             "category_colors": series_color_meta[idx][1] if idx < len(series_color_meta) else None,
             "values": [None if math.isnan(_parse_float(v)) else round(_parse_float(v), 6)
                        for v in s.get("values", [])],
             "errors": ([None if math.isnan(_parse_float(e)) else round(_parse_float(e), 6)
                         for e in s["errors"]] if s.get("errors") else None),
             "n": s.get("n"),
             "source": s.get("source")}
            for idx, s in enumerate(series)
        ],
        "legend_entries": n if show_leg else 0,
        "unit": ch.get("unit", ""),
        "x_label": ch.get("x_label", ""),
        "y_label": ch.get("y_label", ""),
        "data_file": ch.get("data_file"),
        "sheet_name": ch.get("sheet_name"),
        "source_sha256": ch.get("_source_sha256"),
    }
