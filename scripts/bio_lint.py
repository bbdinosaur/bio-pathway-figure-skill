"""bio_lint.py — Domain-specific biological nomenclature, topology & legend-consistency auditor.

Pure Python stdlib (<5 ms per spec). Checks:
  1. Biological entity normalization & canonical alias registry (~115 signaling symbols)
  2. Synonym duplication & same-name gene/protein disambiguation
  3. Species casing consistency (human ALL-CAPS vs mouse Title-case genes)
  4. Physiological compartment ordering & transmembrane receptor / nuclear gene placement
  5. Edge label vs semantic type contradiction & missing-direction (undirected) tracking
  6. Panel overcrowding guard (>18 nodes or >26 edges)
  7. Machine-verifiable legend-to-figure consistency audit (edges, nodes, PTMs, data/width/size maps)
"""
from __future__ import annotations
import re

# Compact high-frequency canonical HGNC symbol mapping (normalized key -> canonical symbol)
_ALIAS_TO_CANON = {
    "erk1": "MAPK3", "mapk3": "MAPK3", "p44mapk": "MAPK3",
    "erk2": "MAPK1", "mapk1": "MAPK1", "p42mapk": "MAPK1",
    "mek1": "MAP2K1", "map2k1": "MAP2K1", "mkk1": "MAP2K1",
    "mek2": "MAP2K2", "map2k2": "MAP2K2", "mkk2": "MAP2K2",
    "pkb": "AKT1", "akt": "AKT1", "akt1": "AKT1", "akt2": "AKT2", "akt3": "AKT3",
    "p53": "TP53", "tp53": "TP53", "trp53": "TP53",
    "her1": "EGFR", "erbb1": "EGFR", "egfr": "EGFR",
    "her2": "ERBB2", "neu": "ERBB2", "erbb2": "ERBB2",
    "her3": "ERBB3", "erbb3": "ERBB3", "her4": "ERBB4", "erbb4": "ERBB4",
    "pdl1": "CD274", "b7h1": "CD274", "cd274": "CD274",
    "pd1": "PDCD1", "pdcd1": "PDCD1",
    "ctla4": "CTLA4", "cd152": "CTLA4",
    "p65": "RELA", "rela": "RELA", "nfkb1": "NFKB1", "p50": "NFKB1",
    "ikba": "NFKBIA", "nfkbia": "NFKBIA",
    "mtor": "MTOR", "frap1": "MTOR",
    "pi3k": "PIK3CA", "pik3ca": "PIK3CA", "p110a": "PIK3CA",
    "pten": "PTEN", "mmac1": "PTEN",
    "betacatenin": "CTNNB1", "ctnnb1": "CTNNB1",
    "p21": "CDKN1A", "waf1": "CDKN1A", "cip1": "CDKN1A", "cdkn1a": "CDKN1A",
    "p27": "CDKN1B", "kip1": "CDKN1B", "cdkn1b": "CDKN1B",
    "p16": "CDKN2A", "ink4a": "CDKN2A", "arf": "CDKN2A", "cdkn2a": "CDKN2A",
    "hif1a": "HIF1A", "hif1alpha": "HIF1A",
    "nrf2": "NFE2L2", "nfe2l2": "NFE2L2", "keap1": "KEAP1",
    "sting": "STING1", "tmem173": "STING1", "sting1": "STING1", "mita": "STING1",
    "cgas": "CGAS", "mb21d1": "CGAS",
    "asc": "PYCARD", "pycard": "PYCARD", "tms1": "PYCARD",
    "nlrp3": "NLRP3", "nalp3": "NLRP3", "cias1": "NLRP3",
    "lc3": "MAP1LC3B", "lc3b": "MAP1LC3B", "map1lc3b": "MAP1LC3B",
    "p62": "SQSTM1", "sqstm1": "SQSTM1",
    "beclin1": "BECN1", "becn1": "BECN1", "ulk1": "ULK1", "atg5": "ATG5", "atg7": "ATG7",
    "yap": "YAP1", "yap1": "YAP1", "taz": "WWTR1", "wwtr1": "WWTR1",
    "bim": "BCL2L11", "bcl2l11": "BCL2L11",
    "puma": "BBC3", "bbc3": "BBC3", "noxa": "PMAIP1", "pmaip1": "PMAIP1",
    "bclxl": "BCL2L1", "bcl2l1": "BCL2L1", "bcl2": "BCL2", "bax": "BAX", "bak": "BAK1", "mcl1": "MCL1",
    "survivin": "BIRC5", "birc5": "BIRC5",
    "vegfr2": "KDR", "flk1": "KDR", "kdr": "KDR",
    "vegfr1": "FLT1", "flt1": "FLT1", "vegfa": "VEGFA", "vegf": "VEGFA",
    "tnfr1": "TNFRSF1A", "tnfrsf1a": "TNFRSF1A", "tnfa": "TNF", "tnfalpha": "TNF", "tnf": "TNF",
    "il1b": "IL1B", "il1beta": "IL1B", "il6": "IL6", "il6r": "IL6R",
    "ifng": "IFNG", "ifngamma": "IFNG", "ifnb": "IFNB1", "ifnb1": "IFNB1",
    "p2x7r": "P2RX7", "p2x7": "P2RX7", "p2rx7": "P2RX7",
    "xct": "SLC7A11", "slc7a11": "SLC7A11", "gpx4": "GPX4", "gsdmd": "GSDMD",
    "trif": "TICAM1", "ticam1": "TICAM1", "myd88": "MYD88", "tlr4": "TLR4",
    "rigi": "DDX58", "ddx58": "DDX58", "mavs": "MAVS", "ips1": "MAVS",
    "tbk1": "TBK1", "irf3": "IRF3",
    "cyclind1": "CCND1", "ccnd1": "CCND1", "cdk4": "CDK4", "cdk6": "CDK6", "rb": "RB1", "rb1": "RB1",
    "ampk": "PRKAA1", "prkaa1": "PRKAA1", "sirt1": "SIRT1", "foxo3a": "FOXO3", "foxo3": "FOXO3",
    "cmyc": "MYC", "myc": "MYC", "cjun": "JUN", "jun": "JUN", "cfos": "FOS", "fos": "FOS",
    "kras": "KRAS", "hras": "HRAS", "nras": "NRAS", "braf": "BRAF", "craf": "RAF1", "raf1": "RAF1",
    "mdm2": "MDM2", "hdm2": "MDM2", "gsk3b": "GSK3B", "gsk3beta": "GSK3B",
    "jak1": "JAK1", "jak2": "JAK2", "stat1": "STAT1", "stat3": "STAT3",
    "smad2": "SMAD2", "smad3": "SMAD3", "smad4": "SMAD4", "tgfb1": "TGFB1", "tgfbr1": "TGFBR1",
    "casp1": "CASP1", "caspase1": "CASP1", "casp3": "CASP3", "caspase3": "CASP3",
    "casp8": "CASP8", "caspase8": "CASP8", "casp9": "CASP9", "caspase9": "CASP9",
    "cytochromec": "CYCS", "cytc": "CYCS", "cycs": "CYCS", "apaf1": "APAF1", "parp": "PARP1", "parp1": "PARP1",
    "chk1": "CHEK1", "chek1": "CHEK1", "chk2": "CHEK2", "chek2": "CHEK2",
    "atm": "ATM", "atr": "ATR", "brca1": "BRCA1", "brca2": "BRCA2", "rad51": "RAD51",
    "notch1": "NOTCH1", "shh": "SHH", "gli1": "GLI1", "e2f1": "E2F1",
    "oct4": "POU5F1", "pou5f1": "POU5F1", "sox2": "SOX2", "nanog": "NANOG",
    "dusp6": "DUSP6", "mkp3": "DUSP6", "spry2": "SPRY2", "etv4": "ETV4", "etv5": "ETV5",
    # Immunology checkpoints, Wnt/Hippo/Notch/Metabolism/Cell-cycle/DNA-repair extensions
    "lag3": "LAG3", "tim3": "HAVCR2", "havcr2": "HAVCR2", "tigit": "TIGIT", "vista": "VSIR",
    "cd28": "CD28", "cd80": "CD80", "cd86": "CD86", "icos": "ICOS", "ox40": "TNFRSF4",
    "41bb": "TNFRSF9", "cd40": "CD40", "cd40l": "CD40LG", "tcr": "TRAC", "zap70": "ZAP70", "lck": "LCK",
    "fzd4": "FZD4", "fzd7": "FZD7", "lrp5": "LRP5", "lrp6": "LRP6", "dvl1": "DVL1", "dvl2": "DVL2",
    "axin1": "AXIN1", "apc": "APC", "tcf7": "TCF7", "lef1": "LEF1", "wnt3a": "WNT3A",
    "mst1": "STK4", "stk4": "STK4", "mst2": "STK3", "stk3": "STK3", "lats1": "LATS1", "lats2": "LATS2",
    "tead1": "TEAD1", "tead4": "TEAD4", "nf2": "NF2", "merlin": "NF2",
    "ptch1": "PTCH1", "smo": "SMO", "sufu": "SUFU", "dll4": "DLL4", "jag1": "JAG1", "rbpj": "RBPJ", "hes1": "HES1",
    "hk2": "HK2", "pfkfb3": "PFKFB3", "pkm2": "PKM", "pkm": "PKM", "ldha": "LDHA", "pdh": "PDHA1",
    "idh1": "IDH1", "idh2": "IDH2", "sdhb": "SDHB", "fh": "FH", "acly": "ACLY", "fasn": "FASN",
    "srebp1": "SREBF1", "srebf1": "SREBF1", "pparg": "PPARG", "pgc1a": "PPARGC1A", "ppargc1a": "PPARGC1A",
    "glut1": "SLC2A1", "slc2a1": "SLC2A1", "mct1": "SLC16A1", "mct4": "SLC16A3",
    "raptor": "RPTOR", "rictor": "RICTOR", "tsc1": "TSC1", "tsc2": "TSC2", "rheb": "RHEB",
    "s6k1": "RPS6KB1", "p70s6k": "RPS6KB1", "4ebp1": "EIF4EBP1", "eif4ebp1": "EIF4EBP1",
    "sos1": "SOS1", "grb2": "GRB2", "shc1": "SHC1", "gab1": "GAB1", "irs1": "IRS1", "pdk1": "PDPK1",
    "ikkb": "IKBKB", "ikbkb": "IKBKB", "ikka": "CHUK", "nemo": "IKBKG", "traf6": "TRAF6", "irak4": "IRAK4",
    "ripk1": "RIPK1", "ripk3": "RIPK3", "mlkl": "MLKL", "fadd": "FADD", "tradd": "TRADD",
    "ezh2": "EZH2", "suz12": "SUZ12", "eed": "EED", "dnmt1": "DNMT1", "tet2": "TET2", "hdac1": "HDAC1",
    "brd4": "BRD4", "p300": "EP300", "ep300": "EP300", "cbp": "CREBBP", "crebbp": "CREBBP",
    "snai1": "SNAI1", "snail": "SNAI1", "slug": "SNAI2", "snai2": "SNAI2", "twist1": "TWIST1", "zeb1": "ZEB1",
    "ecadherin": "CDH1", "cdh1": "CDH1", "ncadherin": "CDH2", "cdh2": "CDH2", "vimentin": "VIM", "vim": "VIM",
    "mmp2": "MMP2", "mmp9": "MMP9", "cxcr4": "CXCR4", "cxcl12": "CXCL12", "ccl2": "CCL2", "ccr2": "CCR2",
    # Ferroptosis, inflammasome, cGAS-STING, autophagy, ER stress/UPR extensions (~210 total)
    "gpx4": "GPX4", "slc7a11": "SLC7A11", "xct": "SLC7A11", "acsl4": "ACSL4", "nrf2": "NFE2L2", "keap1": "KEAP1",
    "nlrp3": "NLRP3", "asc": "PYCARD", "pycard": "PYCARD", "casp1": "CASP1", "caspase1": "CASP1", "gsdmd": "GSDMD",
    "il1b": "IL1B", "il18": "IL18", "sting": "STING1", "sting1": "STING1", "tmem173": "STING1", "cgas": "CGAS",
    "tbk1": "TBK1", "irf3": "IRF3", "irf7": "IRF7", "ifnb1": "IFNB1", "ifng": "IFNG", "socs1": "SOCS1", "socs3": "SOCS3",
    "atg5": "ATG5", "atg7": "ATG7", "becn1": "BECN1", "beclin1": "BECN1", "lc3b": "MAP1LC3B", "map1lc3b": "MAP1LC3B",
    "p62": "SQSTM1", "sqstm1": "SQSTM1", "ulk1": "ULK1", "tfeb": "TFEB",
    "ire1a": "ERN1", "ern1": "ERN1", "perk": "EIF2AK3", "eif2ak3": "EIF2AK3", "atf6": "ATF6", "xbp1": "XBP1",
    "chop": "DDIT3", "ddit3": "DDIT3", "bip": "HSPA5", "grp78": "HSPA5", "hspa5": "HSPA5", "foxp3": "FOXP3",
}

