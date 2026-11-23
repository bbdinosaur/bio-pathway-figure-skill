# Naming, Provenance, Layout & Fallback Rules

## Biological Naming & Provenance
1. **Gene vs protein**: always distinguish gene loci (`kind: "gene"`, rendered *italic*) from
   encoded proteins (`kind: "protein"`, roman). When a mechanism distinguishes transcription of
   gene *MYC* from MYC protein activity, draw separate nodes.
2. **Species convention**: preserve exact species casing from the material (human `EGFR`, mouse
   `Egfr`, *Arabidopsis* `UVR8`). Never silently rename across species.
3. **Aliases & synonyms**: keep the primary symbol in `label` and place old/common synonyms in
   `alias` (rendered small italic above the node, e.g., `beta-catenin` above `CTNNB1`); log the
   mapping in `content_map`.
4. **Complexes vs module groups**: use `kind: "complex"` (double border) for a single functional
   complex node; use `"groups": [{"id": ..., "label": ..., "members": [...]}]` when individual
   subunits and intra-complex edges are shown.
5. **Identifiers & citations**: if the material gives UniProt/HGNC/Reactome/KEGG IDs, append them
   to `source` (e.g., `"Materials §3.2 p.5; UniProt:P00533"`). Every node, edge, group, and chart
   series MUST cite its exact location in the source material.

## Layout, Legend & Export Parity
- **Compartment order**: declare compartments in physiological top-to-bottom order (`exterior` →
  `membrane` → `cytosol` → `organelle` → `nucleus`). Membrane bands render a lipid bilayer
  interrupted cleanly by transmembrane receptors and the compartment label.
- **Band tightening & multi-tier placement**: `tighten_bands` and `auto_tier` are enabled by
  default; dense cytosolic cascades (>1350 px single row) split automatically into clean vertical
  tiers, or you may assign explicit integer `"row": 0, 1, 2` on nodes.
- **Legend auto-sync**: the rounded legend card is generated strictly from rendered elements
  (interaction styles used, node shapes used, PTM badges used, module groups, dashed/dotted
  evidence lines, and `data_map` color ramp). Never hand-edit the legend inside SVG.
- **SVG / PNG / PDF parity**: `viz_svg.py` emits named `<g id="layer-...">` layers (and
  `<g id="panel-A">` for composites) with editable font stacks (`Helvetica, Arial, DejaVu Sans,
  Noto Sans CJK SC`); `viz_mpl.py` uses fixed logical-px scaling (`72/96 pt/px`) and TrueType
  font embedding (`pdf.fonttype = 42`) so 100 DPI preview, 300 DPI PNG, PDF, and SVG match.
- **Dual audit gate**: every figure is audited both at IR level (`viz_check.py`: canvas bounds,
  text overlap, edge-label-on-node, boundary attachment) and by re-parsing raw delivered SVG bytes
  (`check_figure.py`). Target `n_violations: 0` on both.

## No-Script Fallback (if `scripts/` are unavailable)
Write a layered SVG directly with matching conventions and rasterize with `cairosvg` or
`rsvg-convert`:
```xml
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 1200 800"
     font-family="Helvetica, Arial, 'DejaVu Sans', sans-serif">
  <g id="layer-canvas"><rect width="1200" height="800" fill="#ffffff"/></g>
  <g id="layer-compartments">
    <rect x="32" y="180" width="1136" height="68" rx="10" fill="#e7eef5" stroke="#94a3b8"/>
    <rect x="32" y="480" width="1136" height="260" rx="10" fill="#eaf1fc" stroke="#adc3e2"/>
  </g>
  <g id="layer-edges">
    <line x1="540" y1="244" x2="540" y2="332" stroke="#1d4ed8" stroke-width="2.3"/>
    <polygon points="540,345 534,332 546,332" fill="#1d4ed8"/>
    <line x1="700" y1="332" x2="700" y2="250" stroke="#dc2626" stroke-width="2.3"/>
    <line x1="691" y1="250" x2="709" y2="250" stroke="#dc2626" stroke-width="3.5"/>
  </g>
  <g id="layer-nodes">
    <rect id="shape-EGFR" x="480" y="184" width="120" height="60" rx="8" fill="#e2f4ea" stroke="#2f855a" stroke-width="1.8"/>
    <text id="label-EGFR" x="540" y="214" font-size="14.5" font-weight="bold" text-anchor="middle" dominant-baseline="central">EGFR</text>
  </g>
</svg>
```
Export fallback:
`python3 -c "import cairosvg; cairosvg.svg2png(url='fig.svg',write_to='fig.png',output_width=2400); cairosvg.svg2pdf(url='fig.svg',write_to='fig.pdf')"`
(or `rsvg-convert -w 2400 -o fig.png fig.svg`). Record the actual export tool used in `result.json`.
