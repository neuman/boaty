# SPDX-License-Identifier: Apache-2.0
"""boaty's own gates: the seven claims no installed pack covers.

Gate ids are PROJECT-scoped (`boat.*`), never domain-scoped. A bare domain id
collides with any pack shipping the same domain, and two gates cannot share an id
-- verdicts, claim coverage and `--only` all key on it.

Every gate here reads `ctx.params` and recomputes nothing geometric. A gate that
re-derives hull geometry is a second source of truth and the two will disagree
(rule 2).

Why these seven exist, one line each:

  boat.trim           fluids-analytic states in its own PACK.md that it cannot do
                      trim, and that this is "the nearest omission of all, and the
                      easiest to miss precisely because three hydrostatic gates go
                      green next to it". On this boat trim costs 3.8 mm of the
                      lowest deck-edge freeboard, which is 15% of the claim.
  boat.free_surface   fluid.metacentric reports SOLID GM and says it does not know
                      your tanks exist. A hull with bilge water has less.
  boat.swamped        reserve buoyancy that communicates with a flooded space is
                      not reserve. No pack asks which volumes are sealed.
  boat.empty          the battery is the heaviest low item, so removing it RAISES
                      KG. The empty hull can be the least stable one, and it is the
                      condition the boat is in every time it is carried to the water.
  boat.driveline      a shaft line is not a solid until someone has committed to
                      where it goes, so cad.clash cannot see a prop that fouls the
                      rudder or a stuffing tube that exits through the topsides.
  boat.wall_agreement two independent routes to one number: the wall the model
                      SPECIFIES, and the wall implied by the generated mesh's own
                      volume and area. This is the gate that found the real bug in
                      this project -- see its docstring.
  boat.envelope       cad.bounding cannot run here: it reads `bbox_mm`, and so does
                      fdm-print for the part it is judging, and one projection
                      cannot mean two things by one key. See FRICTION.md.
"""
from __future__ import annotations

from atompipe.gates import gate, GateContext
from atompipe.models import NegativeControl, Tier, Verdict


def _p(ctx, key):
    v = ctx.params.get(key)
    if v is None:
        raise KeyError(f"model projection has no {key!r}")
    return v


@gate(
    id="boat.trim",
    title="The boat floats level enough that the freeboard figure means something",
    claims=["trim", "longitudinal-stability"],
    tier=Tier.INSTANT,
    settles="trim angle and the freeboard that survives it",
    negative_control=NegativeControl(
        fixture="selftest/bad_boat.py:battery_aft",
        note="the 98 g battery moved to the aft end of the equipment bay -- one "
             "plausible cable-routing decision, nothing else changed. It is the "
             "exact move the fluids lens list warns about ('the battery that gets "
             "relocated for cable routing')",
    ),
)
def trim(ctx: GateContext) -> Verdict:
    """Trim angle from the two-unknown flotation solve, and the freeboard left after it.

    Both halves matter and the second is the point. `fluid.freeboard` reports the
    LEVEL figure; this reports what is left once the hull has trimmed to put its
    centre of buoyancy under its centre of gravity, which is the condition the boat
    is actually in.
    """
    deg = abs(float(_p(ctx, "trim_deg")))
    lim = float(_p(ctx, "max_trim_deg"))
    fb = float(_p(ctx, "trimmed_freeboard_mm"))
    fb_lim = float(ctx.params["config"]["min_freeboard_limit_mm"])
    lost = float(_p(ctx, "freeboard_lost_to_trim_mm"))
    ok = deg <= lim and fb >= fb_lim and bool(_p(ctx, "trim_balanced"))
    return Verdict(
        gate="boat.trim", passed=ok, measured=round(deg, 3), limit=lim, units="deg",
        detail=(f"trim {float(_p(ctx,'trim_deg')):+.2f} deg "
                f"({float(_p(ctx,'trim_mm')):+.1f} mm bow-to-stern) vs {lim:.2f} limit; "
                f"freeboard {fb:.1f} mm after trim vs {fb_lim:.0f} mm required "
                f"(level flotation would have reported {float(_p(ctx,'level_freeboard_mm')):.1f} mm, "
                f"so trim costs {lost:.1f} mm); LCG {float(_p(ctx,'lcg_mm')):.1f} vs "
                f"LCB {float(_p(ctx,'lcb_mm')):.1f} mm"),
    )


