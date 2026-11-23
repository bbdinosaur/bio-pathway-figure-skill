# Interaction Semantics, Node Shapes & Evidence Encoding

Every interaction type has a distinct **color + endpoint marker (+ optional start glyph)** so the
pathway remains unambiguous in grayscale print and the legend is generated directly from usage.

## Edge Taxonomy (`edges[].type`)

| Biological wording | `type` | Endpoint & start glyph | Color | Default style |
|---|---|---|---|---|
| activates, promotes, stimulates, drives | `activation` | filled triangle `▶` | `#1d4ed8` blue | solid |
| recruits, docks, scaffolds | `recruitment` | start dot `○` + filled `▶` | `#0284c7` cyan | solid |
| inhibits, suppresses, blocks, represses | `inhibition` | flat T-bar `⊣` | `#dc2626` red | solid (NEVER arrow) |
| binds, associates, dimerizes, complexes | `binding` | diamond `◇` both ends | `#7c3aed` purple | solid (undirected) |
| phosphorylates | `phosphorylation` | badge circle `℗` (`P`) | `#b45309` amber | solid; optional site label e.g. `pT/Y` |
| ubiquitinates | `ubiquitination` | badge circle (`Ub`) | `#92400e` brown | solid |
| acetylates, methylates, SUMOylates, cleaves | `modification` | badge circle (`M`) | `#a21caf` magenta | solid; label mod |
| imports, exports, shuttles | `transport` | open triangle `▷` | `#0f766e` dark teal | solid |
| translocates (across compartment border) | `translocation` | start dot `○` + open `▷` | `#0d9488` teal | solid |
| expresses (protein/mRNA level) | `expression` | open triangle `▷` | `#475569` slate | solid |
| induces transcription of gene target | `transcription` | promoter bar `|` + open `▷` | `#4f46e5` indigo | solid (target `kind:"gene"`) |
| degrades, targets to proteasome/lysosome | `degradation` | cross `×` | `#991b1b` dark red | dashed by default |
| direction unknown / correlative association | `undirected` | hollow circles `○—○` both ends | `#64748b` slate | dashed (NEVER false arrow) |
| unclear / unspecified mechanism | `other` | filled triangle `▶` | `#334155` charcoal | set `dashed:true` + exception |

## Node Kinds (`nodes[].kind`)

| Kind | Visual encoding | Typical biological entities |
|---|---|---|
| `receptor` | Green rounded rect spanning membrane lipid bilayer | EGFR, FZD4, LRP5/6, TLR4, GPCR |
| `protein` | Blue rounded rect, roman bold | Kinases, adaptors, transcription factors |
| `gene` | Amber rounded rect, **italic bold** | *MYC*, *CCND1*, *DUSP6*, target loci |
| `complex` | Purple **double-bordered** rect | Destruction complex, mTORC1, PRC2 |
| `metabolite` | Emerald hexagon | ATP, cAMP, lactate, lipid ligands |
| `drug` | Rose hexagon | Small-molecule inhibitors, agonists |
| `process` / `phenotype` | Green rounded pill | Proliferation, apoptosis, EMT |
| `cell` | Soft-red ellipse | T cell, macrophage, tumor cell |
| `dna` | Slate rect | Enhancer, promoter, chromatin locus |

## Post-Translational Modification (PTM) Corner Badges (`nodes[].mods`)
`P` (amber, Phosphorylation), `Ub` (brown, Ubiquitination), `Ac` (purple, Acetylation),
`GTP` (teal, GTP-bound), `Me` (magenta, Methylation), `SUMO` (sky blue, SUMOylation).
Any badge used on a node is automatically added to the `Modifications` section of the legend.

## Direction, Feedback & Uncertainty Rules
1. **Upstream → downstream**: signal flows top-to-bottom across compartments (exterior → membrane
   → cytosol → organelle/nucleus) and left-to-right within tiers.
2. **Feedback loops**: set `"route": "feedback"`. Same-row feedback routes along a clean staggered
   top channel; cross-compartment feedback automatically takes an obstacle-free right-margin outer
   rail without cutting through any intermediate node.
3. **Evidence strength**: solid = direct experimental evidence; `dashed: true` = indirect,
   inferred, or literature-reported; `dotted: true` = weak evidence. With
   `"layout": {"evidence_auto_style": true}`, `evidence` of `reported|inferred|indirect|putative`
   auto-dashes and `weak` auto-dots, with matching legend entries.
4. **Source conflicts**: draw both edges labeled with their respective sources and record the
   discrepancy in `exceptions`.
