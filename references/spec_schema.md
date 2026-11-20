# Mechanism spec schema (`spec.json`)

`make_figure.py` consumes one JSON file. Unknown keys are ignored; missing keys use defaults.

```json
{
  "mode": "mechanism",                  // or "chart"
  "title": "short declarative title",
  "caption": "evidence + source note (auto-wrapped)",
  "compartments": [                      // order = vertical order top->bottom
    {"id":"ext","label":"Extracellular space","kind":"exterior"},
    {"id":"mb","label":"Plasma membrane","kind":"membrane"},
    {"id":"cyt","label":"Cytosol","kind":"cytosol"},
    {"id":"nuc","label":"Nucleus","kind":"nucleus"}
  ],                                     // kinds: exterior|membrane|cytosol|nucleus|organelle|custom
  "nodes": [
    {"id":"EGFR","label":"EGFR","kind":"receptor","compartment":"mb",
     "mods":["P"],                        // corner tags: P, Ub, Ac, GTP
     "alias":"ERBB1 (old name)",          // small italic alias above node
     "x":300,"y":200,"w":120,"h":46,      // optional explicit placement overrides auto layout
     "fill":"#e3ecfb",                    // optional data-encoded fill (document in data_map)
     "source":"Materials §3.1"}           // provenance string, lands in content_map
  ],                                      // node kinds: receptor|protein|gene|complex|metabolite|cell|dna|other
  "edges": [
    {"from":"EGFR","to":"GRB2","type":"recruitment",
     "label":"pY1045",                    // printed on the edge
     "evidence":"direct",                 // appended as [direct]
     "dashed":true,                       // indirect / reported only
     "route":"feedback",                  // orthogonal loop above both nodes
     "source":"§3.2"}
  ],                                      // types: activation|inhibition|binding|phosphorylation|
                                          // ubiquitination|transport|translocation|recruitment|
                                          // expression|other  (see arrow_semantics.md)
  "data_map": {"palette":"blues","min":"low expr.","max":"high expr.",
               "caption":"Node fill encodes RNA expression (TPM, Table S2)."},
  "legend": true                          // false hides legend panel entirely
}
```

## Auto-layout rules
- Nodes are grouped by `compartment`, centered as a row inside the band, ordered as declared.
- Receptors in a `membrane` compartment automatically span the full band height (transmembrane).
- Inter-compartment row width = widest compartment; all rows centered; gap adapts so edge
  labels never sit on node boxes. Very wide cascades (≥6 nodes, >1700px) switch to a
  2-row serpentine automatically.
- A straight SAME-ROW edge that would pass BEHIND an intermediate node can be auto-routed
  as a short arc above the row on its own staggered height rail — enable with
  `"layout":{"auto_arc":true}`. Cross-compartment edges always stay straight.
- `route:"feedback"` routes above both nodes; use for inhibitory feedback loops.
- Optional size encoding: `"size_map":{"min":..,"max":..}` scales node height by each
  node's numeric `value` (0.72x–1.28x); describe it in `data_map.size_caption`.
- Optional band tightening: `"layout":{"tighten_bands":true}` shrinks compartment bands
  to their node extent (+padding; explicit y0/y1 are always respected).
- Both layout flags default OFF (classic straight-line look); enable when the workorder
  asks for denser or more disambiguated layouts.

## Chart mode (`"mode":"chart"`)
```json
{"mode":"chart","title":"...",
 "chart":{"x_label":"Gene","y_label":"Fold change",
          "y_note":"n=3, SEM, t-test (Table 1)",
          "bars":[{"label":"MYC","value":4.2,"err":0.4,"group":"stimulated"}],
          "stars":[{"pair":[0,3],"text":"**"}]}}
```
Bars are colored by `group`; value labels, SEM error bars, significance brackets and a
group legend are drawn automatically; y ticks are snapped to nice steps.
Every numeric value in `bars` MUST come from the case material (table/text), cited in `y_note`.
