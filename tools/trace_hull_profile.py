"""Trace the hull curves out of the design-tool screenshot.

EXTRACTION tool, not a generator. Input: the ingested evidence
(inputs/screenshots/hull-profile.png). Output: inputs/data/hull_offsets.json --
the only thing model/boat.py is allowed to be grounded on for hull shape.

Why pixel-trace instead of just using the three toolbar numbers: LOA 300, draft 8.14
and WL beam 76.24 are three scalars, and a hull needs a shape. The panels carry that
shape at ~0.23 mm/px.

WHICH PANEL IS WHICH (this was got wrong once, hence the note):
  top-left    = PLAN, half-breadths measured from a centreline dashed at y=798 px.
                purple = sheer/deck half-breadth, light blue = DWL half-breadth.
  bottom-left = PROFILE, side elevation. light blue = DWL (dead horizontal,
                y=1547 px, which is how you can tell the two panels apart),
                dark teal = keel, orange = sheer.
  bottom-right= CUT, one section at x=150 mm. centreline vertical at x=2850 px,
                sheer dashed at y=1313 px, WL dashed at y=1462 px.

CALIBRATION is over-determined on purpose, so it can be checked rather than trusted:
  CUT     y-scale <- reported draft 8.14 mm == (keel_y - WL_y) px
  CUT     x-scale <- reported WL beam 76.24 mm == 2*(CL_x - section@WL_x) px
          ...those two must agree, because the panel is plotted isotropically.
  PLAN/PROFILE scale <- hull x-extent == LOA 300 mm
          ...and that must agree with the CUT scale, ditto.
If they disagree by more than TOL_REL the script refuses to write the file.
A tracer that emits a plausible hull from a mis-identified panel is worse than none.
"""
import json, os, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(HERE, "inputs", "screenshots", "hull-profile.png")
OUT = os.path.join(HERE, "inputs", "data", "hull_offsets.json")

PLAN_BOX = (50, 220, 1570, 1090)
PROF_BOX = (50, 1100, 1570, 1690)
CUT_BOX = (2380, 1180, 3170, 1730)

REPORTED = {"loa_mm": 300.0, "cut_x_mm": 150.0, "cut_draft_mm": 8.14, "cut_wl_beam_mm": 76.24}
TOL_REL = 0.08  # 8% between independent scale estimates; the panels are ~1300 px
                # wide and the curves are 4-5 px thick, so ~0.4% per curve, but the
                # hull end-points are genuinely fuzzy (round stem, control dots).


def band(a, box, rgb, tol, ywin=None):
    """Per-column median y of pixels within tol of rgb. ywin clips contamination
    (labels, control-point dots) that shares the curve's colour."""
    x0, y0, x1, y1 = box
    sub = a[y0:y1, x0:x1].astype(float)
    d = np.sqrt(((sub - np.array(rgb, float)) ** 2).sum(axis=2))
    hit = d < tol
    if ywin:
        lo, hi = ywin
        mask = np.zeros(hit.shape[0], bool)
        mask[max(0, lo - y0):max(0, hi - y0)] = True
        hit &= mask[:, None]
    out = {}
    for c in range(hit.shape[1]):
        ys = np.nonzero(hit[:, c])[0]
        if len(ys):
            out[c + x0] = float(np.median(ys) + y0)
    return out


def smooth(d, w=9):
    xs = np.array(sorted(d)); ys = np.array([d[x] for x in xs])
    k = np.ones(w) / w
    pad = w // 2
    yp = np.concatenate([np.full(pad, ys[0]), ys, np.full(pad, ys[-1])])
    return xs, np.convolve(yp, k, mode="valid")


