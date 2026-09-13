# SPDX-License-Identifier: Apache-2.0
"""The hull surface, rebuilt from the traced offsets.

This module owns ONE thing: given a scale, produce the hull's outer and inner
surfaces as section curves, and the integrals over them (volume, waterplane,
centroids). `boat.py` owns the design; `geometry.py` turns these curves into
meshes. Nothing here knows what a motor is.

Source of shape: inputs/data/hull_offsets.json, written by tools/trace_hull_profile.py
from the user's screenshot. THE SCREENSHOT IS THE ONLY SHAPE EVIDENCE THIS PROJECT
HAS. Everything in here is a +/-1.5 mm statement (claim A1), not a CAD statement.

Frame (and it is stated here because mixing datums is the error no arithmetic
catches -- see packs/fluids-analytic/PACK.md "Vertical datum"):

    x  mm, 0 at the TRANSOM, +ve forward to the bow at x = loa
    y  mm, 0 on the centreline, +ve to starboard
    z  mm, 0 at the LOWEST POINT OF THE KEEL, +ve up

Every draft, KG, KB and freeboard in this project is measured from that z=0. The
design tool's own DWL is NOT a datum here: it was a slider position, and the
hull floats where its mass says it floats.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
OFFSETS = os.path.join(os.path.dirname(_HERE), "inputs", "data", "hull_offsets.json")

#: Stations forward of this (in traced, unscaled mm) are dropped: the trace of the
#: stem at x=300 picks up the control-point dot at the bow and returns a keel
#: 19 mm ABOVE the sheer, which is not a hull. The bow is closed analytically
#: instead. Tried keeping it and clipping to physical bounds: that produced a
#: 1 mm wide sliver station and trimesh reported degenerate faces, which is
#: cad.degenerate_faces doing its job on a problem that belongs here.
_TRACE_X_MAX = 292.0

#: The traced sheer half-beam at x=150 is contaminated by the red station line the
#: design tool draws at exactly that x (it reads 44.7 mm between neighbours of 56.3
#: and 54.0). Interpolated out rather than trusted.
_CONTAMINATED_SHEER_X = (150.0,)


@lru_cache(maxsize=1)
def _raw() -> dict:
    with open(OFFSETS) as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def traced() -> dict:
    """Cleaned traced offsets, in TRACED (unscaled, LOA 300) millimetres.

    Returns arrays keyed x, sheer_half_beam, depth, keel_above_datum, and the
    normalised section shape (t, f) with t = depth below sheer / station depth
    and f = half-beam / sheer half-beam.
    """
    d = _raw()
    st = [s for s in d["stations"]
          if s["x_mm"] <= _TRACE_X_MAX
          and s["dwl_half_beam_mm"] is not None
          and s["sheer_half_beam_mm"] is not None]
    x = np.array([s["x_mm"] for s in st], float)
    shb = np.array([s["sheer_half_beam_mm"] for s in st], float)
    sad = np.array([s["sheer_above_dwl_mm"] for s in st], float)
    kbd = np.array([s["keel_below_dwl_mm"] for s in st], float)

    bad = np.isin(x, np.array(_CONTAMINATED_SHEER_X))
    if bad.any():
        shb[bad] = np.interp(x[bad], x[~bad], shb[~bad])

    depth = sad + kbd                      # sheer to keel at each station
    keel_above_datum = kbd.max() - kbd     # 0 at the deepest station

    # ---- normalised section, from the traced CUT at x=150 ----------------
    # HALF-BEAM IS THE INDEPENDENT VARIABLE HERE, and that is not a stylistic
    # choice. The CUT panel was traced column by column, so there is exactly one
    # depth per half-beam and that direction is well sampled. Sorting the same
    # points by DEPTH instead -- which is what the first version did -- puts
    # dozens of points into the few pixels of the turn of bilge, where the section
    # is nearly vertical, and pixel noise then scrambles their order.
    #
    # The result was a section shape that was not monotone: f(0.75)=0.14 sitting
    # between f(0.79)=0.77 and f(0.71)=0.83. A hull whose half-beam wobbles like
    # that has an inward offset that folds over itself, and the folded wall polygon
    # encloses 501 mm2 where the ribbon is really 869 mm2 -- so every printed part
    # was 40% light and every hydrostatic integral was run on a corrugated hull.
    #
    # Nothing caught it for a long time. The meshes were watertight, cad.is_volume
    # passed, the numbers all looked plausible. What caught it was comparing the
    # wall thickness derived from mesh volume and area against the wall thickness
    # the model specified -- two independent routes to one number, which is METHOD
    # rule 6, and which is now the boat.wall_agreement gate.
    sec = [(p["half_beam_mm"], p["below_sheer_mm"]) for p in d["section_at_x150"]]
    sec.sort(key=lambda p: p[0])                   # by HALF-BEAM, ascending
    b = np.array([p[0] for p in sec], float)
    z = np.array([p[1] for p in sec], float)
    b, idx = np.unique(b, return_index=True)
    z = z[idx]
    # Enforce the one thing physics guarantees for a hull with no tumblehome below
    # the sheer: as the section gets wider it gets shallower, monotonically.
    #
    # The direction of this accumulation matters and the wrong one is silent.
    # minimum.accumulate LEFT to right looks equivalent and is not: the trace's
    # first few points, at half-beams under 1 mm, are the sheer-label text and the
    # marker circle bleeding into the curve, and one of them reads 32 mm where the
    # keel is at 43 mm. A left-to-right running minimum latches onto that stray and
    # flattens 176 of 221 points to it -- which is precisely what happened, and the
    # symptom was a hull that was wall-sided to within 5% of its depth and then
    # fell off a cliff. Running the maximum in from the RIGHT takes z[i] = max(z[i:]),
    # which keeps the deep keel values, repairs the stray, and needs no threshold.
    z = np.maximum.accumulate(z[::-1])[::-1]
    t = z / z.max()
    f = b / b.max()
    # force the two ends exactly: sheer is full beam, keel is on the centreline
    t = np.concatenate([[0.0], t, [1.0]])
    f = np.concatenate([[1.0], f, [0.0]])
    o = np.argsort(t)
    return {"x": x, "sheer_half_beam": shb, "depth": depth,
            "keel_above_datum": keel_above_datum,
            "dwl_half_beam": np.array([s["dwl_half_beam_mm"] for s in st], float),
            "sheer_above_dwl": sad,
            "sec_t": t[o], "sec_f": f[o],
            "traced_loa": 300.0}


def section_f(t):
    """Half-beam fraction at depth fraction t below the sheer. t=0 sheer, t=1 keel."""
    d = traced()
    return np.interp(np.clip(np.asarray(t, float), 0.0, 1.0), d["sec_t"], d["sec_f"])


def stations(scale: float, loa: float, n: int = 61):
    """Resampled station geometry at the design scale.

    Returns x, sheer_half_beam, depth, keel_above_datum -- all mm, all in the
    frame above. The bow is closed analytically over the last stretch because the
    trace cannot see the stem (see _TRACE_X_MAX).
    """
    d = traced()
    tx = d["x"] * scale
    x = np.linspace(0.0, loa, n)
    shb = np.interp(x, tx, d["sheer_half_beam"] * scale)
    dep = np.interp(x, tx, d["depth"] * scale)
    kad = np.interp(x, tx, d["keel_above_datum"] * scale)

    # close the bow: beyond the last traced station taper the half-beam to zero and
    # run the keel up to the sheer, so the stem is a point rather than a blunt face.
    nose = x > tx[-1]
    if nose.any():
        u = (x[nose] - tx[-1]) / max(loa - tx[-1], 1e-9)      # 0..1
        shb[nose] = shb[~nose][-1] * (1.0 - u) ** 0.7
        kad[nose] = kad[~nose][-1] + (dep[~nose][-1]) * u ** 1.6
        dep[nose] = dep[~nose][-1] * (1.0 - u ** 1.6)
    shb = np.maximum(shb, 0.0)
    dep = np.maximum(dep, 0.0)
    return x, shb, dep, kad


def deck_z(scale: float, loa: float, n: int = 241) -> float:
    """Height of the FLAT deck above the keel datum: the highest point the traced
    sheer reaches anywhere, so the deck is a plane and the topsides are carried up
    to it with a vertical strake wherever the traced sheer is lower.

    Why flat rather than following the sheer: a deck panel that follows the sheer
    curve rises about 3 degrees from horizontal over a printed segment, and a
    3-degree ramp is not a gentle slope to a printer -- at 0.24 mm layers each layer
    overhangs the one below by 4.6 mm. It is unprintable flat, and printing it on
    edge just moves the curve. Flattening costs roughly 21 g of extra topside, ADDS
    freeboard everywhere the traced sheer was low (the transom, which is where this
    hull's sheer is lowest and where a stern-trimmed boat is deepest), and it is what
    the source screenshot's own profile panel draws as a dashed line labelled
    "flat deck".
    """
    _, _, dep, kad = stations(scale, loa, n)
    return float((kad + dep).max()) + 0.6


def extension_volume(scale: float, loa: float, n: int = 241) -> float:
    """Moulded volume of the vertical strake between the traced sheer and the flat
    deck, mm^3. Reserve buoyancy, entirely above any waterline in this project."""
    x, shb, dep, kad = stations(scale, loa, n)
    dz = np.maximum(deck_z(scale, loa, n) - (kad + dep), 0.0)
    return float(np.trapezoid(2.0 * shb * dz, x))


def section_points(half_beam: float, depth: float, keel_z: float, m: int = 24):
    """One section as (y, z) from keel to sheer, starboard side, m+1 points."""
    t = np.linspace(1.0, 0.0, m + 1)          # t=1 keel -> t=0 sheer
    y = half_beam * section_f(t)
    z = keel_z + depth * (1.0 - t)             # t=1 is the keel, so z = keel_z there
    return y, z


def offset_inward(y, z, t_wall: float, clamp: bool = True):
    """Offset a section curve inward by t_wall along its own 2D normal.

    Transverse only: the longitudinal component of the true surface normal is
    ignored. On a hull this slender (L/B = 2.6) the sections change slowly and the
    error is well under a tenth of a millimetre, but cad.wall_thickness measures
    the real mesh by ray casting, so if this ever stops being true the gate says so
    rather than this comment.
    """
    dy = np.gradient(y)
    dz = np.gradient(z)
    ln = np.hypot(dy, dz)
    ln[ln == 0] = 1.0
    # outward normal for a keel->sheer traverse on the starboard side is (+dz,-dy)
    nx, nz = dz / ln, -dy / ln
    yi = y - nx * t_wall
    zi = z - nz * t_wall
    if clamp:
        # Clamping keeps the mesh generator from emitting negative half-breadths at
        # the keel, where the true offset dips a hair past the centreline. It also
        # HIDES a collapsed section: where the hull gets narrower than 2*t_wall the
        # two sides cross over and the clamp turns that into a pair of coincident
        # points instead of an obvious negative number, so the sweep comes out
        # non-manifold with no boundary edges and no degenerate faces, which is
        # about the least diagnosable failure trimesh has. geometry._hollow_to
        # calls this with clamp=False precisely to see the crossover.
        yi = np.maximum(yi, 0.0)
    return yi, zi


def hydrostatics(scale: float, loa: float, draft: float, rho_kg_m3: float = 998.0,
                 n: int = 121, m: int = 60) -> dict:
    """Integrate the hull at a waterline `draft` mm above the keel datum.

    Everything here is a numerical integral over the SAME surface the meshes are
    built from -- there is no second analytic hull anywhere in this project
    (rule 2). Returns mm/g units; boat.py converts to SI for the pack gates.
    """
    x, shb, dep, kad = stations(scale, loa, n)
    area = np.zeros(n)       # immersed sectional area, mm^2
    hb_wl = np.zeros(n)      # half-beam at the waterline, mm
    vmom_z = np.zeros(n)     # first moment of immersed area about z=0
    for i in range(n):
        if dep[i] <= 0 or shb[i] <= 0:
            continue
        imm = draft - kad[i]                 # immersion at this station
        if imm <= 0:
            continue
        imm = min(imm, dep[i])
        zz = np.linspace(0.0, imm, m)        # up from this station's keel
        tt = (dep[i] - zz) / dep[i]
        bb = shb[i] * section_f(tt)
        area[i] = 2.0 * np.trapezoid(bb, zz)
        vmom_z[i] = 2.0 * np.trapezoid(bb * (zz + kad[i]), zz)
        hb_wl[i] = shb[i] * section_f((dep[i] - imm) / dep[i]) if imm < dep[i] else shb[i]

    vol = float(np.trapezoid(area, x))                        # mm^3
    awp = float(np.trapezoid(2.0 * hb_wl, x))                 # mm^2
    iwp = float(np.trapezoid((2.0 / 3.0) * hb_wl ** 3, x))    # mm^4, transverse
    kb = float(np.trapezoid(vmom_z, x) / vol) if vol > 0 else 0.0
    lcb = float(np.trapezoid(area * x, x) / vol) if vol > 0 else 0.0
    lcf = float(np.trapezoid(2.0 * hb_wl * x, x) / awp) if awp > 0 else 0.0
    # wetted surface: arc length of each immersed section (both sides), integrated
    # along the hull. Needed by fluid.drag, which wants a reference area -- note the
    # pack's Cd table is referenced to FRONTAL area, not this one, so this figure is
    # for the friction estimate and the report, not for the drag gate's input.
    girth = np.zeros(n)
    for i in range(n):
        if dep[i] <= 0 or area[i] <= 0:
            continue
        imm = min(draft - kad[i], dep[i])
        zz = np.linspace(0.0, imm, m)
        bb = shb[i] * section_f((dep[i] - zz) / dep[i])
        girth[i] = 2.0 * float(np.trapezoid(np.hypot(np.gradient(bb, zz), 1.0), zz))
    wetted = float(np.trapezoid(girth, x))

    return {
        "displaced_volume_mm3": vol,
        "displaced_mass_g": vol * rho_kg_m3 * 1e-6,
        "waterplane_area_mm2": awp,
        "waterplane_inertia_mm4": iwp,
        "kb_mm": kb, "lcb_mm": lcb, "lcf_mm": lcf,
        "wl_beam_mm": 2.0 * float(hb_wl.max()),
        "wetted_area_mm2": wetted,
        "midship_area_mm2": float(area.max()),
        # Freeboard is measured to the DECK EDGE, which on this boat is the flat deck
        # at deck_z, not to the traced sheer. The hull's topsides are carried up to
        # deck_z at every station by a vertical strake -- that is what makes the deck
        # flat and printable -- so the deck edge is at deck_z everywhere and the
        # traced sheer is an interior line with no water on the other side of it.
        #
        # Measuring to the sheer under-reported freeboard by about 20 mm on the 480 mm
        # boat: 31 mm against a true 50 mm. Conservative, and wrong, and it made the
        # freeboard claim look like the tightest margin on the boat when it is not
        # remotely. Caught while sweeping hull length for the one-piece study, because
        # two routes to the same number disagreed.
        "min_freeboard_mm": float(deck_z(scale, loa) - draft),
    }


def draft_for_mass(scale: float, loa: float, mass_g: float, rho_kg_m3: float = 998.0,
                   n: int = 121) -> float:
    """Solve for the waterline that displaces `mass_g`. Bisection, 40 steps."""
    _, _, dep, kad = stations(scale, loa, n)
    hi = float((kad + dep).max())
    lo = 0.0
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if hydrostatics(scale, loa, mid, rho_kg_m3, n=n, m=30)["displaced_mass_g"] < mass_g:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


if __name__ == "__main__":
    import sys
    sc = float(sys.argv[1]) if len(sys.argv) > 1 else 1.4
    loa = 300.0 * sc
    print(f"scale {sc}  LOA {loa:.0f} mm")
    x, shb, dep, kad = stations(sc, loa)
    print(f"  max deck beam {2*shb.max():.1f} mm   max depth {(kad+dep).max():.1f} mm")
    for T in (10, 15, 20, 25, 30):
        h = hydrostatics(sc, loa, T)
        print(f"  T={T:4.0f}  disp {h['displaced_mass_g']:7.1f} g  "
              f"Awp {h['waterplane_area_mm2']:8.0f}  BM {h['waterplane_inertia_mm4']/h['displaced_volume_mm3']:6.1f}  "
              f"KB {h['kb_mm']:5.1f}  LCB {h['lcb_mm']:6.1f}  fb {h['min_freeboard_mm']:5.1f}")


# --------------------------------------------------------------------------- #
# Trimmed flotation
#
# fluids-analytic says of itself, in PACK.md: "Trim and longitudinal stability.
# This is the nearest omission of all, and the easiest to miss precisely because
# three hydrostatic gates go green next to it. ... the draft is one uniform number,
# V/Awp -- which is to say the pack assumes the hull floats level. It does not
# balance LCG against LCB, it has no longitudinal GM, and it cannot tell you the
# trim angle. A hull trimmed by the head or stern has a lowest deck-edge freeboard
# materially below the single figure fluid.freeboard reports."
#
# So this is the closed-form answer to exactly that, done here rather than in the
# pack because it needs the hull's own station geometry. Two unknowns (the
# waterline's height and its slope), two equations (displacement equals mass,
# and the centre of buoyancy sits under the centre of gravity). Nested bisection,
# a few milliseconds, no solver.
# --------------------------------------------------------------------------- #
def _integrate_wl(scale, loa, wl_at, n=121, m=40, rho=998.0):
    """Integrate the hull under an arbitrary waterline wl_at(x).

    Vectorised over stations. The station-by-station Python loop this replaces was
    correct and cost 250,000 inner iterations per flotation solve, which put a
    single `atompipe check` at seventeen seconds. Rule 10: an inner loop that costs
    seventeen seconds is an inner loop nobody runs, and a design that is not
    re-checked on every edit is not validated.
    """
    x, shb, dep, kad = stations(scale, loa, n)
    wl = np.asarray([wl_at(xi) for xi in x], float) if callable(wl_at) else np.asarray(wl_at, float)
    live = (dep > 0) & (shb > 0)
    imm = np.clip(wl - kad, 0.0, None)
    imm = np.where(live, np.minimum(imm, dep), 0.0)

    u = np.linspace(0.0, 1.0, m)                      # 0 at the keel, 1 at the WL
    zz = imm[:, None] * u[None, :]                    # (n, m) height above each keel
    safe_dep = np.where(dep > 0, dep, 1.0)
    tt = (safe_dep[:, None] - zz) / safe_dep[:, None]
    bb = shb[:, None] * section_f(tt)
    bb = np.where((imm > 0)[:, None], bb, 0.0)

    area = 2.0 * np.trapezoid(bb, zz, axis=1)
    zmom = 2.0 * np.trapezoid(bb * (zz + kad[:, None]), zz, axis=1)
    hb = np.where(imm > 0, bb[:, -1], 0.0)

    vol = float(np.trapezoid(area, x))
    return {
        "x": x, "area": area, "hb": hb, "vol": vol,
        "mass_g": vol * rho * 1e-6,
        "lcb": float(np.trapezoid(area * x, x) / vol) if vol > 0 else 0.0,
        "kb": float(np.trapezoid(zmom, x) / vol) if vol > 0 else 0.0,
        "awp": float(np.trapezoid(2.0 * hb, x)),
        "iwp": float(np.trapezoid((2.0 / 3.0) * hb ** 3, x)),
        # To the DECK EDGE at deck_z, not to the traced sheer -- see hydrostatics().
        # With trim the waterline is a plane, so the least freeboard is at whichever
        # end is deepest, which is what max(wl) picks out.
        "freeboard": float(deck_z(scale, loa) - float(np.max(wl[live]))),
    }


def flotation(scale, loa, mass_g, lcg_mm, rho=998.0, n=121):
    """Solve for the waterline that both floats `mass_g` AND puts the centre of
    buoyancy under `lcg_mm`. Returns the trimmed condition.

    `trim_deg` is positive BOW DOWN; `trim_mm` is the difference in immersion between
    the bow and the transom, which is the number you can see on the boat.
    """
    x, _, dep, kad = stations(scale, loa, n)
    hmax = float((kad + dep).max())
    xc = x - loa / 2.0

    def solve_height(slope):
        lo, hi = -hmax, 2.0 * hmax
        for _ in range(34):
            mid = 0.5 * (lo + hi)
            r = _integrate_wl(scale, loa, mid + slope * xc, n=n, m=20, rho=rho)
            if r["mass_g"] < mass_g:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def lcb_err(slope):
        h = solve_height(slope)
        r = _integrate_wl(scale, loa, h + slope * xc, n=n, m=20, rho=rho)
        return r["lcb"] - lcg_mm, h

    # A POSITIVE slope raises the waterline forward, so the bow is less immersed and
    # buoyancy moves aft: lcb_err DECREASES as slope increases.
    lo, hi = -0.30, 0.30
    elo, _ = lcb_err(lo)
    ehi, _ = lcb_err(hi)
    if elo * ehi > 0:                      # cannot balance inside +/-17 degrees
        slope = lo if abs(elo) < abs(ehi) else hi
        balanced = False
    else:
        balanced = True
        for _ in range(28):
            mid = 0.5 * (lo + hi)
            em, _ = lcb_err(mid)
            if em * elo > 0:
                lo, elo = mid, em
            else:
                hi = mid
        slope = 0.5 * (lo + hi)
    h = solve_height(slope)
    r = _integrate_wl(scale, loa, h + slope * xc, n=n, m=40, rho=rho)
    r["trim_slope"] = slope
    r["trim_deg"] = float(np.degrees(np.arctan(slope)))
    r["trim_mm"] = float(slope * loa)
    r["balanced"] = balanced
    r["draft_transom_mm"] = float(h + slope * (0.0 - loa / 2.0))
    r["draft_mid_mm"] = float(h)
    r["wl_beam_mm"] = 2.0 * float(r["hb"].max())
    r["lcf"] = (float(np.trapezoid(2.0 * r["hb"] * r["x"], r["x"]) / r["awp"])
                if r["awp"] > 0 else 0.0)
    return r
