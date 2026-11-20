# Naming, identity & provenance rules

1. **Gene vs protein**: gene symbols are italic (engine italicizes nodes of `kind:"gene"`);
   proteins are roman. If one symbol denotes both (e.g. MYC), draw separate gene and
   protein nodes when the mechanism distinguishes them, otherwise use the protein node.
2. **Species prefixes**: human `EGFR`, mouse `Egfr`, `EGFR` with species noted once in the
   caption when the material mixes species. Never silently rename.
3. **Aliases**: put old/synonym names in `alias` (rendered small above the node) rather
   than replacing the current HGNC symbol; note the mapping in `content_map`.
4. **Complexes**: use `kind:"complex"` (double border) when the material describes a
   complex as one functional unit; list members in `alias` or draw individual members with
   `binding` edges when the material specifies composition.
5. **IDs**: if the material provides UniProt/HGNC/Reactome IDs, append them to the node's
   `source` field: `"source":"Materials §3.2; UniProt:P00533"`.
6. **Provenance strings**: every node/edge `source` must cite the case material location
   (section, figure, table, line). The engine writes them into `content_map` of result.json
   via the summary/checks files — keep them precise, they are what makes the figure auditable.

# Layout, legend & export rules

- Compartments vertical order should mirror the mechanism (exterior → membrane → cytosol →
  nucleus). Use `organelle` bands for mitochondria/ER when the material requires them.
- The legend is auto-built from actual usage: edge types present, node kinds used, dashed
  evidence line, and `data_map` gradient. Do not hand-edit the SVG legend.
- Node fill encoding: when the material gives per-node quantitative data (expression,
  fold-change, confidence), map it to fill via the palette and describe it in `data_map`
  with min/max captions. If no data, omit `data_map` — legend shrinks accordingly.
- Fonts: SVG uses a font stack (Helvetica/Arial/DejaVu Sans) — replaceable; PNG/PDF via
  matplotlib use DejaVu Sans. Both are exportable at 300 dpi by default.
- Every delivered figure must pass `check_figure.py` with `n_violations: 0` before it is
  considered final; violations listed honestly if a case must ship partial.

# No-script fallback (if `scripts/` are unavailable)
Write the SVG by hand with this minimal skeleton (same conventions), then export PNG/PDF:
```svg
<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" font-family="Helvetica,Arial,sans-serif">
  <rect width="1200" height="800" fill="#fff"/>
  <rect x="20" y="480" width="1160" height="280" rx="10" fill="#eaf1fb" stroke="#b6c8e3"/> <!-- nucleus -->
  <rect x="20" y="180" width="1160" height="60" fill="#e8eef4" stroke="#94a3b8"/>           <!-- membrane -->
  <rect x="480" y="184" width="120" height="52" fill="#e5f3ea" stroke="#3a8f5f"/>           <!-- receptor spans membrane -->
  <line x1="540" y1="240" x2="540" y2="330" stroke="#1d4ed8" stroke-width="2.4"/>
  <polygon points="540,344 533,330 547,330" fill="#1d4ed8"/>                                 <!-- activation head -->
  <line x1="700" y1="330" x2="700" y2="250" stroke="#dc2626" stroke-width="2.4"/>
  <line x1="690" y1="250" x2="710" y2="250" stroke="#dc2626" stroke-width="3.6"/>            <!-- inhibition bar -->
  <text x="540" y="216" font-size="15" font-weight="bold" text-anchor="middle">EGFR</text>
  <text x="20" y="60" font-size="21" font-weight="bold">Title</text>
</svg>
```
Export: `python3 -c "import cairosvg; cairosvg.svg2png(url='f.svg',write_to='f.png',output_width=2400)"`
or `rsvg-convert -w 2400 f.svg > f.png`, or open in a browser and print to PDF. State in
result.json which export path was used.