@gate(
    id="boat.free_surface",
    title="GM survives a bilge with water free to move in it",
    claims=["free-surface"],
    tier=Tier.INSTANT,
    settles="GM after free-surface correction",
    negative_control=NegativeControl(
        fixture="selftest/bad_boat.py:top_heavy",
        note="mass added on deck, SOLVED for the value that misses this gate's own "
             "stated acceptance by 1.15x rather than typed -- a control calibrated "
             "to a literal stops being a control the moment the threshold moves. "
             "A mast or a light bar is the most common thing added to a finished boat "
             "and it always goes up, which is the lens-4 failure exactly",
    ),
)
def free_surface(ctx: GateContext) -> Verdict:
    """Solid GM minus i/V for the bilge, where i is the free surface's own inertia.

    i = sum over cells of L*b^3/12. The width is CUBED, which is the whole reason
    the equipment bay has a longitudinal centre girder and not just transverse
    bulkheads: a longitudinal division cuts b, a transverse one only cuts L.
    """
    gmf = float(_p(ctx, "gm_free_surface_mm"))
    lim = float(ctx.params["config"]["min_gm_free_surface_mm"])
    return Verdict(
        gate="boat.free_surface", passed=gmf >= lim, measured=round(gmf, 2),
        limit=lim, units="mm",
        detail=(f"GM {float(_p(ctx,'gm_mm')):.1f} mm solid, minus "
                f"{float(_p(ctx,'free_surface_correction_mm')):.1f} mm of free surface "
                f"= {gmf:.1f} mm vs {lim:.0f} mm; the girder divides the bilge into "
                f"{float(_p(ctx,'bilge_cell_width_mm')):.0f} mm cells -- undivided the "
                f"correction would be {float(_p(ctx,'free_surface_undivided_mm')):.1f} mm"),
    )


@gate(
    id="boat.swamped",
    title="The sealed end compartments float the boat with the equipment bay flooded",
    claims=["swamped", "reserve-buoyancy-sealed"],
    tier=Tier.INSTANT,
    settles="flooded-condition buoyancy margin",
    negative_control=NegativeControl(
        fixture="selftest/bad_boat.py:one_big_bay",
        note="bulkheads pushed out to 25 mm and 455 mm, which is the obvious move if "
             "you want the biggest possible equipment bay and have not thought about "
             "flooding. Nothing else changes; the hull, the mass and the loading are "
             "identical",
    ),
)
def swamped(ctx: GateContext) -> Verdict:
    """Sealed buoyancy minus all-up mass.

    The flood water itself is neutrally buoyant once the bay is open to the pond, so
    it does not have to be lifted; what has to be lifted is the boat. Volume that
    communicates with the flooded space is not reserve, which is why this counts only
    the two sealed compartments and not the hull's total moulded volume.
    """
    m = float(_p(ctx, "swamped_margin_g"))
    return Verdict(
        gate="boat.swamped", passed=m >= 0.0, measured=round(m, 1), limit=0.0, units="g",
        detail=(f"sealed compartments support {float(_p(ctx,'sealed_buoyancy_g')):.0f} g "
                f"against an all-up {float(_p(ctx,'all_up_mass_g')):.0f} g -> "
                f"{m:+.0f} g margin with the equipment bay full. Foam-filled, so the "
                f"reserve fails gracefully rather than closed-loop"),
    )