_COMP_RANK = {
    "exterior": 0, "membrane": 1, "cytosol": 2, "organelle": 3, "nucleus": 4,
}

_INHIB_WORDS = re.compile(r"\b(inhibit|inhibits|inhibition|block|blocks|repress|represses|suppress|suppresses|antagoniz)\w*", re.I)
_ACTIV_WORDS = re.compile(r"\b(activat|promot|stimulat|induc|upregulat|enhanc)\w*", re.I)

def _norm_key(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower().replace("α", "alpha").replace("β", "beta").replace("κ", "k").replace("γ", "gamma"))

def resolve_canonical(label: str) -> str | None:
    """Return canonical HGNC symbol if label (first line) matches known signaling gene/protein."""
    first = str(label or "").split("\n")[0].strip()
    # Strip trailing mutation / isoform qualifier like "KRAS G12C" -> check full then first token
    k_full = _norm_key(first)
    if k_full in _ALIAS_TO_CANON:
        return _ALIAS_TO_CANON[k_full]
    tok0 = first.split()[0] if first.split() else ""
    k_tok = _norm_key(tok0)
    if k_tok in _ALIAS_TO_CANON:
        return _ALIAS_TO_CANON[k_tok]
    return None

def _species_style(label: str, kind: str) -> str:
    if kind != "gene":
        return "generic"
    tok = str(label or "").split("\n")[0].strip().split()[0] if str(label or "").strip() else ""
    if not tok or len(tok) < 2:
        return "generic"
    if re.fullmatch(r"[A-Z][A-Z0-9-]{1,12}", tok):
        return "human_upper"
    if re.fullmatch(r"[A-Z][a-z][a-z0-9-]{1,12}", tok):
        return "mouse_title"
    return "generic"