def main():
    a = np.asarray(Image.open(SRC).convert("RGB"))
    rep = {}

    # ---------- CUT panel: the section shape, and the tightest calibration ----
    CL_X, SHEER_Y, WL_Y = 2850.0, 1313.0, 1462.0
    sec = band(a, CUT_BOX, (150, 150, 175), 45, ywin=(1320, 1520))
    sx, sy = smooth(sec, 5)
    keel_y = float(np.max(sy))
    cut_mm_per_px_y = REPORTED["cut_draft_mm"] / (keel_y - WL_Y)
    # half-beam at the waterline: where the section crosses WL_Y
    i = int(np.argmin(np.abs(sy - WL_Y)))
    half_px = CL_X - sx[i]
    cut_mm_per_px_x = (REPORTED["cut_wl_beam_mm"] / 2.0) / half_px
    rep["cut_scale_y_mm_per_px"] = cut_mm_per_px_y
    rep["cut_scale_x_mm_per_px"] = cut_mm_per_px_x

    # section as (half_breadth_mm, depth_below_sheer_mm), keel-first
    sect = []
    for x, y in zip(sx, sy):
        b = (CL_X - x) * cut_mm_per_px_x
        z = (y - SHEER_Y) * cut_mm_per_px_y
        if b >= -0.5:
            sect.append((max(0.0, b), z))
    sect.sort(key=lambda p: p[0])
    rep["section_depth_mm"] = (keel_y - SHEER_Y) * cut_mm_per_px_y
    rep["section_half_beam_sheer_mm"] = max(b for b, _ in sect)
    rep["section_freeboard_at_dwl_mm"] = (WL_Y - SHEER_Y) * cut_mm_per_px_y

    # ---------- PLAN panel: half-breadths ------------------------------------
    CLY = 798.0
    sheer_hb = band(a, PLAN_BOX, (110, 60, 230), 46, ywin=(400, 800))
    dwl_hb = band(a, PLAN_BOX, (100, 178, 224), 46, ywin=(560, 800))
    # bow = where the DWL half-breadth reaches the centreline
    dx, dy = smooth(dwl_hb, 9)
    bow_px = float(dx[np.argmax(dy > CLY - 4.0)]) if (dy > CLY - 4.0).any() else float(dx[-1])

    # ---------- PROFILE panel: keel and sheer in elevation -------------------
    DWL_Y = 1547.0
    keel = band(a, PROF_BOX, (48, 104, 100), 46)
    sheer_el = band(a, PROF_BOX, (196, 100, 50), 46, ywin=(1355, 1520))
    kx, ky = smooth(keel, 9)
    # transom = first column where the keel curve exists; stem = last
    transom_px, stem_px = float(kx[0]), float(kx[-1])
    prof_mm_per_px = REPORTED["loa_mm"] / (stem_px - transom_px)
    rep["profile_scale_mm_per_px"] = prof_mm_per_px

    # ---------- agreement check (rule 6) -------------------------------------
    scales = [cut_mm_per_px_y, cut_mm_per_px_x, prof_mm_per_px]
    spread = (max(scales) - min(scales)) / np.mean(scales)
    rep["scale_spread_rel"] = float(spread)
    print("scale estimates mm/px:")
    print(f"  CUT  y (from draft 8.14)      {cut_mm_per_px_y:.4f}")
    print(f"  CUT  x (from WL beam 76.24)   {cut_mm_per_px_x:.4f}")
    print(f"  PROFILE (from LOA 300)        {prof_mm_per_px:.4f}")
    print(f"  relative spread               {spread*100:.2f}%  (tol {TOL_REL*100:.0f}%)")
    if spread > TOL_REL:
        print("REFUSING to write: the three independent scale estimates disagree. "
              "Either a panel is mis-identified or a curve trace is contaminated.",
              file=sys.stderr)
        sys.exit(2)

    # ---------- longitudinal stations ----------------------------------------
    def to_x_mm(px, origin, scale):
        return (px - origin) * scale

    stations = []
    for xm in np.linspace(0, REPORTED["loa_mm"], 31):
        px_prof = transom_px + xm / prof_mm_per_px
        # plan panel has its own origin; anchor it on the bow it reports
        px_plan = bow_px - (REPORTED["loa_mm"] - xm) / prof_mm_per_px
        def at(d, p, default=None):
            if not d: return default
            ks = np.array(sorted(d)); vs = np.array([d[k] for k in ks])
            if p < ks[0] or p > ks[-1]: return default
            return float(np.interp(p, ks, vs))
        ky_ = at(dict(zip(kx, ky)), px_prof)
        sy_ = at(sheer_el, px_prof)
        db = at(dict(zip(dx, dy)), px_plan)
        sb = at(sheer_hb, px_plan)
        stations.append({
            "x_mm": round(float(xm), 2),
            "keel_below_dwl_mm": None if ky_ is None else round((ky_ - DWL_Y) * prof_mm_per_px, 3),
            "sheer_above_dwl_mm": None if sy_ is None else round((DWL_Y - sy_) * prof_mm_per_px, 3),
            "dwl_half_beam_mm": None if db is None else round((CLY - db) * prof_mm_per_px, 3),
            "sheer_half_beam_mm": None if sb is None else round((CLY - sb) * prof_mm_per_px, 3),
        })

    doc = {
        "source": "inputs/screenshots/hull-profile.png",
        "traced_by": "tools/trace_hull_profile.py",
        "reported_by_tool": REPORTED,
        "calibration": rep,
        "note": ("x_mm measured from the transom, +ve forward. keel_below_dwl_mm and "
                 "sheer_above_dwl_mm are relative to the DWL the tool drew, which is "
                 "the tool's slider position, NOT a loading condition. Everything here "
                 "is a pixel trace of a screenshot: treat it as +/-1 mm, not as CAD."),
        "section_at_x150": [{"half_beam_mm": round(b, 3), "below_sheer_mm": round(z, 3)}
                            for b, z in sect],
        "stations": stations,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(doc, open(OUT, "w"), indent=1)
    print("\nwrote", OUT)
    print(f"  hull depth at x=150      {rep['section_depth_mm']:.1f} mm")
    print(f"  half-beam at sheer       {rep['section_half_beam_sheer_mm']:.1f} mm")
    print(f"  freeboard at drawn DWL   {rep['section_freeboard_at_dwl_mm']:.1f} mm")
    ok = [s for s in stations if s["dwl_half_beam_mm"] is not None]
    print(f"  max DWL half-beam        {max(s['dwl_half_beam_mm'] for s in ok):.1f} mm")
    ok2 = [s for s in stations if s["keel_below_dwl_mm"] is not None]
    print(f"  max keel below DWL       {max(s['keel_below_dwl_mm'] for s in ok2):.2f} mm")


if __name__ == "__main__":
    main()
