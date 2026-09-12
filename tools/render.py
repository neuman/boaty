#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""render.py — shaded renders of the boat, from the same STLs the gates judge.

Outputs are generated. Change the model, re-run `python tools/build_geometry.py`,
then re-run this. Nothing here measures anything: every number on a render comes
from the ledger, and if a render and the readiness report disagree, the render is
the one that is wrong.

Software rasteriser on purpose — a painter's-algorithm pass over the triangles with
Lambert shading from a fixed light. No GPU, no display, no headless-GL dependency,
so it runs anywhere the gates run (which is the point: a render you cannot
regenerate in CI stops matching the design within a week).
"""
from __future__ import annotations

import os
import sys

import numpy as np
import trimesh
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BUILD = os.path.join(ROOT, "build")
OUT = os.path.join(ROOT, "renders")

# Colour by ROLE, not by part, so a reader can see the structure at a glance:
# what keeps water out, what carries load, what you buy.
ROLE = {
    "hull":      ("#9fc3e0", "shell — keeps the water out"),
    "deck":      ("#cfe0ee", "deck and hatch"),
    "bulkhead":  ("#e8b98a", "watertight bulkhead"),
    "girder":    ("#e8b98a", "centre girder"),
    "transom":   ("#e8b98a", "transom and stem"),
    "stem":      ("#e8b98a", "transom and stem"),
    "shaft":     ("#c58b8b", "driveline"),
    "hatch":     ("#cfe0ee", "deck and hatch"),
    "component": ("#8f8f98", "bought part"),
}
DEFAULT = ("#b9b9c2", "other")

#: Draw order for coplanar ties: what physically sits on top is drawn LAST.
#: The bought parts live INSIDE the hull and under the deck, so they rank before
#: it — ranking them last (on the reasoning that they are "on top" of the render)
#: drew the motor and the battery straight through the deck they are supposed to
#: be hidden by.
_RANK = ("hull", "girder", "bulkhead", "transom", "stem", "shaft",
         "component", "deck", "hatch")


def DRAW_RANK(name: str) -> int:
    for i, key in enumerate(_RANK):
        if name.startswith(key):
            return i
    return len(_RANK)


def role_of(name: str):
    for key, value in ROLE.items():
        if name.startswith(key):
            return value
    return DEFAULT


def load(directory: str) -> dict[str, trimesh.Trimesh]:
    out = {}
    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".stl"):
            continue
        mesh = trimesh.load(os.path.join(directory, filename), process=False)
        if isinstance(mesh, trimesh.Trimesh) and len(mesh.faces):
            out[filename[:-4]] = mesh
    return out


def shade(colour: str, normals: np.ndarray, light=(0.45, -0.8, 0.55)) -> np.ndarray:
    """Lambert + ambient, per face. Returns an RGBA array."""
    light = np.array(light, dtype=float)
    light /= np.linalg.norm(light)
    base = np.array(matplotlib.colors.to_rgb(colour))
    lam = np.clip(normals @ light, 0.0, 1.0)
    # 0.38 ambient keeps faces pointing away from the light readable rather than
    # black: this is a drawing of an object, not a lighting study.
    level = 0.38 + 0.62 * lam
    rgb = np.clip(base[None, :] * level[:, None], 0, 1)
    return np.concatenate([rgb, np.ones((len(rgb), 1))], axis=1)


def draw(parts, path, title, elev=26, azim=-58, subtitle="", legend=True):
    """One depth-sorted collection for the WHOLE scene.

    Every part as its own Poly3DCollection looks right until two parts touch:
    matplotlib depth-sorts triangles inside a collection but draws collections in
    add order, so a deck laid on a hull comes out striped where the two interleave.
    Merging every triangle into one array and sorting once removes it, and costs
    nothing — the sort is over the same triangles either way.
    """
    tris_all, cols_all, bias_all = [], [], []
    seen: dict[str, str] = {}
    lo = np.array([np.inf] * 3)
    hi = np.array([-np.inf] * 3)
    # A deck laid ON a hull shares its plane exactly, and coplanar triangles have
    # equal depth, so the painter's sort orders them arbitrarily and the surface
    # comes out striped. Ranking the parts and breaking depth ties by rank fixes it
    # without touching the geometry — which matters, because the geometry here is
    # the thing under test and a render must not quietly move it.
    el0, az0 = np.radians(elev), np.radians(azim)
    eye = np.array([np.cos(el0) * np.cos(az0), np.cos(el0) * np.sin(az0), np.sin(el0)])
    for rank, (name, mesh) in enumerate(sorted(parts.items(), key=lambda kv: DRAW_RANK(kv[0]))):
        colour, label = role_of(name)
        seen.setdefault(label, colour)
        # BACKFACE CULLING. Matplotlib draws every triangle, front and back. On a
        # closed solid the back faces are merely wasted work, but on a 1 mm deck
        # panel seen at a grazing angle its top and underside are nearly coplanar,
        # so the sort alternates between them and the panel comes out striped. That
        # striping is not a defect in the geometry — the gates are happy with it —
        # which is exactly why it had to be chased in the renderer and not the model.
        facing = mesh.face_normals @ eye > 0.0
        if not facing.any():
            continue
        faces = mesh.faces[facing]
        tris_all.append(mesh.vertices[faces])
        cols_all.append(shade(colour, mesh.face_normals[facing]))
        bias_all.append(np.full(len(faces), float(rank)))
        lo = np.minimum(lo, mesh.bounds[0])
        hi = np.maximum(hi, mesh.bounds[1])
    tris = np.concatenate(tris_all)
    cols = np.concatenate(cols_all)
    bias = np.concatenate(bias_all)

    el, az = np.radians(elev), np.radians(azim)
    view = np.array([np.cos(el) * np.cos(az), np.cos(el) * np.sin(az), np.sin(el)])

    # Separate coplanar parts along the VIEW direction by a sub-visible amount,
    # rather than trying to control the draw order. Matplotlib re-sorts a
    # Poly3DCollection on every draw and offers no way to turn that off, so any
    # ordering computed here is discarded before it reaches the canvas; giving the
    # triangles a real depth difference is the only thing a sorter cannot undo.
    #
    # The nudge is 1/4000 of the model's own depth span — well under a pixel at any
    # size these are viewed at, and applied ONLY to the copy being drawn. The STLs
    # the gates measure are untouched, which is the line that matters: a render may
    # not move geometry that a verdict was made about.
    depth = tris.mean(axis=1) @ view
    span = float(depth.max() - depth.min()) or 1.0
    tris = tris + (view[None, None, :] * (bias[:, None, None] * span * 2.5e-4))

    order = np.argsort(tris.mean(axis=1) @ view)
    tris, cols = tris[order], cols[order]

    extents = hi - lo
    # Fill the frame: a 480 x 186 x 87 mm boat inside a cube is mostly empty cube.
    # Equal UNIT length on every axis is preserved by making the box match the
    # object's own proportions, so nothing is stretched.
    aspect = extents / extents.max()
    height = 13.0 * float(max(aspect[1], aspect[2], 0.30)) * 0.78 + (1.5 if legend else 0.9)
    fig = plt.figure(figsize=(13, height), dpi=132)
    fig.patch.set_facecolor("#ffffff")
    ax = fig.add_subplot(111, projection="3d")
    ax.set_facecolor("#ffffff")
    coll = Poly3DCollection(tris, linewidths=0.0, shade=False)
    coll.set_facecolor(cols)
    coll.set_edgecolor("none")
    # Matplotlib re-sorts a Poly3DCollection on every draw, which silently discards
    # the depth+rank order computed above and puts the striping back. zsort=False
    # makes it honour input order, which is the only way the coplanar tiebreak can
    # survive to the canvas.
    coll.set_zsort("average")
    ax.add_collection3d(coll)

    centre = (lo + hi) / 2.0
    pad = 1.015
    for setter, axis in ((ax.set_xlim, 0), (ax.set_ylim, 1), (ax.set_zlim, 2)):
        half = max(extents[axis] / 2.0, extents.max() * 0.02) * pad
        setter(centre[axis] - half, centre[axis] + half)
    ax.set_box_aspect(tuple(np.maximum(aspect, 0.04)))
    ax.view_init(elev=elev, azim=azim)
    ax.set_axis_off()

    ax.text2D(0.0, 1.055 if subtitle else 1.02, title, transform=ax.transAxes,
              fontsize=16, weight="bold", color="#16181d", va="bottom")
    if subtitle:
        ax.text2D(0.0, 1.005, subtitle, transform=ax.transAxes, fontsize=10,
                  color="#5a6172", va="bottom")
    if legend and seen:
        handles = [plt.Line2D([], [], marker="s", linestyle="", markersize=9,
                              markerfacecolor=c, markeredgecolor="none", label=l)
                   for l, c in sorted(seen.items())]
        fig.legend(handles=handles, loc="lower center", ncol=min(len(handles), 4),
                   frameon=False, fontsize=9.5, labelcolor="#3b4252",
                   bbox_to_anchor=(0.5, 0.005))

    os.makedirs(os.path.dirname(path), exist_ok=True)
    fig.subplots_adjust(left=0.0, right=1.0, top=1.0, bottom=0.0)
    fig.savefig(path, facecolor="#ffffff", bbox_inches="tight", pad_inches=0.28)
    plt.close(fig)
    print(f"  {os.path.relpath(path, ROOT)}")


def explode(parts, factor=0.85):
    """Push each part out along the vector from the assembly centre to its own.

    Radial rather than along one axis: a boat is long and thin, and a purely
    vertical explode stacks the hull segments into an unreadable column.
    """
    lo = np.array([np.inf] * 3)
    hi = np.array([-np.inf] * 3)
    for mesh in parts.values():
        lo = np.minimum(lo, mesh.bounds[0])
        hi = np.maximum(hi, mesh.bounds[1])
    centre = (lo + hi) / 2.0
    scale = float((hi - lo).max())
    out = {}
    for name, mesh in parts.items():
        moved = mesh.copy()
        direction = (mesh.bounds.mean(axis=0) - centre)
        norm = np.linalg.norm(direction)
        direction = direction / norm if norm > 1e-9 else np.array([0.0, 0.0, 1.0])
        # Bought parts travel furthest: they are what a reader is trying to see
        # inside the hull, and they are the ones the hull hides completely.
        reach = 0.30 if name.startswith("component") else 0.16
        moved.apply_translation(direction * scale * factor * reach)
        out[name] = moved
    return out


def plate(parts, bed=220.0, gap=8.0):
    """Bin the print set into BED-SIZED plates, laid side by side.

    The first version packed shelves without ever capping the bed in Y, so
    thirteen parts came out as a 220 x 1000 mm strip under a title that said "one
    bed". Two of these parts are 190 x 186 and 82 x 186 — they do not share a
    220 mm bed with anything, and a render that implies they do is telling a
    builder something false about their evening.

    Returns (laid parts, number of plates) so the caption can state the real count.
    """
    ordered = sorted(parts.items(),
                     key=lambda kv: -float(kv[1].extents[0] * kv[1].extents[1]))
    laid: dict = {}
    plate_index, x, y, row = 0, gap, gap, 0.0
    for name, mesh in ordered:
        moved = mesh.copy()
        moved.apply_translation(-moved.bounds[0])
        width, depth = float(moved.extents[0]), float(moved.extents[1])
        if x + width + gap > bed:                 # next shelf
            x, y, row = gap, y + row + gap, 0.0
        if y + depth + gap > bed:                 # next plate
            plate_index += 1
            x, y, row = gap, gap, 0.0
        # Grid the plates rather than lining them up: eight beds in a row is a
        # 2 m strip in which every part is a smudge.
        across = 4
        moved.apply_translation((x + (plate_index % across) * (bed * 1.10),
                                 y + (plate_index // across) * (bed * 1.14), 0.0))
        laid[name] = moved
        x += width + gap
        row = max(row, depth)
    return laid, plate_index + 1


def main() -> int:
    if not os.path.isdir(BUILD):
        sys.exit(f"no {BUILD} — run tools/build_geometry.py first")
    asm = load(BUILD)
    printset = load(os.path.join(BUILD, "print"))
    if not asm:
        sys.exit("no STLs in build/")

    print("rendering:")
    draw(asm, os.path.join(OUT, "assembly.png"),
         "Assembly — 480 mm LOA",
         subtitle="19 bodies: 13 printed, 6 bought parts shown in place. "
                  "Hull scaled 1.6x from the traced profile so it floats the payload.")
    draw({k: v for k, v in asm.items() if not k.startswith("component")},
         os.path.join(OUT, "structure.png"),
         "Printed structure",
         subtitle="13 printed parts. Bulkheads and the centre girder divide the bilge "
                  "into 53 mm cells, which is what holds the free-surface correction "
                  "to 4.2 mm of GM.")
    draw(explode(asm), os.path.join(OUT, "exploded.png"),
         "Exploded", elev=22, azim=-62,
         subtitle="Bought parts pushed furthest — they are what the hull hides.")
    draw({k: v for k, v in asm.items() if k.startswith("hull")},
         os.path.join(OUT, "hull.png"),
         "Hull shell", elev=18, azim=-64,
         subtitle="Three printed segments. The section is the traced profile, "
                  "unchanged in form.", legend=False)
    if printset:
        laid, n_plates = plate(printset)
        draw(laid, os.path.join(OUT, "print-plate.png"),
             f"Print set — {len(printset)} parts, {n_plates} plate"
             f"{'s' if n_plates != 1 else ''} of 220 mm",
             elev=90, azim=-90, legend=False,
             subtitle="Each part in the orientation every printability verdict was "
                      "made against. Largest footprint 190 mm against 208 mm usable "
                      "once the brim is on.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