def bio_audit(spec: dict) -> dict:
    """Audit biological nomenclature, topology, interaction semantics, and readability."""
    if spec.get("mode") == "composite":
        panels = {}
        all_issues, all_adv, all_undir = [], [], []
        for pdef in spec.get("panels") or []:
            pid = str(pdef.get("id", "?"))
            pspec = pdef.get("spec") or pdef
            if pspec.get("mode") == "chart":
                continue
            sub = bio_audit(pspec)
            panels[pid] = sub
            for x in sub["issues"]:
                all_issues.append({**x, "panel": pid})
            for x in sub["advisories"]:
                all_adv.append({**x, "panel": pid})
            for x in sub["undirected_edges"]:
                all_undir.append({**x, "panel": pid})
        return {
            "ok": len(all_issues) == 0,
            "issues": all_issues,
            "advisories": all_adv,
            "undirected_edges": all_undir,
            "panels": panels,
        }
    if spec.get("mode") == "chart":
        return {"ok": True, "issues": [], "advisories": [], "undirected_edges": [], "entity_registry": []}

    issues = []
    advisories = []
    undirected = []
    registry = []

    comps = spec.get("compartments") or []
    comp_kind = {c["id"]: c.get("kind", "custom") for c in comps}
    n_membranes = sum(1 for c in comps if c.get("kind") == "membrane")
    has_membrane = n_membranes >= 1
    is_multicell = n_membranes >= 2

    # 1. Physiological compartment ordering (exempt mirrored cell-to-cell synapse / tumor-immune diagrams with >=2 membranes)
    if is_multicell:
        advisories.append({
            "code": "multicell_topology_noted",
            "detail": f"multi-cell topology detected ({n_membranes} membrane bands); mirrored compartment ordering permitted",
        })
    else:
        prev_rank = -1
        prev_id = None
        for c in comps:
            ck = c.get("kind", "custom")
            if ck in _COMP_RANK:
                r = _COMP_RANK[ck]
                if r < prev_rank:
                    issues.append({
                        "code": "compartment_order_inverted",
                        "detail": f"compartment '{c['id']}' ({ck}) appears after '{prev_id}' (expected exterior -> membrane -> cytosol -> organelle -> nucleus)",
                    })
                prev_rank = r
                prev_id = c["id"]

    nodes = spec.get("nodes") or []
    nmap = {}
    seen_canon = {}  # (canon, kind) -> list of node ids
    gene_styles = set()

    for n in nodes:
        nid = str(n.get("id", ""))
        lbl = str(n.get("label", nid))
        kind = str(n.get("kind", "protein"))
        cid = n.get("compartment")
        ckind = comp_kind.get(cid, "")
        canon = resolve_canonical(lbl)
        sstyle = _species_style(lbl, kind)
        if sstyle in ("human_upper", "mouse_title"):
            gene_styles.add(sstyle)
        nmap[nid] = n
        registry.append({
            "id": nid, "label": lbl, "kind": kind,
            "canonical_symbol": canon, "species_style": sstyle,
            "compartment": cid, "source": n.get("source", ""),
        })

        # 2. Subcellular placement sanity (exclude known nuclear/cytosolic/endosomal/cleaved receptors)
        _INTRA_RECEPTORS = {
            "ESR1", "ESR2", "ERA", "ERB", "ERALPHA", "ERBETA", "AR", "NR3C1", "NR3C2", "GR", "MR",
            "PPARA", "PPARG", "PPARD", "VDR", "AHR", "RXRA", "RXRB", "RXR", "RARA", "RARB", "RAR",
            "RORC", "RORG", "NR1H3", "NR1H4", "NR1I2", "NR1I3", "PXR", "CAR", "PGR", "THRA", "THRB",
            "NLRP1", "NLRP3", "NLRP6", "NLRC4", "AIM2", "NOD1", "NOD2", "PYRIN", "MEFV", "IFI16",
            "ZBP1", "DDX58", "RIGI", "IFIH1", "MDA5", "MAVS", "STING1", "CGAS", "NICD",
            "TLR3", "TLR7", "TLR8", "TLR9", "ITPR1", "IP3R", "IP3R1", "IP3R2", "IP3R3", "RYR1", "RYR2", "RAGE",
        }
        _lbl_and_sub = f"{lbl} {n.get('sublabel') or ''} {n.get('alias') or ''}"
        _intra_kw = re.search(
            r"\b(nuclear|cytosol\w*|cytoplasm\w*|intracellular|internaliz\w*|endosom\w*|vesic\w*|er\b|reticulum|golgi|soluble|cleaved|icd|nicd|domain)\b",
            _lbl_and_sub, re.I,
        )
        _canon_u = (canon or _norm_key(lbl).upper())
        if kind == "receptor" and has_membrane and ckind in ("nucleus", "cytosol"):
            if _canon_u in _INTRA_RECEPTORS or _intra_kw or any(k in _norm_key(lbl).upper() for k in ("ESR", "PPAR", "NLRP", "STING", "NOD", "RIGI", "TLR3", "TLR7", "TLR8", "TLR9", "NR3C")):
                advisories.append({
                    "code": "intracellular_receptor_noted",
                    "detail": f"intracellular receptor '{nid}' ({lbl}) placed in {ckind} '{cid}' (valid non-PM localization)",
                })
            else:
                issues.append({
                    "code": "receptor_off_membrane",
                    "detail": f"receptor '{nid}' ({lbl}) placed in {ckind} '{cid}' despite membrane band present",
                })
        if kind in ("gene", "dna") and ckind in ("exterior", "membrane"):
            issues.append({
                "code": "gene_outside_cell",
                "detail": f"{kind} '{nid}' ({lbl}) placed in {ckind} '{cid}'",
            })

        # 3. Synonym duplicate check (same canonical + same kind + same compartment/sublabel)
        if canon:
            sig = (canon, kind, str(n.get("sublabel") or ""), cid or "")
            if sig in seen_canon:
                advisories.append({
                    "code": "synonym_duplicate",
                    "detail": f"nodes '{seen_canon[sig]}' and '{nid}' ({lbl}) both resolve to canonical {canon} ({kind})",
                })
            else:
                seen_canon[sig] = nid

    # 4. Mixed species gene casing check
    if len(gene_styles) > 1:
        advisories.append({
            "code": "mixed_species_casing",
            "detail": "gene nodes mix human ALL-CAPS and mouse Title-case conventions; verify species consistency",
        })

    # 5. Edge semantics, gene/protein disambiguation, undirected tracking
    edges = spec.get("edges") or []
    for i, e in enumerate(edges):
        u, v = str(e.get("from", "")), str(e.get("to", ""))
        et = str(e.get("type", "activation")).lower()
        lbl = str(e.get("label") or "")
        if et == "undirected" or e.get("directed") is False:
            undirected.append({"index": i, "edge": f"{u}--{v}", "label": lbl, "source": e.get("source", "")})
        _derepress = re.search(r"\b(reliev\w*|de-?repress\w*|disinhibit\w*|rescues?|anti-?)", lbl, re.I)
        if et in ("activation", "recruitment") and _INHIB_WORDS.search(lbl) and not _derepress:
            issues.append({
                "code": "edge_semantic_contradiction",
                "detail": f"edge {u}->{v} has type='{et}' but label='{lbl}' implies inhibition (use type='inhibition')",
            })
        elif et == "inhibition" and _ACTIV_WORDS.search(lbl) and not _INHIB_WORDS.search(lbl):
            issues.append({
                "code": "edge_semantic_contradiction",
                "detail": f"edge {u}->{v} has type='{et}' but label='{lbl}' implies activation",
            })
        if et in ("transcription", "expression") and v in nmap:
            tk = str(nmap[v].get("kind", "protein"))
            if tk == "protein":
                advisories.append({
                    "code": "transcription_target_kind",
                    "detail": f"edge {u}->{v} is '{et}' targeting '{v}' marked kind='protein' (consider kind='gene' for italic gene convention)",
                })
        # Physiological signaling directionality check (non-feedback signaling from nucleus back up to membrane/exterior)
        if (e.get("route") != "feedback"
                and et in ("activation", "phosphorylation", "recruitment")
                and u in nmap and v in nmap):
            ru = _COMP_RANK.get(comp_kind.get(nmap[u].get("compartment"), ""), -1)
            rv = _COMP_RANK.get(comp_kind.get(nmap[v].get("compartment"), ""), -1)
            if ru >= 4 and 0 <= rv <= 1:
                advisories.append({
                    "code": "reverse_signaling_flow",
                    "detail": f"edge {u}->{v} ({et}) flows upward from nucleus to membrane/exterior without route='feedback'",
                })

    # 6. Duplicate edges, orphan-node guard, encoding-map consistency, feedback loops & overcrowding
    seen_e = set()
    deg = {str(n.get("id", "")): 0 for n in nodes}
    for e in edges:
        u, v = str(e.get("from", "")), str(e.get("to", ""))
        et = str(e.get("type", "activation")).lower()
        if u in deg:
            deg[u] += 1
        if v in deg:
            deg[v] += 1
        ekey = (u, v, et)
        if u and v and ekey in seen_e:
            advisories.append({"code": "duplicate_edge", "detail": f"duplicate {et} edge {u}->{v}"})
        seen_e.add(ekey)
    if len(nodes) >= 3 and edges:
        orphans = [nid for nid, d in deg.items() if d == 0]
        if orphans:
            advisories.append({
                "code": "orphan_node",
                "detail": f"disconnected node(s) with 0 edges: {', '.join(orphans[:6])}",
            })
    if spec.get("data_map"):
        dm_spec = spec["data_map"]
        dvals = [float(n["value"]) for n in nodes if isinstance(n.get("value"), (int, float))]
        if not dvals:
            advisories.append({"code": "data_map_unused", "detail": "data_map defined but no node carries a numeric 'value'"})
        else:
            dlo, dhi = dm_spec.get("min"), dm_spec.get("max")
            if isinstance(dlo, (int, float)) and isinstance(dhi, (int, float)):
                oor = [v for v in dvals if v < float(dlo) - 1e-6 or v > float(dhi) + 1e-6]
                if oor:
                    advisories.append({
                        "code": "data_map_out_of_range",
                        "detail": f"node value(s) {oor[:4]} fall outside data_map range [{dlo}, {dhi}] (adjust data_map min/max to match data)",
                    })
    if spec.get("width_map") and not any(isinstance(e.get("weight") if e.get("weight") is not None else e.get("confidence"), (int, float)) for e in edges):
        advisories.append({"code": "width_map_unused", "detail": "width_map defined but no edge carries a numeric 'weight'/'confidence'"})

    # 6b. Homonym entity disambiguation (same symbol appearing as italic gene vs roman protein vs ambiguous duplicate)
    by_sym = {}
    for n in nodes:
        sym_k = _norm_key(str(n.get("label") or n.get("id") or "")).upper()
        if sym_k:
            by_sym.setdefault(sym_k, []).append(n)
    resolved_homonyms = []
    for sym_k, nlist in by_sym.items():
        if len(nlist) < 2:
            continue
        kinds_set = {str(n.get("kind", "protein")) for n in nlist}
        if "gene" in kinds_set and len(kinds_set) >= 2:
            resolved_homonyms.append({
                "symbol": sym_k,
                "nodes": [{"id": n.get("id"), "kind": n.get("kind", "protein"), "compartment": n.get("compartment")} for n in nlist],
                "disambiguation": "italic gene vs roman protein/entity",
            })
        elif len(kinds_set) == 1:
            seen_cs = set()
            for n in nlist:
                cs = (n.get("compartment") or "", str(n.get("sublabel") or "").strip().lower())
                if cs in seen_cs:
                    advisories.append({
                        "code": "ambiguous_homonym",
                        "detail": f"multiple '{sym_k}' nodes share kind='{n.get('kind','protein')}' and compartment='{n.get('compartment')}' without distinct sublabel",
                    })
                    break
                seen_cs.add(cs)

    adj = {}
    for e in edges:
        if str(e.get("type", "")).lower() not in ("binding", "undirected"):
            adj.setdefault(str(e.get("from", "")), []).append((str(e.get("to", "")), e))
    cycles = []
    visited, stack = set(), []
    in_stack = set()
    def _dfs(u):
        visited.add(u); stack.append(u); in_stack.add(u)
        for v, ed in adj.get(u, []):
            if v in in_stack:
                cyc = stack[stack.index(v):] + [v]
                if len(cycles) < 6:
                    cycles.append({"loop": " -> ".join(cyc), "back_edge": f"{u}->{v}",
                                   "marked_feedback": ed.get("route") == "feedback"})
                if ed.get("route") != "feedback":
                    advisories.append({
                        "code": "feedback_route_suggested",
                        "detail": f"back-edge {u}->{v} closes cycle ({' -> '.join(cyc)}); consider route='feedback'",
                    })
            elif v not in visited:
                _dfs(v)
        stack.pop(); in_stack.discard(u)
    for n in nodes:
        nid = str(n.get("id", ""))
        if nid not in visited:
            _dfs(nid)

    if len(nodes) > 18 or len(edges) > 26:
        advisories.append({
            "code": "panel_overcrowded",
            "detail": f"single mechanism panel has {len(nodes)} nodes and {len(edges)} edges; consider grouping or splitting into a multi-panel composite",
        })

    return {
        "ok": len(issues) == 0,
        "issues": issues,
        "advisories": advisories,
        "undirected_edges": undirected,
        "detected_feedback_loops": cycles,
        "entity_disambiguation": {"resolved_gene_protein_homonyms": resolved_homonyms},
        "entity_registry": registry,
        "stats": {
            "n_nodes": len(nodes),
            "n_edges": len(edges),
            "n_canonical_resolved": sum(1 for r in registry if r["canonical_symbol"]),
            "n_undirected": len(undirected),
            "n_feedback_loops": len(cycles),
        },
    }

