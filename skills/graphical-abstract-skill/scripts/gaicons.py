#!/usr/bin/env python3
"""Pure-SVG scientific visual icon motifs (biology, chemistry, materials, devices).

All icons draw inside a centered square [cx-r, cx+r] x [cy-r, cy+r] using plain
SVG 1.1 primitives (circle/ellipse/rect/line/polygon/path) so they stay crisp,
editable in Inkscape/Illustrator, and safe across Chrome/soffice renderers.
"""
from __future__ import annotations

import math


def render_icon(name: str, cx: float, cy: float, r: float = 13.0,
                color: str = "#0072B2", bg: str = "#FFFFFF") -> str:
    """Return SVG snippet for a named scientific icon; empty string if unknown."""
    k = (name or "").strip().lower().replace("-", "_").replace(" ", "_")
    if not k:
        return ""
    s = r / 14.0
    out = [f'<g data-kind="sci-icon" data-icon="{k}">']

    if k in ("cell", "eukaryote", "host_cell"):
        out.append(f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{13*s:.1f}" ry="{10.5*s:.1f}" '
                   f'fill="{bg}" stroke="{color}" stroke-width="{1.6*s:.1f}"/>')
        out.append(f'<ellipse cx="{cx+1.5*s:.1f}" cy="{cy+0.5*s:.1f}" rx="{5.2*s:.1f}" ry="{4.2*s:.1f}" '
                   f'fill="{color}" fill-opacity="0.22" stroke="{color}" stroke-width="{1.2*s:.1f}"/>')
        out.append(f'<circle cx="{cx+2*s:.1f}" cy="{cy+0.5*s:.1f}" r="{1.6*s:.1f}" fill="{color}"/>')

    elif k in ("nucleus", "gene_expr"):
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{11.5*s:.1f}" '
                   f'fill="{color}" fill-opacity="0.14" stroke="{color}" '
                   f'stroke-width="{1.6*s:.1f}" stroke-dasharray="{3*s:.1f} {2*s:.1f}"/>')
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{4.2*s:.1f}" fill="{color}" fill-opacity="0.45"/>')

    elif k in ("membrane", "bilayer"):
        for dx in (-9, -4.5, 0, 4.5, 9):
            x = cx + dx * s
            out.append(f'<circle cx="{x:.1f}" cy="{cy-4.5*s:.1f}" r="{2.0*s:.1f}" fill="{color}"/>')
            out.append(f'<circle cx="{x:.1f}" cy="{cy+4.5*s:.1f}" r="{2.0*s:.1f}" fill="{color}"/>')
            out.append(f'<line x1="{x:.1f}" y1="{cy-2.5*s:.1f}" x2="{x:.1f}" y2="{cy+2.5*s:.1f}" '
                       f'stroke="{color}" stroke-width="{1.1*s:.1f}"/>')

    elif k in ("receptor", "channel", "egfr", "kinase"):
        # Transmembrane Y-shaped receptor across bilayer bar
        out.append(f'<rect x="{cx-12*s:.1f}" y="{cy-1.5*s:.1f}" width="{24*s:.1f}" height="{3.5*s:.1f}" '
                   f'rx="{1.5*s:.1f}" fill="{color}" fill-opacity="0.25"/>')
        out.append(f'<path d="M {cx-6*s:.1f},{cy-10*s:.1f} L {cx:.1f},{cy-3*s:.1f} '
                   f'L {cx+6*s:.1f},{cy-10*s:.1f} M {cx:.1f},{cy-3*s:.1f} L {cx:.1f},{cy+9*s:.1f}" '
                   f'fill="none" stroke="{color}" stroke-width="{2.2*s:.1f}" stroke-linecap="round"/>')
        out.append(f'<circle cx="{cx:.1f}" cy="{cy+9.5*s:.1f}" r="{2.3*s:.1f}" fill="{color}"/>')

    elif k in ("antibody", "nanobody", "igg", "conjugate"):
        out.append(f'<path d="M {cx-7.5*s:.1f},{cy-9*s:.1f} L {cx:.1f},{cy-1.5*s:.1f} '
                   f'L {cx+7.5*s:.1f},{cy-9*s:.1f} M {cx:.1f},{cy-1.5*s:.1f} L {cx:.1f},{cy+9.5*s:.1f}" '
                   f'fill="none" stroke="{color}" stroke-width="{2.4*s:.1f}" stroke-linecap="round"/>')
        out.append(f'<circle cx="{cx-7.5*s:.1f}" cy="{cy-9*s:.1f}" r="{2.2*s:.1f}" fill="#D55E00"/>')
        out.append(f'<circle cx="{cx+7.5*s:.1f}" cy="{cy-9*s:.1f}" r="{2.2*s:.1f}" fill="#D55E00"/>')

    elif k in ("drug", "pill", "inhibitor", "small_molecule", "therapy"):
        # Angled two-tone pharmaceutical capsule (distinct from IgG antibody)
        out.append(f'<g transform="rotate(-35 {cx:.1f} {cy:.1f})">')
        out.append(f'<rect x="{cx-9.5*s:.1f}" y="{cy-4.6*s:.1f}" width="{19*s:.1f}" height="{9.2*s:.1f}" '
                   f'rx="{4.6*s:.1f}" fill="{bg}" stroke="{color}" stroke-width="{1.6*s:.1f}"/>')
        out.append(f'<rect x="{cx-9.5*s:.1f}" y="{cy-4.6*s:.1f}" width="{9.5*s:.1f}" height="{9.2*s:.1f}" '
                   f'rx="{4.6*s:.1f}" fill="{color}" fill-opacity="0.72"/>')
        out.append(f'<line x1="{cx:.1f}" y1="{cy-4.5*s:.1f}" x2="{cx:.1f}" y2="{cy+4.5*s:.1f}" '
                   f'stroke="{color}" stroke-width="{1.4*s:.1f}"/>')
        out.append('</g>')

    elif k in ("dna", "genome", "gene"):
        out.append(f'<path d="M {cx-7*s:.1f},{cy-10*s:.1f} C {cx+7*s:.1f},{cy-5*s:.1f} '
                   f'{cx-7*s:.1f},{cy+5*s:.1f} {cx+7*s:.1f},{cy+10*s:.1f}" '
                   f'fill="none" stroke="{color}" stroke-width="{1.8*s:.1f}"/>')
        out.append(f'<path d="M {cx+7*s:.1f},{cy-10*s:.1f} C {cx-7*s:.1f},{cy-5*s:.1f} '
                   f'{cx+7*s:.1f},{cy+5*s:.1f} {cx-7*s:.1f},{cy+10*s:.1f}" '
                   f'fill="none" stroke="{color}" stroke-width="{1.8*s:.1f}" stroke-opacity="0.55"/>')
        for dy in (-6, 0, 6):
            out.append(f'<line x1="{cx-4.5*s:.1f}" y1="{cy+dy*s:.1f}" x2="{cx+4.5*s:.1f}" '
                       f'y2="{cy+dy*s:.1f}" stroke="{color}" stroke-width="{1.1*s:.1f}"/>')

    elif k in ("rna", "mrna", "transcript"):
        out.append(f'<path d="M {cx-9*s:.1f},{cy+4*s:.1f} Q {cx-4*s:.1f},{cy-8*s:.1f} {cx:.1f},{cy:.1f} '
                   f'T {cx+9*s:.1f},{cy-4*s:.1f}" fill="none" stroke="{color}" stroke-width="{2.0*s:.1f}"/>')
        for dx in (-6, -2, 2, 6):
            out.append(f'<line x1="{cx+dx*s:.1f}" y1="{cy:.1f}" x2="{cx+dx*s:.1f}" '
                       f'y2="{cy+4.5*s:.1f}" stroke="{color}" stroke-width="{1.2*s:.1f}"/>')

    elif k in ("protein", "enzyme", "ligand", "cytokine"):
        out.append(f'<circle cx="{cx-4*s:.1f}" cy="{cy-2*s:.1f}" r="{5.5*s:.1f}" '
                   f'fill="{color}" fill-opacity="0.22" stroke="{color}" stroke-width="{1.5*s:.1f}"/>')
        out.append(f'<circle cx="{cx+4.5*s:.1f}" cy="{cy+2.5*s:.1f}" r="{5.0*s:.1f}" '
                   f'fill="{color}" fill-opacity="0.32" stroke="{color}" stroke-width="{1.5*s:.1f}"/>')
        out.append(f'<circle cx="{cx+2*s:.1f}" cy="{cy-5*s:.1f}" r="{3.2*s:.1f}" fill="{color}"/>')

    elif k in ("nanoparticle", "vesicle", "liposome", "exosome"):
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{7.5*s:.1f}" '
                   f'fill="{color}" fill-opacity="0.20" stroke="{color}" stroke-width="{1.7*s:.1f}"/>')
        for ang in range(0, 360, 45):
            rad = math.radians(ang)
            x1, y1 = cx + math.cos(rad) * 7.5 * s, cy + math.sin(rad) * 7.5 * s
            x2, y2 = cx + math.cos(rad) * 11.5 * s, cy + math.sin(rad) * 11.5 * s
            out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                       f'stroke="{color}" stroke-width="{1.3*s:.1f}"/>')
            out.append(f'<circle cx="{x2:.1f}" cy="{y2:.1f}" r="{1.5*s:.1f}" fill="{color}"/>')

    elif k in ("microbe", "bacteria", "microbiome"):
        out.append(f'<rect x="{cx-9*s:.1f}" y="{cy-5*s:.1f}" width="{16*s:.1f}" height="{10*s:.1f}" '
                   f'rx="{5*s:.1f}" fill="{color}" fill-opacity="0.22" stroke="{color}" stroke-width="{1.6*s:.1f}"/>')
        out.append(f'<path d="M {cx+7*s:.1f},{cy:.1f} Q {cx+10*s:.1f},{cy-4*s:.1f} {cx+12.5*s:.1f},{cy+1*s:.1f}" '
                   f'fill="none" stroke="{color}" stroke-width="{1.4*s:.1f}"/>')

    elif k in ("tumor", "organoid", "tissue", "cluster"):
        for dx, dy, cr in ((-4, -3, 4.5), (4, -2, 4.2), (0, 4, 4.6), (-5, 3.5, 3.6), (5, 3.5, 3.4)):
            out.append(f'<circle cx="{cx+dx*s:.1f}" cy="{cy+dy*s:.1f}" r="{cr*s:.1f}" '
                       f'fill="{color}" fill-opacity="0.25" stroke="{color}" stroke-width="{1.2*s:.1f}"/>')

    elif k in ("mitochondria", "metabolism"):
        out.append(f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{11.5*s:.1f}" ry="{6.5*s:.1f}" '
                   f'fill="{color}" fill-opacity="0.18" stroke="{color}" stroke-width="{1.6*s:.1f}"/>')
        out.append(f'<path d="M {cx-8*s:.1f},{cy:.1f} L {cx-4*s:.1f},{cy-3*s:.1f} L {cx:.1f},{cy+3*s:.1f} '
                   f'L {cx+4*s:.1f},{cy-3*s:.1f} L {cx+8*s:.1f},{cy:.1f}" '
                   f'fill="none" stroke="{color}" stroke-width="{1.4*s:.1f}"/>')

    elif k in ("molecule", "compound", "chemical", "metabolite"):
        pts = []
        for i in range(6):
            a = math.radians(60 * i - 30)
            pts.append((cx + math.cos(a) * 8.5 * s, cy + math.sin(a) * 8.5 * s))
        pstr = " ".join(f"{px:.1f},{py:.1f}" for px, py in pts)
        out.append(f'<polygon points="{pstr}" fill="{color}" fill-opacity="0.14" '
                   f'stroke="{color}" stroke-width="{1.7*s:.1f}"/>')
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{3.6*s:.1f}" fill="none" '
                   f'stroke="{color}" stroke-width="{1.2*s:.1f}"/>')

    elif k in ("catalyst", "lattice", "crystal", "surface", "material"):
        for r0 in (-6, 0, 6):
            for c0 in (-6, 0, 6):
                is_c = (r0 == 0 and c0 == 0)
                out.append(f'<circle cx="{cx+c0*s:.1f}" cy="{cy+r0*s:.1f}" '
                           f'r="{(3.2 if is_c else 2.0)*s:.1f}" '
                           f'fill="{"#D55E00" if is_c else color}"/>')
        out.append(f'<line x1="{cx-6*s:.1f}" y1="{cy:.1f}" x2="{cx+6*s:.1f}" y2="{cy:.1f}" '
                   f'stroke="{color}" stroke-width="{1.0*s:.1f}" stroke-opacity="0.5"/>')
        out.append(f'<line x1="{cx:.1f}" y1="{cy-6*s:.1f}" x2="{cx:.1f}" y2="{cy+6*s:.1f}" '
                   f'stroke="{color}" stroke-width="{1.0*s:.1f}" stroke-opacity="0.5"/>')

    elif k in ("electrode", "battery", "energy", "device", "chip"):
        out.append(f'<rect x="{cx-9*s:.1f}" y="{cy-8*s:.1f}" width="{18*s:.1f}" height="{16*s:.1f}" '
                   f'rx="{2.5*s:.1f}" fill="{color}" fill-opacity="0.16" stroke="{color}" stroke-width="{1.6*s:.1f}"/>')
        out.append(f'<path d="M {cx+1*s:.1f},{cy-5*s:.1f} L {cx-3*s:.1f},{cy+1*s:.1f} '
                   f'L {cx+1*s:.1f},{cy+1*s:.1f} L {cx-1*s:.1f},{cy+6*s:.1f}" '
                   f'fill="none" stroke="{color}" stroke-width="{1.9*s:.1f}" stroke-linecap="round"/>')

    elif k in ("flask", "assay", "screen", "experiment"):
        out.append(f'<path d="M {cx-3*s:.1f},{cy-10*s:.1f} L {cx-3*s:.1f},{cy-3*s:.1f} '
                   f'L {cx-9.5*s:.1f},{cy+9*s:.1f} L {cx+9.5*s:.1f},{cy+9*s:.1f} '
                   f'L {cx+3*s:.1f},{cy-3*s:.1f} L {cx+3*s:.1f},{cy-10*s:.1f} Z" '
                   f'fill="{color}" fill-opacity="0.18" stroke="{color}" stroke-width="{1.6*s:.1f}"/>')
        out.append(f'<line x1="{cx-5*s:.1f}" y1="{cy+3*s:.1f}" x2="{cx+5*s:.1f}" y2="{cy+3*s:.1f}" '
                   f'stroke="{color}" stroke-width="{1.5*s:.1f}"/>')

    elif k in ("microscope", "imaging", "spectroscopy"):
        out.append(f'<circle cx="{cx-2*s:.1f}" cy="{cy-2*s:.1f}" r="{6.5*s:.1f}" '
                   f'fill="{color}" fill-opacity="0.16" stroke="{color}" stroke-width="{1.8*s:.1f}"/>')
        out.append(f'<line x1="{cx+3*s:.1f}" y1="{cy+3*s:.1f}" x2="{cx+10*s:.1f}" y2="{cy+10*s:.1f}" '
                   f'stroke="{color}" stroke-width="{2.6*s:.1f}" stroke-linecap="round"/>')

    elif k in ("target", "aim", "focus"):
        for rr in (10.5, 6.5, 2.5):
            out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{rr*s:.1f}" '
                       f'fill="{"none" if rr > 3 else color}" stroke="{color}" stroke-width="{1.5*s:.1f}"/>')

    elif k in ("shield", "immune", "immunity", "protection"):
        out.append(f'<path d="M {cx:.1f},{cy-10*s:.1f} L {cx+9*s:.1f},{cy-6*s:.1f} '
                   f'V {cy+1*s:.1f} C {cx+9*s:.1f},{cy+7*s:.1f} {cx:.1f},{cy+11*s:.1f} {cx:.1f},{cy+11*s:.1f} '
                   f'C {cx:.1f},{cy+11*s:.1f} {cx-9*s:.1f},{cy+7*s:.1f} {cx-9*s:.1f},{cy+1*s:.1f} '
                   f'V {cy-6*s:.1f} Z" fill="{color}" fill-opacity="0.18" '
                   f'stroke="{color}" stroke-width="{1.6*s:.1f}"/>')

    elif k in ("check", "outcome", "success", "impact"):
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{10.5*s:.1f}" '
                   f'fill="{color}" fill-opacity="0.16" stroke="{color}" stroke-width="{1.6*s:.1f}"/>')
        out.append(f'<path d="M {cx-5*s:.1f},{cy:.1f} L {cx-1.5*s:.1f},{cy+4*s:.1f} '
                   f'L {cx+5.5*s:.1f},{cy-4.5*s:.1f}" fill="none" stroke="{color}" '
                   f'stroke-width="{2.2*s:.1f}" stroke-linecap="round"/>')

    elif k in ("warning", "problem", "resistance", "block"):
        out.append(f'<polygon points="{cx:.1f},{cy-10*s:.1f} {cx+10.5*s:.1f},{cy+9*s:.1f} '
                   f'{cx-10.5*s:.1f},{cy+9*s:.1f}" fill="{color}" fill-opacity="0.18" '
                   f'stroke="{color}" stroke-width="{1.6*s:.1f}"/>')
        out.append(f'<line x1="{cx:.1f}" y1="{cy-4*s:.1f}" x2="{cx:.1f}" y2="{cy+3*s:.1f}" '
                   f'stroke="{color}" stroke-width="{2.0*s:.1f}" stroke-linecap="round"/>')
        out.append(f'<circle cx="{cx:.1f}" cy="{cy+6.2*s:.1f}" r="{1.3*s:.1f}" fill="{color}"/>')

    elif k in ("tcell", "immune_cell", "macrophage", "lymphocyte"):
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{9.5*s:.1f}" '
                   f'fill="{color}" fill-opacity="0.16" stroke="{color}" stroke-width="{1.6*s:.1f}"/>')
        out.append(f'<circle cx="{cx-2.2*s:.1f}" cy="{cy:.1f}" r="{4.2*s:.1f}" '
                   f'fill="{color}" fill-opacity="0.45"/>')
        out.append(f'<circle cx="{cx+2.6*s:.1f}" cy="{cy-1.2*s:.1f}" r="{3.2*s:.1f}" '
                   f'fill="{color}" fill-opacity="0.45"/>')
        for ang in (30, 150, 270):
            rad = math.radians(ang)
            out.append(f'<line x1="{cx+math.cos(rad)*9.5*s:.1f}" y1="{cy+math.sin(rad)*9.5*s:.1f}" '
                       f'x2="{cx+math.cos(rad)*12.5*s:.1f}" y2="{cy+math.sin(rad)*12.5*s:.1f}" '
                       f'stroke="{color}" stroke-width="{1.5*s:.1f}"/>')

    elif k in ("mouse", "vivo", "animal", "model_organism"):
        out.append(f'<ellipse cx="{cx-1*s:.1f}" cy="{cy+2*s:.1f}" rx="{8.5*s:.1f}" ry="{5.5*s:.1f}" '
                   f'fill="{color}" fill-opacity="0.22" stroke="{color}" stroke-width="{1.5*s:.1f}"/>')
        out.append(f'<circle cx="{cx+6*s:.1f}" cy="{cy-3.5*s:.1f}" r="{3.2*s:.1f}" '
                   f'fill="{color}" fill-opacity="0.32" stroke="{color}" stroke-width="{1.3*s:.1f}"/>')
        out.append(f'<circle cx="{cx+8.2*s:.1f}" cy="{cy+1.2*s:.1f}" r="{1.4*s:.1f}" fill="{color}"/>')
        out.append(f'<path d="M {cx-9.5*s:.1f},{cy+2*s:.1f} Q {cx-12.5*s:.1f},{cy-2*s:.1f} {cx-9.5*s:.1f},{cy-5.5*s:.1f}" '
                   f'fill="none" stroke="{color}" stroke-width="{1.3*s:.1f}" stroke-linecap="round"/>')

    elif k in ("patient", "cohort", "clinical", "human"):
        out.append(f'<circle cx="{cx:.1f}" cy="{cy-5.5*s:.1f}" r="{3.8*s:.1f}" '
                   f'fill="{color}" fill-opacity="0.26" stroke="{color}" stroke-width="{1.5*s:.1f}"/>')
        out.append(f'<path d="M {cx-7.5*s:.1f},{cy+9*s:.1f} C {cx-7.5*s:.1f},{cy+1.5*s:.1f} '
                   f'{cx+7.5*s:.1f},{cy+1.5*s:.1f} {cx+7.5*s:.1f},{cy+9*s:.1f}" '
                   f'fill="{color}" fill-opacity="0.22" stroke="{color}" stroke-width="{1.5*s:.1f}"/>')

    elif k in ("virus", "phage", "pathogen"):
        pts = " ".join(f"{cx+math.cos(math.radians(60*i))*7.5*s:.1f},{cy+math.sin(math.radians(60*i))*7.5*s:.1f}"
                       for i in range(6))
        out.append(f'<polygon points="{pts}" fill="{color}" fill-opacity="0.22" '
                   f'stroke="{color}" stroke-width="{1.5*s:.1f}"/>')
        for i in range(6):
            rad = math.radians(60 * i)
            x1, y1 = cx + math.cos(rad) * 7.5 * s, cy + math.sin(rad) * 7.5 * s
            x2, y2 = cx + math.cos(rad) * 11.2 * s, cy + math.sin(rad) * 11.2 * s
            out.append(f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
                       f'stroke="{color}" stroke-width="{1.3*s:.1f}"/>')
            out.append(f'<circle cx="{x2:.1f}" cy="{y2:.1f}" r="{1.6*s:.1f}" fill="#D55E00"/>')

    elif k in ("crispr", "cas9", "knockout", "edit"):
        out.append(f'<line x1="{cx-10*s:.1f}" y1="{cy-3.5*s:.1f}" x2="{cx-1.5*s:.1f}" y2="{cy-3.5*s:.1f}" '
                   f'stroke="{color}" stroke-width="{1.9*s:.1f}"/>')
        out.append(f'<line x1="{cx+1.5*s:.1f}" y1="{cy-3.5*s:.1f}" x2="{cx+10*s:.1f}" y2="{cy-3.5*s:.1f}" '
                   f'stroke="{color}" stroke-width="{1.9*s:.1f}"/>')
        out.append(f'<line x1="{cx-10*s:.1f}" y1="{cy+3.5*s:.1f}" x2="{cx-1.5*s:.1f}" y2="{cy+3.5*s:.1f}" '
                   f'stroke="{color}" stroke-width="{1.9*s:.1f}"/>')
        out.append(f'<line x1="{cx+1.5*s:.1f}" y1="{cy+3.5*s:.1f}" x2="{cx+10*s:.1f}" y2="{cy+3.5*s:.1f}" '
                   f'stroke="{color}" stroke-width="{1.9*s:.1f}"/>')
        out.append(f'<path d="M {cx-3.5*s:.1f},{cy-9.5*s:.1f} L {cx+3.5*s:.1f},{cy+9.5*s:.1f} '
                   f'M {cx+3.5*s:.1f},{cy-9.5*s:.1f} L {cx-3.5*s:.1f},{cy+9.5*s:.1f}" '
                   f'stroke="#DC2626" stroke-width="{1.6*s:.1f}" stroke-linecap="round"/>')

    elif k in ("neuron", "brain", "neural"):
        out.append(f'<circle cx="{cx-3*s:.1f}" cy="{cy:.1f}" r="{5.0*s:.1f}" '
                   f'fill="{color}" fill-opacity="0.24" stroke="{color}" stroke-width="{1.6*s:.1f}"/>')
        out.append(f'<line x1="{cx+2*s:.1f}" y1="{cy:.1f}" x2="{cx+11*s:.1f}" y2="{cy:.1f}" '
                   f'stroke="{color}" stroke-width="{1.8*s:.1f}"/>')
        for ang in (135, 180, 225):
            rad = math.radians(ang)
            out.append(f'<line x1="{cx-3*s+math.cos(rad)*5*s:.1f}" y1="{cy+math.sin(rad)*5*s:.1f}" '
                       f'x2="{cx-3*s+math.cos(rad)*10.5*s:.1f}" y2="{cy+math.sin(rad)*10.5*s:.1f}" '
                       f'stroke="{color}" stroke-width="{1.3*s:.1f}"/>')

    else:
        # Clean generic scientific node badge
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{8.5*s:.1f}" '
                   f'fill="{color}" fill-opacity="0.18" stroke="{color}" stroke-width="{1.6*s:.1f}"/>')
        out.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{3.2*s:.1f}" fill="{color}"/>')

    out.append("</g>")
    return "".join(out)


AVAILABLE_ICONS = [
    "cell", "nucleus", "membrane", "receptor", "antibody", "nanobody", "drug",
    "dna", "rna", "protein", "nanoparticle", "vesicle", "microbe", "tumor",
    "organoid", "mitochondria", "molecule", "catalyst", "electrode", "device",
    "flask", "microscope", "target", "shield", "tcell", "mouse", "patient",
    "virus", "crispr", "neuron", "check", "warning",
]