@gate(
    id="boat.empty",
    title="Upright and stable in the EMPTY condition, not only at design load",
    claims=["loading-cases"],
    tier=Tier.INSTANT,
    settles="empty-condition metacentric height",
    negative_control=NegativeControl(
        fixture="selftest/bad_boat.py:top_heavy_empty",
        note="same solved topside mass as boat.free_surface's control, which raises "
             "KG in the condition where KG is already highest because the battery -- "
             "the heaviest low item -- has been taken out",
    ),
)
def empty(ctx: GateContext) -> Verdict:
    """GM with the battery out.

    Taking out the heaviest item in the bilge RAISES the centre of gravity, so the
    empty boat can be the least stable one. It is also the condition the boat is in
    every time it is carried to the water and put down before the pack goes in.
    """
    gm = float(_p(ctx, "empty_gm_mm"))
    lim = float(ctx.params["config"]["min_gm_free_surface_mm"])
    return Verdict(
        gate="boat.empty", passed=gm >= lim, measured=round(gm, 2), limit=lim, units="mm",
        detail=(f"empty GM {gm:.1f} mm (KG {float(_p(ctx,'kg_empty_mm')):.1f} mm vs "
                f"{float(_p(ctx,'kg_mm')):.1f} loaded) at "
                f"{float(_p(ctx,'empty_draft_mm')):.1f} mm draft, vs {lim:.0f} mm"),
    )


@gate(
    id="boat.driveline",
    title="Shaft, propeller and rudder are geometrically compatible with the hull",
    claims=["driveline"],
    tier=Tier.INSTANT,
    settles="driveline geometry violations",
    negative_control=NegativeControl(
        fixture="selftest/bad_boat.py:steep_shaft",
        note="shaft angle raised to 22 degrees, which is what you reach for when the "
             "motor will not clear the hull floor. It is past what a flexible coupler "
             "will take and it drags the propeller down into the rudder",
    ),
)
def driveline(ctx: GateContext) -> Verdict:
    """Four things cad.clash cannot see, because a shaft line is not a solid.

    The classic first-boat mistakes, in order of how often they happen: the stuffing
    tube drawn on a line that leaves through the topsides instead of the bottom; the
    propeller disc intersecting the hull it is supposed to sit behind; the rudder in
    the propeller's wash by 3 mm instead of 12; and a shaft angle a universal joint
    will not take.
    """
    v = []
    if not bool(_p(ctx, "shaft_exits_through_bottom")):
        v.append("shaft does not leave through the hull bottom")
    tip = float(_p(ctx, "prop_to_hull_clearance_mm"))
    tip_lim = float(_p(ctx, "min_prop_tip_clearance_mm"))
    if tip < tip_lim:
        v.append(f"propeller-to-hull clearance {tip:.1f} < {tip_lim:.0f} mm")
    gap = float(_p(ctx, "prop_to_rudder_gap_mm"))
    gap_lim = float(_p(ctx, "min_prop_rudder_gap_mm"))
    if gap < gap_lim:
        v.append(f"propeller-to-rudder gap {gap:.1f} < {gap_lim:.0f} mm")
    ang = float(_p(ctx, "shaft_angle_deg"))
    ang_lim = float(_p(ctx, "max_shaft_angle_deg"))
    if ang > ang_lim:
        v.append(f"shaft angle {ang:.1f} > {ang_lim:.0f} deg")
    return Verdict(
        gate="boat.driveline", passed=not v, measured=len(v), limit=0, units="violations",
        detail=("; ".join(v) if v else
                f"shaft exits the bottom at x={float(_p(ctx,'shaft_exit_x_mm')):.0f} mm at "
                f"{ang:.1f} deg; prop clears the hull by {tip:.1f} mm and leads the "
                f"rudder by {gap:.1f} mm; prop tip sits "
                f"{-float(_p(ctx,'prop_tip_z_mm')):.1f} mm below the keel"),
    )