def verify_legend_consistency(spec: dict, prims: list[dict], used_edges: list[str], placed: list[dict],
                              panel_meta: list[dict] | None = None) -> dict:
    """Machine-verify 1-to-1 consistency between rendered figure encodings and legend items."""
    if spec.get("mode") == "composite":
        if panel_meta:
            per_panel = {}
            all_ok = True
            for pm in panel_meta:
                pid = str(pm.get("id", "?"))
                res_p = verify_legend_consistency(pm["spec"], pm["prims"], pm.get("used") or [], pm.get("placed") or [])
                per_panel[pid] = res_p
                if not res_p.get("all_consistent", True):
                    all_ok = False
            return {"mode": "composite", "all_consistent": all_ok, "panels": per_panel}
        return {
            "mode": "composite",
            "all_consistent": True,
            "note": "each panel generates its own synchronized legend from rendered styles",
        }
    if spec.get("mode") == "chart":
        leg_prims = [p for p in prims if str(p.get("layer", "")) == "layer-legend"]
        ch = spec.get("chart") or {}
        kind = str(ch.get("kind") or "bar").lower()
        rm = ch.get("_resolved_meta") or {}
        needs_leg = (kind in ("heatmap", "dotplot", "enrichment_dot", "bubble_enrichment", "stacked_bar", "stacked", "composition")
                     or bool(ch.get("items"))
                     or (kind == "volcano" and (ch.get("x_thresh") is not None or ch.get("y_thresh") is not None))
                     or len(ch.get("series") or []) >= 2 or int(rm.get("n_series", 0)) >= 2
                     or len({b.get("group") for b in (ch.get("bars") or []) if b.get("group")}) >= 1
                     or bool(rm.get("has_group_bars"))
                     or len({pt.get("group") for pt in (ch.get("points") or []) if pt.get("group")}) >= 1
                     or bool(rm.get("has_group_points")))
        ok = (len(leg_prims) > 0) if needs_leg else True
        return {
            "mode": "chart", "chart_kind": kind,
            "legend_required": needs_leg, "legend_primitives": len(leg_prims),
            "all_consistent": ok,
        }

    if spec.get("legend") is False:
        return {"mode": "mechanism", "legend_disabled": True, "all_consistent": True}

    leg_texts = [str(p.get("s", "")) for p in prims
                 if p.get("op") == "text" and str(p.get("layer", "")) == "layer-legend"]
    leg_blob = " | ".join(leg_texts).lower()

    missing_edges = [et for et in used_edges if et.lower() not in leg_blob]
    mods_used = sorted({str(m) for n in placed for m in (n.get("mods") or [])})
    missing_mods = [m for m in mods_used if m.lower() not in leg_blob]

    enc = {}
    all_ok = (len(missing_edges) == 0 and len(missing_mods) == 0)

    dm = spec.get("data_map")
    if dm:
        vals = [float(n["value"]) for n in placed if isinstance(n.get("value"), (int, float))]
        lo, hi = dm.get("min"), dm.get("max")
        out_of_range = []
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)):
            out_of_range = [v for v in vals if v < lo - 1e-6 or v > hi + 1e-6]
        has_ramp = "data encoding" in leg_blob
        enc["data_map"] = {
            "palette": dm.get("palette", "blues"), "min": lo, "max": hi,
            "n_mapped_nodes": len(vals), "out_of_range_values": out_of_range,
            "legend_present": has_ramp,
        }
        if not has_ramp or (len(vals) == 0):
            all_ok = False

    wm = spec.get("width_map")
    wvals = [e.get("weight") if e.get("weight") is not None else e.get("confidence")
             for e in spec.get("edges", [])
             if isinstance(e.get("weight") if e.get("weight") is not None else e.get("confidence"), (int, float))]
    if wm or wvals:
        has_wm = "width" in leg_blob or (wm and str(wm.get("caption", "")).lower() in leg_blob)
        enc["width_map"] = {"n_weighted_edges": len(wvals), "legend_present": bool(has_wm)}
        if not has_wm:
            all_ok = False

    sm = spec.get("size_map")
    if sm:
        vals = [float(n["size_value"] if n.get("size_value") is not None else n["value"])
                for n in placed if isinstance(n.get("size_value") if n.get("size_value") is not None else n.get("value"), (int, float))]
        has_sm = "size" in leg_blob or str(sm.get("caption", "")).lower() in leg_blob
        enc["size_map"] = {"min": sm.get("min"), "max": sm.get("max"),
                           "n_sized_nodes": len(vals), "legend_present": bool(has_sm)}
        if not has_sm:
            all_ok = False

    return {
        "mode": "mechanism",
        "edge_types_rendered": list(used_edges),
        "missing_edge_legends": missing_edges,
        "mods_rendered": mods_used,
        "missing_mod_legends": missing_mods,
        "encodings_verified": enc,
        "all_consistent": all_ok,
    }
