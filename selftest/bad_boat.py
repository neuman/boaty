# SPDX-License-Identifier: Apache-2.0
"""Known-bad fixtures for boaty's own gates.

Each returns a GateContext whose params come from the model REBUILT with one
physically meaningful change, in the direction the gate under test cares about.
That constraint is the whole point: a fixture that is bad in some other way -- a
corrupt file, a missing key, an empty mesh -- proves the gate survives garbage, not
that it measures what it claims.

Two of these SOLVE for the value that misses the acceptance rather than typing one.
A control calibrated to a literal stops being a control the moment somebody relaxes
the threshold, and nothing says so.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

_MODEL = str(Path(__file__).resolve().parent.parent / "model")
if _MODEL not in sys.path:
    sys.path.insert(0, _MODEL)

import boat  # noqa: E402

_FIELDS = {f.name for f in dataclasses.fields(boat.Config)}


def _cfg(ctx, **overrides):
    base = (ctx.params.get("config", {}) or {}) if getattr(ctx, "params", None) else {}
    kw = {k: v for k, v in base.items() if k in _FIELDS}
    kw["write_meshes"] = False
    kw.update(overrides)
    return boat.Config(**kw)


def _with(ctx, **overrides):
    return dataclasses.replace(ctx, params=boat.build(_cfg(ctx, **overrides)))


# --------------------------------------------------------------------------- #
def battery_aft(ctx):
    """boat.trim -- the battery relocated to the aft end of the equipment bay.

    One decision, the kind that gets made for cable routing, with nothing else
    touched. The fluids lens list names it: "the battery that gets relocated for
    cable routing" is a KG and LCG change nobody re-runs the gate for.
    """
    base = _cfg(ctx)
    place = {k: list(v) for k, v in base.place.items()}
    place["battery"] = [base.bulkhead_aft_x + 42.0, 0.0, None]
    return _with(ctx, place=place)


def steep_shaft(ctx):
    """boat.driveline -- 22 degrees of shaft angle.

    What you reach for when the motor will not clear the hull floor. Past what a
    universal joint will take, and it drags the propeller down and aft into the
    rudder.
    """
    return _with(ctx, shaft_angle_deg=22.0)


def bugged_offset(ctx):
    """boat.wall_agreement -- the inner offset at half the specified wall.

    Simulates the generator bug this project actually hit. The meshes stay
    watertight and stay valid positive volumes, so cad.watertight, cad.is_volume and
    cad.degenerate_faces all still pass: that is exactly why this gate exists.
    """
    return _with(ctx, mesh_wall_scale=0.5)


def one_big_bay(ctx):
    """boat.swamped -- bulkheads pushed out to the ends.

    The obvious move if you want the roomiest possible equipment bay and have not
    thought about flooding. Hull, mass and loading are untouched; only the volume
    that stays sealed changes.
    """
    loa = _cfg(ctx).loa_mm
    return _with(ctx, bulkhead_aft_x=25.0, bulkhead_fwd_x=loa - 25.0,
                 hatch_x0=60.0, hatch_x1=loa - 60.0)


def oversize_hull(ctx):
    """boat.envelope -- hull_scale 3.0, a 900 mm boat.

    Doubles as the units-slip control: a model that has silently gone
    metres-for-millimetres somewhere fails here loudly instead of exporting a
    plausible STL that nobody measures.
    """
    return _with(ctx, hull_scale=3.0)


# --------------------------------------------------------------------------- #
# The two solved controls.
#
# This hull has BM = 91 mm and GM = 72 mm. No plausible rearrangement of a 98 g
# battery inside a 190 mm bay makes a stability gate fail, so a fixture that moved
# things around would be a control that cannot control. Mass ON THE DECK is the
# lever that works, and it is not fiction -- it is the single most common thing
# added to a finished boat, and the fluids lens list is blunt that additions go up.
#
# The value is SOLVED for, not typed: bisection on topside mass until the gate's
# own measured quantity misses the acceptance THE MODEL STATES by 1.15x. Relax the
# threshold later and the control moves with it.
# --------------------------------------------------------------------------- #
_MISS = 1.15


def _solve_topside(ctx, read, limit_key, empty=False):
    base = _cfg(ctx)
    target = getattr(base, limit_key) / _MISS
    lo, hi = 0.0, 20000.0
    for _ in range(34):
        mid = 0.5 * (lo + hi)
        try:
            r = boat.build(_cfg(ctx, topside_mass_g=mid))
            val = float(r[read])
        except Exception:
            hi = mid
            continue
        if val > target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def top_heavy(ctx):
    """boat.free_surface -- topside mass solved until free-surface GM misses by 1.15x."""
    m = _solve_topside(ctx, "gm_free_surface_mm", "min_gm_free_surface_mm")
    return _with(ctx, topside_mass_g=m)


def top_heavy_empty(ctx):
    """boat.empty -- the same solved mass, in the condition where KG is already highest."""
    m = _solve_topside(ctx, "empty_gm_mm", "min_gm_free_surface_mm")
    return _with(ctx, topside_mass_g=m)


def bed_overflow(ctx):
    """boat.bed_fit_all -- hull_scale 2.2, a 660 mm boat.

    Distinct from oversize_hull (3.0) so the two gates' controls cannot be satisfied
    by one accident. At 2.2 the mid segment's footprint passes 208 mm and nothing
    else about the design is obviously absurd, which is the point: the fixture has to
    be a boat somebody could have drawn.
    """
    return _with(ctx, hull_scale=2.2)


def pushrod_low(ctx):
    """boat.hull_penetrations -- the pushrod run dropped to 18 mm above the keel.

    A straighter line from the servo horn to the tiller, and exactly the reason
    somebody would do it. At 18 mm it is below the loaded waterline, so the guide tube
    where it leaves the transom becomes a second hole under water. Nothing else about
    the boat changes.
    """
    return _with(ctx, pushrod_z_mm=18.0)