@gate(
    id="boat.wall_agreement",
    title="The generated mesh's wall is the wall the model specified",
    claims=["mesh-agreement"],
    tier=Tier.INSTANT,
    settles="generated wall thickness vs specified",
    negative_control=NegativeControl(
        fixture="selftest/bad_boat.py:bugged_offset",
        note="the inner offset scaled to half, simulating exactly the class of "
             "generator bug this project actually hit. The meshes stay watertight and "
             "stay valid volumes, which is the point: every other geometry gate "
             "passes a mesh with the wrong wall",
    ),
)
def wall_agreement(ctx: GateContext) -> Verdict:
    """Two independent routes to one number, compared (rule 6).

    Route one: `wall_mm`, which the model states. Route two: 2V/A on the generated
    shell, where V and A come out of trimesh and know nothing about the model.

    THIS GATE FOUND THE REAL BUG IN THIS PROJECT. The traced section came out of the
    screenshot non-monotone -- half-beam wobbling by a factor of five between
    adjacent depths -- so the inward offset folded over itself at the turn of bilge.
    The folded wall polygon enclosed 501 mm2 where the ribbon was really 869, which
    made every printed part 40% light and ran every hydrostatic integral on a
    corrugated hull. It was invisible to everything else: the meshes were watertight,
    cad.is_volume passed, cad.degenerate_faces passed, the masses looked plausible
    and the boat floated on paper. Nothing that checks a mesh against ITSELF could
    have caught it.

    Tolerance is 15% and it is one-sided in spirit: the bow segment reads low because
    it carries the solid nose, whose volume is not wall.
    """
    meas = _p(ctx, "shell_wall_measured_mm")
    spec = float(_p(ctx, "shell_wall_spec_mm"))
    tol = 0.15
    worst_k, worst_e = None, 0.0
    for k, v in meas.items():
        e = abs(float(v) - spec) / spec
        if e > worst_e:
            worst_k, worst_e = k, e
    return Verdict(
        gate="boat.wall_agreement", passed=worst_e <= tol,
        measured=round(worst_e, 4), limit=tol, units="fraction",
        detail=(f"worst disagreement {worst_e*100:.1f}% on {worst_k} "
                f"({float(meas[worst_k]):.3f} mm from mesh volume/area vs {spec:.2f} mm "
                f"specified); all shells: "
                + ", ".join(f"{k} {float(v):.3f}" for k, v in sorted(meas.items()))),
    )


@gate(
    id="boat.envelope",
    title="The assembled boat fits the stated envelope",
    claims=["envelope", "packaging"],
    tier=Tier.INSTANT,
    settles="assembled bounding box",
    negative_control=NegativeControl(
        fixture="selftest/bad_boat.py:oversize_hull",
        note="hull_scale 3.0, i.e. a 900 mm boat. Also the units-slip control: a "
             "model that has silently gone metres-for-millimetres somewhere fails "
             "here loudly instead of exporting a plausible STL nobody measures",
    ),
)
def envelope(ctx: GateContext) -> Verdict:
    """Assembled bounding box against the car-boot limit.

    This duplicates what cad.bounding would do, and it exists because cad.bounding
    CANNOT run in this project: it reads `bbox_mm`, and fdm-print reads the same key
    for the single part it is judging. One projection cannot mean the whole boat and
    one printed part by one key, and fdm.bed_fit is the more valuable of the two, so
    it keeps the key. Recorded in FRICTION.md rather than hidden here.
    """
    box = [float(v) for v in _p(ctx, "assembly_bbox_mm")]
    lim = [float(v) for v in _p(ctx, "bbox_limit_mm")]
    util = max(b / l for b, l in zip(box, lim))
    return Verdict(
        gate="boat.envelope", passed=util <= 1.0, measured=round(util, 3),
        limit=1.0, units="fraction",
        detail=("assembled " + " x ".join(f"{b:.0f}" for b in box) + " mm vs "
                + " x ".join(f"{l:.0f}" for l in lim) + " mm envelope "
                f"(worst axis {util*100:.0f}%)"),
    )
