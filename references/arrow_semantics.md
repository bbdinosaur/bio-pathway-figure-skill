# Interaction semantics — how wording maps to arrows

Every edge type has a distinct color AND endpoint marker, so the map stays legible in
grayscale print and the legend can be generated from actual usage.

| Input wording | `type` | Endpoint | Color | Notes |
|---|---|---|---|---|
| activates, promotes, stimulates, drives, enhances | `activation` | filled triangle ▶ | blue #1d4ed8 | default direct arrow |
| recruits, docks, scaffolds | `recruitment` | filled triangle ▶ | blue | use when the verb is recruitment |
| inhibits, suppresses, blocks, represses, dephosphorylates(inactivating) | `inhibition` | bar-headed ⊣ | red #dc2626 | NEVER draw as pointed arrow |
| binds, associates with, forms complex with | `binding` | diamond ◇ both ends | purple #7c3aed | no direction implied |
| phosphorylates | `phosphorylation` | filled circle ● at target | amber #b45309 | label residue e.g. `P-Y1045` |
| ubiquitinates | `ubiquitination` | filled circle ● | brown #92400e | label `Ub` |
| imports/exports, shuttles | `transport` | open triangle ▷ | teal #0f766e | cross-compartment |
| translocates (cytosol→nucleus etc.) | `translocation` | open triangle ▷ | teal | edge must cross the compartment boundary |
| expresses, induces transcription of | `expression` | open triangle ▷ | slate #475569 | source usually a gene node |
| unclear / not stated | `other` | filled triangle | dark gray | mark `dashed:true` + note in exceptions |

## Direction rules (topology is semantics)
1. Upstream → downstream: ligand → receptor → adaptor → kinase cascade → transcription factor → gene.
2. Receptors sit IN the membrane band; ligands above it; signal flows toward the nucleus.
3. An edge must not contradict the compartment model (e.g. a cytosolic kinase directly
   hitting a ligand in the extracellular space is suspect — re-read the source).
4. Feedback loops: use `route:"feedback"` and, if only reported indirectly, `dashed:true`.
5. Never invent an edge. If the material says "may/possibly/putatively", draw it dashed
   and say so in the caption and `content_map`.

## Evidence & uncertainty encoding
- Solid = stated as direct in the material; add `"evidence":"direct"` only when the source
  says so (label becomes `[direct]`).
- `dashed:true` = indirect, inferred, or reported-only; explain in the caption.
- Optional auto-styling (spec `"layout":{"evidence_auto_style":true}`): edges with
  `evidence` of reported/inferred/indirect/putative render dashed automatically, and
  `weak` renders dotted; the legend gains the matching samples. Legend entries derive
  from actual usage, so legend ≡ map always holds.
- Conflict between two sources: draw both edges with labels naming the source of each,
  and record the conflict in `exceptions` of result.json.

## Mod tags on nodes
`"mods":["P","Ub"]` draw corner tags (P amber, Ub brown, Ac purple, GTP teal). Use them
instead of duplicating state inside the label; keep labels short (names, not sentences).
