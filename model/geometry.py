# SPDX-License-Identifier: Apache-2.0
"""Meshes, generated from the hull form. Nothing here is hand-modelled.

Every part is a closed 2D polygon swept along an axis and capped, so
watertightness is a property of the construction rather than something to hope
for. cad.watertight still runs on the result, because "I built it carefully" is
not evidence (METHOD rule 4).

No boolean operations anywhere. Booleans in trimesh need manifold3d, a compiled
dependency that would make `atompipe check` fail to run on a machine that has
everything else -- and a boolean that silently returns an empty mesh is the classic
way a part disappears from an assembly while every gate stays green. Parts that
must fuse are emitted as separate closed bodies in one mesh, abutting on a face.
Slicers union those, trimesh reports each closed, and the volumes add correctly
because they abut rather than overlap.

PRINT ORIENTATION drives the decomposition, and it is worth stating why, because
the obvious decomposition does not print:

  - Keel-down: the hull bottom is near-flat and the keel has rocker, so all but one
    line of it is an unsupported near-horizontal overhang. Unprintable.
  - Deck-down: the bottom is now a near-flat roof at the top of the print. Same
    overhang, now at the top. Needs support over ~200x160 mm.
  - Split on the centreline: prints beautifully with zero support, and puts a
    400 mm glue seam along the keel -- underwater, and the single worst place on
    the boat to have a seam. Rejected on watertightness (claim P1).
  - STANDING ON A TRANSVERSE FACE, which is what this module does: the section
    changes slowly along x on a hull this slender, so every wall is within ~27
    degrees of vertical and nothing needs support. The cost is that a closed end
    would become a full-section bridge, so the ends are left OPEN and the transom
    and bulkheads are separate flat plates glued in. That is why the part count is
    what it is.

Frame: as model/hullform.py. x=0 transom, +x forward, z=0 at the lowest keel point.
"""
from __future__ import annotations

import numpy as np
import trimesh

from hullform import section_f, stations, offset_inward, deck_z


# --------------------------------------------------------------------------- #
# sweep primitives
# --------------------------------------------------------------------------- #
def _sweep(sections, close_start=True, close_end=True):
    """Sweep (x, poly) closed 2D polygons into a closed solid. poly is (N,2) of
    (y,z), the same N and the same winding at every section."""
    n = len(sections[0][1])
    verts = np.vstack([np.column_stack([np.full(n, x), p[:, 0], p[:, 1]])
                       for x, p in sections])
    faces = []
    for i in range(len(sections) - 1):
        a, b = i * n, (i + 1) * n
        for j in range(n):
            k = (j + 1) % n
            faces.append([a + j, a + k, b + k])
            faces.append([a + j, b + k, b + j])
    if close_start:
        faces += _cap(0, n, flip=True)
    if close_end:
        faces += _cap((len(sections) - 1) * n, n, flip=False)
    m = trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=True)
    m.fix_normals()
    return m


def _cap(base, n, flip):
    """Triangulate a closed polygon by pairing point j with point n-1-j.

    The second triangle is emitted ONLY when hi-1 and lo+1 are still distinct.
    Without that guard an ODD-length polygon closes with [k, k, k+1], a triangle
    with a repeated vertex. It cost an hour: the 98-point hull wall came out
    watertight and the 49-point bulkhead did not, from the same function, and the
    symptom was `is_watertight False` with ZERO degenerate faces reported, because
    trimesh's process=True had already merged the repeated vertex and left a hole
    where the triangle used to be.
    """
    out = []
    lo, hi = 0, n - 1
    while hi - lo >= 2:
        out.append([base + lo, base + lo + 1, base + hi])
        if hi - 1 > lo + 1:
            out.append([base + lo + 1, base + hi - 1, base + hi])
        lo += 1
        hi -= 1
    return [t[::-1] for t in out] if flip else out


# --------------------------------------------------------------------------- #
# hull sections
# --------------------------------------------------------------------------- #
#: Points used for the vertical strake between the traced sheer and the flat deck.
#: Four, not one: `offset_inward` takes its normals from np.gradient, and a single
#: point at the top of a curve gives the endpoint a one-sided gradient that blends
#: the vertical strake with the flared topside below it and offsets the deck edge
#: inboard by about half a millimetre.
_EXT_PTS = 4


def _half_section(hb, dep, kz, m, top_z=None):
    """Starboard half-section, keel first, optionally carried up to a flat deck."""
    t = np.linspace(1.0, 0.0, m + 1)                  # keel -> sheer
    y = hb * section_f(t)
    z = kz + dep * (1.0 - t)
    if top_z is not None:
        # ALWAYS extend, and always by the same number of points: _sweep needs every
        # section to carry the same vertex count, and near the bow the traced sheer
        # already sits at (or a hair above) the flat deck, so a conditional extension
        # gives 57 points at one station and 49 at the next.
        top = max(float(top_z), float(z[-1]) + 0.05)
        zex = np.linspace(z[-1], top, _EXT_PTS + 1)[1:]
        y = np.concatenate([y, np.full(_EXT_PTS, hb)])
        z = np.concatenate([z, zex])
    return y, z


def _outer_u(hb, dep, kz, m, top_z=None):
    """Outer section as a closed U: port sheer -> keel -> starboard sheer, closed
    across the top by the implicit last->first edge."""
    yo, zo = _half_section(hb, dep, kz, m, top_z)
    return (np.concatenate([-yo[::-1], yo[1:]]),
            np.concatenate([zo[::-1], zo[1:]]))


def _inner_u(hb, dep, kz, wall, m, extra=0.0, clamp=True, wall_scale=1.0, top_z=None):
    yo, zo = _half_section(hb, dep, kz, m, top_z)
    yi, zi = offset_inward(yo, zo, wall * wall_scale + extra, clamp=clamp)
    return (np.concatenate([-yi[::-1], yi[1:]]),
            np.concatenate([zi[::-1], zi[1:]]))


def wall_polygon(hb, dep, kz, wall, m, wall_scale=1.0, top_z=None):
    """The hull WALL cross-section: outer U out, inner U back."""
    oy, oz = _outer_u(hb, dep, kz, m, top_z)
    iy, iz = _inner_u(hb, dep, kz, wall, m, wall_scale=wall_scale, top_z=top_z)
    return np.column_stack([np.concatenate([oy, iy[::-1]]),
                            np.concatenate([oz, iz[::-1]])])


def solid_polygon(hb, dep, kz, m, top_z=None):
    oy, oz = _outer_u(hb, dep, kz, m, top_z)
    return np.column_stack([oy, oz])


def inner_polygon(hb, dep, kz, wall, m, extra=0.0, top_z=None):
    iy, iz = _inner_u(hb, dep, kz, wall, m, extra, top_z=top_z)
    return np.column_stack([iy, iz])


def _sampler(cfg):
    X, SHB, DEP, KAD = stations(cfg.hull_scale, cfg.loa_mm, 401)
    def at(x):
        return (max(float(np.interp(x, X, SHB)), 0.5),
                max(float(np.interp(x, X, DEP)), 1.0),
                float(np.interp(x, X, KAD)))
    return at


def _hollow_to(cfg, at, x0, x1):
    """Largest x in [x0,x1] where the inner cavity is still wider than the minimum
    printable feature. Past it the offset self-intersects and the mesh goes
    non-manifold, which is how the bow used to fail."""
    lo, hi = x0, x1
    def ok(x):
        hb, dep, kz = at(x)
        # UNCLAMPED: a clamped offset reports a healthy cavity for a section whose
        # two sides have already crossed the centreline. Every point except the one
        # at the keel must still be clear of the centreline by a printable margin.
        iy, iz = _inner_u(hb, dep, kz, cfg.wall_mm, cfg.section_points, clamp=False)
        m = cfg.section_points
        half = iy[m:]                       # keel -> sheer, starboard side
        # half[0] is the keel and is legitimately ~0; anything materially negative
        # anywhere means the two sides have crossed. The FIRST version of this test
        # read half.min() against a positive threshold, which the keel point fails
        # at every station, so x_solid collapsed to x0 and the bow came out as a
        # 200 cm3 lump of solid PETG. It was watertight and it was wrong, which is
        # the whole reason part volumes are in the report.
        return (half.min() > -0.2
                and half.max() > cfg.min_cavity_mm / 2.0
                and (iz.max() - iz.min()) > cfg.min_cavity_mm)
    if ok(hi):
        return hi
    if not ok(lo):
        return lo
    for _ in range(30):
        mid = 0.5 * (lo + hi)
        lo, hi = (mid, hi) if ok(mid) else (lo, mid)
    return lo


# --------------------------------------------------------------------------- #
# parts
# --------------------------------------------------------------------------- #
def hull_tube_end(cfg, x0, x1):
    """Where the hull tube actually stops: the last x whose cavity is still wider
    than min_cavity_mm. Published so boat.py can put the stem plate there."""
    return _hollow_to(cfg, _sampler(cfg), x0, x1)


def hull_tube(cfg, x0, x1, spigot_at=None):
    """One printed hull segment: an open-ended tube of wall thickness, printed
    standing on a transverse face. `spigot_at` ('start'/'end') adds a stepped
    ring that plugs into the neighbouring segment and locates the joint."""
    at = _sampler(cfg)
    m = cfg.section_points
    x_solid = _hollow_to(cfg, at, x0, x1)
    n = max(6, int((x_solid - x0) / cfg.mesh_dx_mm) + 1)
    dz = deck_z(cfg.hull_scale, cfg.loa_mm)
    secs = [(float(x), wall_polygon(*at(x), cfg.wall_mm, m,
                                    wall_scale=getattr(cfg, "mesh_wall_scale", 1.0),
                                    top_z=dz))
            for x in np.linspace(x0, x_solid, n)]
    parts = [_sweep(secs)]

    # NO SOLID NOSE. The hull stops where its cavity stops and is capped by a
    # separate flat stem plate, exactly the way the transom is capped.
    #
    # The nose was three separate fights and lost all of them. A hull that tapers to
    # a point gives cad.wall_thickness a 0.03 mm ray hit at the stem; printed
    # stem-up, the solid nose roofs over the end of the cavity and fdm.bridge_span
    # calls a 35 mm unsupported ceiling; printed stem-down, the taper hangs off the
    # print at 79 degrees and fdm.overhang calls 3.4% of the surface. Every fix for
    # one made another worse.
    #
    # A 480 mm hull whose stem is a 12 mm flat instead of a knife edge is visually
    # indistinguishable, loses about 1 cm3 of displacement 470 mm forward of nothing
    # that matters, and turns three failing gates into one more flat plate.
    _ = x1

    if spigot_at:
        xj = x0 if spigot_at == "start" else x1
        ls = cfg.spigot_mm
        e = cfg.body_overlap_mm
        xa, xb = (xj - ls, xj + e) if spigot_at == "start" else (xj - e, xj + ls)
        hb, dep, kz = at(xj)
        dzz = deck_z(cfg.hull_scale, cfg.loa_mm)
        outer = inner_polygon(hb, dep, kz, cfg.wall_mm, m,
                              extra=cfg.fit_clearance_mm, top_z=dzz)
        inner = inner_polygon(hb, dep, kz, cfg.wall_mm, m,
                              extra=cfg.fit_clearance_mm + cfg.spigot_wall_mm, top_z=dzz)
        ring = np.vstack([outer, inner[::-1]])
        parts.append(_sweep([(float(xa), ring), (float(xb), ring)]))
    return trimesh.util.concatenate(parts)


def plate(cfg, x, thickness, *, lip=0.0, lip_dir=1, section_x=None):
    """A transom or bulkhead plate: the inner section at x, extruded, with an
    optional locating lip that steps into the tube."""
    at = _sampler(cfg)
    m = cfg.section_points
    dz = deck_z(cfg.hull_scale, cfg.loa_mm)
    # The section is taken at `section_x`, which must be the SMALLEST section the
    # plate spans, not the one at its aft face. A plate is a constant section swept
    # along x while the hull is not: near the stem the half-beam changes about
    # 1.5 mm per millimetre of x, so a 2 mm plate sized at its aft face stands 3 mm
    # proud of the hull at its forward face. cad.clash found it as 47592 mm3 of
    # hull_bow/stem_plate interference, 72.7 mm deep.
    hb, dep, kz = at(section_x if section_x is not None else x)
    body = inner_polygon(hb, dep, kz, cfg.wall_mm, m, extra=cfg.fit_clearance_mm, top_z=dz)
    parts = [_sweep([(float(x), body), (float(x + thickness), body)])]
    if lip > 0:
        # A RING, not a slab. The first version extruded the whole inner section and
        # put 16 cm3 of solid PETG -- 20 g, 4% of the boat -- into what is a
        # locating rim. Caught by reading the part volumes, not by a gate.
        o = inner_polygon(hb, dep, kz, cfg.wall_mm, m,
                          extra=cfg.fit_clearance_mm + cfg.plate_lip_inset_mm, top_z=dz)
        i = inner_polygon(hb, dep, kz, cfg.wall_mm, m,
                          extra=cfg.fit_clearance_mm + cfg.plate_lip_inset_mm + cfg.lip_wall_mm,
                          top_z=dz)
        ring = np.vstack([o, i[::-1]])
        e = cfg.body_overlap_mm
        # lip_dir puts the locating rim on the side AWAY from the neighbouring hull
        # segment's spigot. With both pointing the same way they occupy one annulus
        # and cad.clash reported 19 cm3 of interference between bulkhead_aft and
        # hull_aft -- two parts that are supposed to slide together.
        if lip_dir >= 0:
            xa, xb = x + thickness - e, x + thickness + lip
        else:
            xa, xb = x - lip, x + e
        parts.append(_sweep([(float(xa), ring), (float(xb), ring)]))
    return trimesh.util.concatenate(parts)


def deck_panel(cfg, x0, x1, hatch=None, coaming=0.0):
    """Flat deck panel spanning the sheer, printed flat. `hatch` is
    (x_from, x_to, half_width); `coaming` raises a lip around the opening."""
    at = _sampler(cfg)
    dz = deck_z(cfg.hull_scale, cfg.loa_mm) + cfg.deck_gap_mm

    def z_sheer(x):
        # FLAT (see hullform.deck_z), and standing deck_gap_mm PROUD of the hull and
        # bulkhead tops rather than resting on them. That gap is a real epoxy bond
        # line, and it is also what stops the two faces being coplanar: a boolean
        # engine asked about two solids that share a face exactly returns nonsense,
        # and cad.clash reported 31277 mm3 of interference between bulkhead_fwd and
        # deck_mid -- two parts whose bounding boxes do not overlap on any axis --
        # with "inf mm equivalent depth over 0.00 mm^2", which is the engine saying
        # so if you read it.
        return dz

    def strip(a, b, y_lo, y_hi, top=None, drop=0.0):
        n = max(4, int((b - a) / cfg.mesh_dx_mm) + 1)
        secs = []
        for x in np.linspace(a, b, n):
            hb, _, _ = at(x)
            z = z_sheer(x)
            lo = -hb if y_lo is None else max(y_lo, -hb)
            hi = hb if y_hi is None else min(y_hi, hb)
            if hi - lo < 0.6:
                hi = lo + 0.6
            t = cfg.deck_mm if top is None else top
            secs.append((float(x), np.array([[lo, z - drop], [hi, z - drop],
                                             [hi, z + t], [lo, z + t]])))
        return _sweep(secs)

    if not hatch:
        return strip(x0, x1, None, None)
    hx0, hx1, hhw = hatch
    e = cfg.body_overlap_mm
    # EVERY sub-body overlaps its neighbour by `e` rather than abutting it exactly.
    # Face-coincident bodies survive in memory -- trimesh reported all of these
    # watertight -- and then STL, which has no vertex identity, welds the coincident
    # vertices on reload and the shared face becomes 68 non-manifold edges:
    #   cad.watertight: 120 bad edge(s) across 18 part(s) ... worst deck_mid:
    #   0 open, 68 non-manifold of 1104 faces; 18 part(s) welded at 0.0001 mm on load
    # An overlap has no shared vertices to weld, and a slicer unions it regardless.
    # The lap between deck sub-panels is a MILLIMETRES-scale overlap, not the
    # 0.08 mm body_overlap. At 0.08 mm the fore panel and the side rails overlapped
    # in a 0.16 mm slab and cad.wall_thickness cast a ray straight along it:
    #   thinnest wall 0.160 mm on deck_mid at (320.08, -64.802, 83.082)
    # The overlap has to be thicker than the minimum wall, because it IS a wall.
    lap = cfg.deck_lap_mm
    out = []
    # The fore and aft panels are stepped `deck_step_mm` clear of the rails in z.
    #
    # THIS DOES NOT FIX cad.wall_thickness, and the comment says so rather than
    # implying otherwise. Four of deck_mid's 1136 faces report a sub-millimetre
    # section, and all four are INTERNAL faces where two overlapping sub-bodies of
    # the same printed part meet -- a ray leaving one body's face immediately enters
    # the other body's face. Stepping in z moved the number from 0.000 to 0.003 and
    # 0.06; insetting in y moves it somewhere else. Any overlap of two closed bodies
    # produces internal faces, and a ray sampler cannot tell an internal face from a
    # void. The only real fix is one body, i.e. a boolean union -- attempted in
    # geometry.fuse and REJECTED BY ITS OWN GUARD, because the union's output does
    # not survive an STL round-trip. So the step stays because it is harmless and
    # documents the attempt, the gate stays red, and the readiness report says which
    # four faces and why. The 1st percentile of this part is 1.400 mm, which is the
    # specified deck thickness.
    st = cfg.deck_step_mm
    if hx0 > x0 + 1:
        out.append(strip(x0, hx0 + lap, None, None, top=cfg.deck_mm + st, drop=st))
    if x1 > hx1 + 1:
        out.append(strip(hx1 - lap, x1, None, None, top=cfg.deck_mm + st, drop=st))
    out.append(strip(hx0 - lap, hx1 + lap, None, -hhw))
    out.append(strip(hx0 - lap, hx1 + lap, hhw, None))
    if coaming > 0:
        w = cfg.coaming_w_mm
        # The side coamings run the FULL length including the corners, and the fore
        # and aft pieces cross them by a whole coaming width. Overlapping by only `e`
        # left a 0.08 mm sliver at each corner, and cad.wall_thickness found it:
        #   thinnest wall 0.080 mm on deck_mid at (320, -51.307, 84.415)
        out.append(strip(hx0 - w, hx1 + w, -hhw - w, -hhw + lap, top=cfg.deck_mm + coaming))
        out.append(strip(hx0 - w, hx1 + w, hhw - lap, hhw + w, top=cfg.deck_mm + coaming))
        # ...and the fore/aft pieces are a hair WIDER than the side pieces, so the
        # outboard faces are not coplanar either. Flush faces weld on STL load and
        # come back as non-manifold edges -- the same failure the hatch lip had,
        # reached from the opposite direction.
        # ...and the fore/aft pieces reach only to the MIDLINE of the side pieces, so
        # they overlap by half a coaming width and no face is flush or nearly flush.
        # Flush welds into non-manifold edges on STL load; a hair proud leaves an
        # 0.08 mm step that cad.wall_thickness casts a ray down. Half a width inside
        # is the only version that is neither.
        out.append(strip(hx0 - w, hx0 + e, -hhw - w / 2.0, hhw + w / 2.0, top=cfg.deck_mm + coaming))
        out.append(strip(hx1 - e, hx1 + w, -hhw - w / 2.0, hhw + w / 2.0, top=cfg.deck_mm + coaming))
    return trimesh.util.concatenate(out)


def fuse(bodies, name=""):
    """Union a list of overlapping bodies into ONE solid, CHECKED, or hand back the
    concatenation unchanged.

    This module builds parts out of separate closed bodies and, for a long time,
    avoided booleans entirely (see the header). That worked until the part count had
    to come down: a bulkhead printed integral with its hull segment has no bond line
    to fail, and watertightness is the top physical risk on the whole boat -- but an
    integral bulkhead emitted as a SEPARATE body inside the same STL is not integral,
    it is two bodies with an internal face between them, and cad.wall_thickness casts
    a ray along that face and measures nothing.

    So the boolean is used, and it is WRAPPED (rule 7), with three things learned the
    hard way:

    * **Union the ORIGINAL body list, not a re-split of their concatenation.**
      `trimesh.boolean.union(mesh.split(...))` and `union([a, b, c])` are not the same
      call: the first round-trips the geometry through concatenate/split first, and
      its output did not survive STL where the direct call's output did. Same engine,
      same inputs, different answer.
    * **The bodies have to genuinely OVERLAP.** Abutting bodies union to a no-op --
      same body count, same volume, and it looks like it worked. Every merged
      sub-body bites `merge_bite_mm` into its host on purpose.
    * **manifold3d is fast and wrong here.** It returns a watertight single body in
      milliseconds whose STL round-trip is not watertight. Blender takes two seconds
      and survives. The fast answer that fails the check is worse than no answer.

    The guard is the STL round-trip, because that is the artifact the gates read --
    checking the in-memory object was checking the wrong thing, which is the same
    mistake as judging a part in assembly coordinates. One watertight positive-volume
    body, volume within 25% of the inputs (overlaps mean a little smaller, never
    larger). Anything else and the caller gets the concatenation and the gates get to
    complain about the real thing rather than a silent substitution.
    """
    bodies = [b for b in bodies if b is not None and len(b.faces)]
    if len(bodies) == 1:
        return bodies[0]
    plain = trimesh.util.concatenate(bodies)
    if len(bodies) == 0:
        return plain
    before = float(plain.volume)
    try:
        u = trimesh.boolean.union(bodies, engine="blender")
    except Exception:
        return plain
    if u is None or len(u.faces) == 0:
        return plain
    try:
        # fill_holes ONLY. The obvious cleanup -- dropping degenerate faces and
        # re-merging vertices -- takes a union with 18 open edges and returns one
        # with 412, and takes hull_bow's union, which was already watertight, and
        # breaks it. Blender's output is nearly closed and very fragile; the least
        # that closes it is the most that should be done to it.
        trimesh.repair.fill_holes(u)
        rt = trimesh.load(trimesh.util.wrap_as_stream(u.export(file_type="stl")),
                          file_type="stl", process=True)
    except Exception:
        return plain
    # The guard has to be at least as strict as the gate, or it passes meshes the
    # gate then rejects. cad-solid does not just load the STL: it welds at 1e-4 mm
    # and drops faces under 1e-8 mm2 over two passes, and hull_aft came back from a
    # union that satisfied is_watertight with 2 non-manifold edges and 11 degenerate
    # faces once that ran. So the same normalisation runs here.
    if not (rt.is_watertight and rt.is_volume and rt.body_count == 1):
        return plain
    probe = rt.copy()
    keep = probe.nondegenerate_faces(height=1e-4)
    if not bool(keep.all()):
        return plain
    probe.merge_vertices(digits_vertex=4)
    if not (probe.is_watertight and probe.is_volume and probe.body_count == 1):
        return plain
    if not (0.70 * before <= float(rt.volume) <= 1.02 * before):
        return plain
    return u


def box(cx, cy, cz, lx, ly, lz):
    b = trimesh.creation.box(extents=(lx, ly, lz))
    b.apply_translation((cx, cy, cz))
    return b


def hatch_cover(cfg, hx0, hx1, hhw):
    """Lid for the equipment bay: a flat plate, one body, no downstand rails.

    The rails went. They located the lid in y, and they cost more than that was
    worth: they ran the full length of a constant-section sweep, so where the lid
    lands on the bulkhead tops they dipped into solid plate and cad.clash found
    119 mm3 of lid inside hull_bow. Shortening only the rails means a varying
    section, which means a second body, which means internal faces -- the thing this
    module keeps paying for.

    What locates the lid instead: the coaming it drops against on both sides, and
    four M3 screws. What seals it: closed-cell foam tape on the rim, compressed by
    those screws. Prusa's measured result is that O-rings and tapes seal and printed
    flexible gaskets do not; a printed rail was never the seal, only a guide.
    """
    at = _sampler(cfg)
    dz = deck_z(cfg.hull_scale, cfg.loa_mm) + cfg.deck_gap_mm
    z0 = dz + cfg.deck_mm + cfg.coaming_h_mm + cfg.gasket_mm
    W = hhw + cfg.coaming_w_mm + cfg.hatch_land_mm
    a = hx0 - cfg.hatch_land_mm
    b = hx1 + cfg.hatch_land_mm
    n = max(4, int((b - a) / cfg.mesh_dx_mm) + 1)
    secs = []
    for x in np.linspace(a, b, n):
        hb = max(at(x)[0] - cfg.merge_inset_mm, 0.8)
        w = min(W, hb)
        secs.append((float(x), np.array([[-w, z0], [w, z0],
                                         [w, z0 + cfg.hatch_mm], [-w, z0 + cfg.hatch_mm]])))
    return _sweep(secs)


def girder(cfg, x0, x1):
    """Longitudinal centre girder in the bilge. Its job is free surface (it halves
    the bilge width, which cubes down into i = L b^3 / 12), and it doubles as the
    keel stiffener. Limber holes are NOT modelled: they are drilled, because a
    printed 6 mm hole in a 2 mm web is a support nightmare and a drill is 4 seconds."""
    at = _sampler(cfg)
    n = max(4, int((x1 - x0) / cfg.mesh_dx_mm) + 1)
    secs = []
    for x in np.linspace(x0, x1, n):
        hb, dep, kz = at(x)
        iy, iz = _inner_u(hb, dep, kz, cfg.wall_mm, cfg.section_points)
        zfloor = iz.min()
        t = cfg.girder_t_mm / 2.0
        h = cfg.girder_h_mm
        secs.append((float(x), np.array([[-t, zfloor], [t, zfloor],
                                         [t, zfloor + h], [-t, zfloor + h]])))
    return _sweep(secs)


def shaft_block(cfg, spec):
    """Internal block the stuffing tube passes through, epoxied to the hull bottom.
    Emitted as a plain block on the shaft axis; the bore is drilled, for the same
    reason the limber holes are."""
    ax, az, ang = spec["exit_x_mm"], spec["exit_z_mm"], spec["angle_deg"]
    L = cfg.shaft_block_len_mm
    cx = ax + L * 0.5 * np.cos(np.radians(ang))
    cz = az + L * 0.5 * np.sin(np.radians(ang)) + cfg.shaft_block_h_mm * 0.5
    # AXIS-ALIGNED, not rotated onto the shaft line. Printed, a box tilted 8 degrees
    # has its whole underside as an unsupported 48 mm ceiling; fdm.bridge_span said
    # so. The bore is drilled at the shaft angle after printing, which is how the
    # stuffing tube gets bonded anyway -- the hole has to be reamed to suit the tube.
    return box(cx, 0.0, cz, L, cfg.shaft_block_w_mm, cfg.shaft_block_h_mm)


# --------------------------------------------------------------------------- #
# Integral features
#
# Everything below returns a body that deliberately BITES `cfg.merge_bite_mm` into
# the hull segment it belongs to, so that geometry.fuse has something to union.
# A feature that merely touches its host unions to a no-op.
# --------------------------------------------------------------------------- #
def integral_plate(cfg, x, thickness, section_x=None, top_extra=0.0):
    """A transom, stem or bulkhead, sized to bite into the hull wall.

    `top_extra` carries the plate above deck level, which is how the fore and aft
    coamings are made: they are the tops of the two bulkheads, so the hatch lands on
    a continuous rim without any part having to grow a cross-piece that its own
    print would have to bridge.
    """
    at = _sampler(cfg)
    dz = deck_z(cfg.hull_scale, cfg.loa_mm) + cfg.deck_mm + top_extra
    # Sized at the WIDEST station the plate spans, not at one end of it. The hull
    # changes half-beam along x, so a plate cut to its forward face is narrower than
    # the hull at its aft face -- by only 0.2 mm at the forward bulkhead, which was
    # still enough of a rim for cad.wall_thickness to cast a ray down and report a
    # 0.002 mm wall.
    if section_x is None:
        section_x = max((x, x + thickness), key=lambda xx: at(xx)[0])
    hb, dep, kz = at(section_x)
    # The plate covers the FULL section and stands `plate_proud_mm` past the hull's
    # outer skin -- it is not inset into the cavity. Two failures drove that:
    #   * inset by less than the wall, it leaves a rim of bare hull wall beside it,
    #     and a ray cast along that rim measures wall - bite, not the wall.
    #     cad.wall_thickness: 0.001 mm on hull_bow.
    #   * inset at all, the hull tube's end ring lands PARTLY on the plate and partly
    #     on nothing, which printed is an unsupported annulus all round the part.
    #     fdm.bridge_span: a 157 mm span on a 384 mm2 ceiling.
    # Standing proud fixes both and gives the joint a 0.3 mm register into the
    # bargain. Flush was not an option: it makes the plate's rim exactly coplanar
    # with the hull's outer skin, which STL welds into non-manifold edges.
    # Built from the hull's OUTER section pushed outward, not from the inner section
    # pushed back out. The two are not the same near the keel, where the inward
    # offset clamps at the centreline: run backwards from there, the plate stopped
    # about 1.6 mm short of the hull's outer skin along the flat of the bottom, so
    # the hull tube's end ring landed on nothing for a strip the width of the wall,
    # and fdm.bridge_span reported a 157 mm unsupported ceiling. Offsetting the outer
    # curve outward has no clamp in it and covers the section by construction.
    oy, oz = _half_section(hb, dep, kz, cfg.section_points, dz)
    py, pz = offset_inward(oy, oz, -cfg.plate_proud_mm, clamp=False)
    body = np.column_stack([np.concatenate([-py[::-1], py[1:]]),
                            np.concatenate([pz[::-1], pz[1:]])])
    return _sweep([(float(x), body), (float(x + thickness), body)])


def integral_deck(cfg, x0, x1, y_lo=None, y_hi=None, top_extra=0.0):
    """A deck slab that sinks into the sheer instead of floating above it.

    `y_lo`/`y_hi` cut it down to a side rail; `top_extra` raises it into a coaming.
    """
    at = _sampler(cfg)
    dz = deck_z(cfg.hull_scale, cfg.loa_mm)
    n = max(4, int((x1 - x0) / cfg.mesh_dx_mm) + 1)
    secs = []
    for x in np.linspace(x0, x1, n):
        hb = max(at(x)[0], 0.6)
        # The deck's outboard edge stops INSIDE the hull's outer skin. Flush with it
        # gives the boolean a pair of exactly coplanar vertical faces the full length
        # of the part, and its answer then is a single body that is not watertight.
        edge = max(hb - cfg.merge_inset_mm, 0.8)
        lo = -edge if y_lo is None else max(y_lo, -edge)
        hi = edge if y_hi is None else min(y_hi, edge)
        if hi - lo < 0.6:
            hi = lo + 0.6
        secs.append((float(x), np.array([[lo, dz - cfg.merge_bite_mm],
                                         [hi, dz - cfg.merge_bite_mm],
                                         [hi, dz + cfg.deck_mm + top_extra],
                                         [lo, dz + cfg.deck_mm + top_extra]])))
    return _sweep(secs)


def integral_girder(cfg, x0, x1):
    """Centre girder whose foot sinks into the hull floor.

    Limber holes are drilled, not printed: a 6 mm hole in a 2.4 mm web printed on
    its side is a support problem and a drill is four seconds.
    """
    at = _sampler(cfg)
    n = max(4, int((x1 - x0) / cfg.mesh_dx_mm) + 1)
    secs = []
    for x in np.linspace(x0, x1, n):
        hb, dep, kz = at(x)
        iy, iz = _inner_u(hb, dep, kz, cfg.wall_mm, cfg.section_points)
        zf = iz.min()
        t = cfg.girder_t_mm / 2.0
        secs.append((float(x), np.array([[-t, zf - cfg.merge_bite_mm],
                                         [t, zf - cfg.merge_bite_mm],
                                         [t, zf + cfg.girder_h_mm],
                                         [-t, zf + cfg.girder_h_mm]])))
    return _sweep(secs)


def integral_shaft_seat(cfg, spec, x_from=None):
    """The seat the stuffing tube is bonded through, grown UP OUT OF the hull floor
    rather than floated on the shaft axis.

    Floating it on the axis left its underside unsupported and put an unsupported
    ceiling in the print; sitting it on the floor also gives the tube a real bonded
    bearing length, which is what stops the one penetration below the waterline from
    working loose.
    """
    at = _sampler(cfg)
    ax, az, ang = spec["exit_x_mm"], spec["exit_z_mm"], spec["angle_deg"]
    L = cfg.shaft_block_len_mm
    x0 = ax if x_from is None else float(x_from)
    n = max(4, int((ax + L - x0) / cfg.mesh_dx_mm) + 1)
    secs = []
    for x in np.linspace(x0, ax + L, n):
        hb, dep, kz = at(x)
        iy, iz = _inner_u(hb, dep, kz, cfg.wall_mm, cfg.section_points)
        zf = iz.min() - cfg.merge_bite_mm
        ztop = az + (x - ax) * np.tan(np.radians(ang)) + cfg.shaft_block_h_mm / 2.0
        if ztop <= zf + 1.0:
            ztop = zf + 1.0
        # Clamped to the CAVITY, not to a constant. Near the transom this hull is
        # shallow and its section pinches hard at the turn of bilge, so a seat of
        # constant 18 mm width poked straight out through the topsides: a ray from
        # its own side face found the hull's inner surface 0.085 mm away. The seat
        # narrows to fit and widens as the hull does.
        half = iy[cfg.section_points:]          # keel -> sheer, starboard
        room = float(np.interp(ztop, iz[cfg.section_points:][::-1], half[::-1]))
        w = max(min(cfg.shaft_block_w_mm / 2.0, room - cfg.seat_side_clear_mm), 1.5)
        secs.append((float(x), np.array([[-w, zf], [w, zf], [w, ztop], [-w, ztop]])))
    return _sweep(secs)


def integral_coaming(cfg, x0, x1, y_lo, y_hi, boss_xs=(), boss_extra=0.0,
                     boss_half=7.0):
    """The raised lip around the hatch opening, sitting ON the deck rail.

    Deliberately NOT the same z range as the rail it stands on. The first version
    made the coaming a second slab over the same z band as the rail, with the same
    underside and a shared inboard face -- two coplanar pairs -- and the part came
    back not watertight after process() welded them. This one starts inside the
    rail's top surface and stops short of the rail's inboard edge, so it crosses the
    rail rather than lying against it.
    """
    at = _sampler(cfg)
    dz = deck_z(cfg.hull_scale, cfg.loa_mm)
    z0 = dz + cfg.deck_mm - cfg.merge_bite_mm
    z1 = dz + cfg.deck_mm + cfg.coaming_h_mm
    xs = sorted(set(list(np.linspace(x0, x1, max(4, int((x1 - x0) / cfg.mesh_dx_mm) + 1)))
                    + [bx + s * boss_half for bx in boss_xs for s in (-1.0, 1.0)]
                    + [bx + s * (boss_half + 4.0) for bx in boss_xs for s in (-1.0, 1.0)]))
    xs = [x for x in xs if x0 - 1e-9 <= x <= x1 + 1e-9]
    outboard = y_hi > 0
    secs = []
    for x in xs:
        hb = max(at(x)[0] - cfg.merge_inset_mm, 0.8)
        # Widened only where the hatch screws land. The coaming IS the boss, but it
        # does not have to be boss-width for all 186 mm of it to hold four screws.
        grow = 0.0
        if boss_xs and boss_extra:
            d = min(abs(x - bx) for bx in boss_xs)
            if d <= boss_half:
                grow = boss_extra
            elif d <= boss_half + 4.0:
                grow = boss_extra * (boss_half + 4.0 - d) / 4.0
        lo = max(y_lo - (grow if not outboard else 0.0), -hb)
        hi = min(y_hi + (grow if outboard else 0.0), hb)
        if hi - lo < 0.6:
            hi = lo + 0.6
        secs.append((float(x), np.array([[lo, z0], [hi, z0], [hi, z1], [lo, z1]])))
    return _sweep(secs)


# --------------------------------------------------------------------------- #
# Bought hardware, as solids.
#
# These are representative, not scale models of the vendors' parts: a propeller is
# a hub and three pitched blades, not an aerofoil. The point is that they OCCUPY
# SPACE. Until this existed the driveline was four numbers in boat.driveline, and
# cad.clash had never seen a propeller, a rudder or a stuffing tube -- so nothing
# had ever checked that the prop clears the hull it is drawn behind, or that a wire
# run does not lie across the shaft.
# --------------------------------------------------------------------------- #
def rod(p0, p1, d, sections=16):
    """A cylinder between two 3D points. The workhorse for shafts, tubes and wire."""
    p0 = np.asarray(p0, float)
    p1 = np.asarray(p1, float)
    v = p1 - p0
    L = float(np.linalg.norm(v))
    if L < 1e-6:
        L, v = 1e-3, np.array([0.0, 0.0, 1.0])
    m = trimesh.creation.cylinder(radius=d / 2.0, height=L, sections=sections)
    zaxis = np.array([0.0, 0.0, 1.0])
    u = v / L
    if np.allclose(u, zaxis):
        R = np.eye(4)
    elif np.allclose(u, -zaxis):
        R = trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0])
    else:
        axis = np.cross(zaxis, u)
        R = trimesh.transformations.rotation_matrix(
            float(np.arccos(np.clip(np.dot(zaxis, u), -1, 1))), axis)
    m.apply_transform(R)
    m.apply_translation((p0 + p1) / 2.0)
    return m


def polytube(points, d, sections=12):
    """A run of rod segments through a polyline, with a ball at each interior knot so
    the corners are closed. Used for wire runs and the pushrod."""
    pts = [np.asarray(p, float) for p in points]
    # Segments are EXTENDED past each interior knot so consecutive rods interpenetrate,
    # and there are no knot balls at all. A ball sized to the rod is tangent to it, and
    # a tangent pair welds on STL load into non-manifold edges -- hw_pushrod came back
    # "not closed", which then made cad.clash refuse to answer any question about it.
    # Sizing the ball larger did not help: three surfaces meeting near-tangentially is
    # the problem, not the ball. Overlapping cylinders are several closed bodies that
    # share no surface, which is all this has ever needed to be.
    parts = []
    for i, (a, b) in enumerate(zip(pts[:-1], pts[1:])):
        u = b - a
        L = float(np.linalg.norm(u))
        if L < 1e-6:
            continue
        u = u / L
        a2 = a - u * (d * 0.5 if i > 0 else 0.0)
        b2 = b + u * (d * 0.5 if i < len(pts) - 2 else 0.0)
        parts.append(rod(a2, b2, d, sections))
    return trimesh.util.concatenate(parts)


def screw(p, direction, length, shank_d, head_d, head_h):
    """A pan-head machine screw: shank from `p` along `direction`, head on top of it.

    Modelled head-first-at-p, i.e. `p` is where the head sits on the surface and the
    shank goes INTO the material along `direction`.
    """
    p = np.asarray(p, float)
    u = np.asarray(direction, float)
    u = u / max(float(np.linalg.norm(u)), 1e-9)
    shank = rod(p, p + u * length, shank_d)
    head = rod(p - u * head_h, p, head_d)
    return trimesh.util.concatenate([shank, head])


def insert(p, direction, length, od):
    """A brass heat-set insert, sunk from `p` along `direction`."""
    p = np.asarray(p, float)
    u = np.asarray(direction, float)
    u = u / max(float(np.linalg.norm(u)), 1e-9)
    return rod(p, p + u * length, od)


def propeller(centre, axis_deg, dia, hub_d, hub_l, blades=3, pitch_deg=28.0,
              blade_t=1.6):
    """Hub plus `blades` pitched blades, on an axis `axis_deg` below the x axis.

    Recognisable as a propeller in a render, and the right size in every direction
    that matters: the disc diameter is what sets the clearance to the hull and to the
    rudder, and boat.driveline checks both.
    """
    c = np.asarray(centre, float)
    hub = rod(c - np.array([hub_l / 2.0, 0, 0]), c + np.array([hub_l / 2.0, 0, 0]), hub_d)
    out = [hub]
    r_in, r_out = hub_d / 2.0, dia / 2.0
    for i in range(blades):
        th = 2.0 * np.pi * i / blades
        b = trimesh.creation.box(extents=(blade_t, r_out - r_in, dia * 0.34))
        b.apply_transform(trimesh.transformations.rotation_matrix(
            np.radians(pitch_deg), [0, 1, 0]))
        b.apply_translation((0.0, (r_in + r_out) / 2.0, 0.0))
        b.apply_transform(trimesh.transformations.rotation_matrix(th, [1, 0, 0]))
        b.apply_translation(c)
        out.append(b)
    prop = trimesh.util.concatenate(out)
    prop.apply_transform(trimesh.transformations.rotation_matrix(
        np.radians(-axis_deg), [0, 1, 0], point=c))
    return prop


def rudder(x, z_top, depth, chord, thickness, stock_d, tiller_len):
    """Blade, stock and tiller arm. The blade hangs below `z_top`; the stock runs up
    past it to the tiller, which is what the pushrod pulls on."""
    blade = trimesh.creation.box(extents=(chord, thickness, depth))
    blade.apply_translation((x, 0.0, z_top - depth / 2.0))
    stock = rod((x, 0.0, z_top - depth), (x, 0.0, z_top + 26.0), stock_d)
    tiller = trimesh.creation.box(extents=(thickness + 1.0, tiller_len, 4.0))
    tiller.apply_translation((x, -tiller_len / 2.0, z_top + 24.0))
    return trimesh.util.concatenate([blade, stock, tiller])


def integral_rib(cfg, x0, x1, y_centre, width, z_top, z_from=None,
                 boss_xs=(), boss_w=None, boss_half=7.0, ramp=8.0,
                 full_from=None, full_to=None):
    """A longitudinal rib rising from the hull floor to `z_top`.

    Longitudinal, always. In this print orientation the hull's x axis is the build
    direction, so a rib running along x is a VERTICAL WALL in the print and needs no
    support, while the same feature as a discrete post would be a cylinder
    cantilevered horizontally off a wall. Every mounting boss on this boat is
    therefore a rib with a drilled bore, not a post.
    """
    at = _sampler(cfg)
    xs = sorted(set(list(np.linspace(x0, x1, max(4, int((x1 - x0) / cfg.mesh_dx_mm) + 1)))
                    + [bx + s * boss_half for bx in boss_xs for s in (-1.0, 1.0)]
                    + [bx + s * (boss_half + 4.0) for bx in boss_xs for s in (-1.0, 1.0)]))
    xs = [x for x in xs if x0 - 1e-9 <= x <= x1 + 1e-9]
    secs = []
    for x in xs:
        hb, dep, kz = at(x)
        iy, iz = _inner_u(hb, dep, kz, cfg.wall_mm, cfg.section_points)
        # The rib stands on the hull's inner surface AT ITS OWN y, not on the lowest
        # point of the whole section. Using iz.min() drew every rib from the keel,
        # so a rib sitting 24 mm off the centreline started inside the hull wall and
        # carried tens of millimetres of plastic that held nothing up.
        m = cfg.section_points
        half_y, half_z = iy[m:], iz[m:]
        order = np.argsort(half_y)
        base = float(np.interp(abs(y_centre), half_y[order], half_z[order]))
        z0 = (base - cfg.merge_bite_mm) if z_from is None else z_from
        # The rib's top RAMPS down to its own base over `ramp` at each end, so it has
        # no end face at all. A rib that simply stops has a face perpendicular to the
        # build direction with nothing under it, and fdm.bridge_span counts every one
        # as an unanchored ceiling -- five ribs, ten faces. Running each rib the full
        # length of the bay instead would anchor them on the bed and cost three times
        # the plastic to hold the same ten screws.
        # Full height only over [full_from, full_to] -- the bit that actually carries
        # a fastener -- ramping down to a 0.8 mm plinth outside it. The rib itself
        # runs all the way back to the segment's aft face, so its aft end is ON THE
        # BED and is not a face at all. Stopping the rib where its bosses stop left a
        # 0.6 mm end face perpendicular to the build direction, and fdm.bridge_span
        # counts any such face as an unanchored ceiling however small it is. Carrying
        # it aft as a plinth costs 0.8 mm of height and fixes it.
        a = x0 if full_from is None else full_from
        b = x1 if full_to is None else full_to
        if x < a:
            f = min(1.0, max(0.0, (x - x0) / ramp)) if ramp > 0 else 1.0
            f = min(f, min(1.0, max(0.0, (x - (a - ramp)) / ramp)) if ramp > 0 else 1.0)
        elif x > b:
            f = min(1.0, max(0.0, (b + ramp - x) / ramp)) if ramp > 0 else 1.0
            f = min(f, min(1.0, max(0.0, (x1 - x) / ramp)) if ramp > 0 else 1.0)
        else:
            f = 1.0
        top = max(z0 + 0.8 + (z_top - z0 - 0.8) * f, z0 + 0.8)
        # Boss width only where a fastener actually lands. Carrying it the whole
        # length cost 13 cm3 per rib to hold two M3 screws, and three of those put
        # hull_mid past its print-time ceiling. Varying the sweep's width keeps it
        # ONE body -- separate pad boxes were extra bodies whose aft faces read as
        # unanchored ceilings to fdm.bridge_span.
        # RAMPED, not stepped. A step in the swept width is a face perpendicular to
        # the build direction with nothing under it, and fdm.bridge_span counted
        # thirty of them as unanchored ceilings. Four millimetres of ramp for about
        # three of width is a 38 degree transition.
        w = width
        if boss_xs and boss_w:
            d = min(abs(x - bx) for bx in boss_xs)
            if d <= boss_half:
                w = boss_w
            elif d <= boss_half + 4.0:
                t = (boss_half + 4.0 - d) / 4.0
                w = width + (boss_w - width) * t
        half = w / 2.0
        secs.append((float(x), np.array([[y_centre - half, z0], [y_centre + half, z0],
                                         [y_centre + half, top], [y_centre - half, top]])))
    return _sweep(secs)


def saddle_clamp(cfg, x0, x1, y_half, z_land, z_over, wall):
    """An upside-down U that arches over a cylindrical component and lands on two
    ribs either side of it. Swept along x as ONE closed profile, so it is a single
    body with no internal faces."""
    poly = np.array([
        [-y_half, z_over], [y_half, z_over], [y_half, z_land],
        [y_half - wall, z_land], [y_half - wall, z_over - wall],
        [-(y_half - wall), z_over - wall], [-(y_half - wall), z_land],
        [-y_half, z_land],
    ], float)
    return _sweep([(float(x0), poly), (float(x1), poly)])


def tube_along(points, d, sections=12, samples_per_seg=4):
    """A single closed tube swept along a polyline. ONE body, no knots.

    polytube() emits overlapping cylinders, which is fine for a pushrod inside a
    guide tube but not for anything cad.wall_thickness looks at: where two cylinders
    cross at a knot, a ray leaving one immediately enters the other and the gate
    reports the gap. It measured 0.057 mm through a 3.4 mm wire.

    This sweeps a ring along the path instead, so there is one surface and no
    interior. The frame is carried along the path rather than recomputed per segment,
    which keeps the ring from spinning at a corner and folding the tube.
    """
    pts = [np.asarray(p, float) for p in points]
    path = []
    for a, b in zip(pts[:-1], pts[1:]):
        for t in np.linspace(0.0, 1.0, samples_per_seg, endpoint=False):
            path.append(a + (b - a) * t)
    path.append(pts[-1])
    path = np.asarray(path, float)

    tangents = np.gradient(path, axis=0)
    tangents /= np.maximum(np.linalg.norm(tangents, axis=1)[:, None], 1e-9)
    ref = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(tangents[0], ref))) > 0.9:
        ref = np.array([0.0, 1.0, 0.0])
    normal = np.cross(tangents[0], ref)
    normal /= max(float(np.linalg.norm(normal)), 1e-9)

    rings = []
    for i, (p, t) in enumerate(zip(path, tangents)):
        normal = normal - t * float(np.dot(normal, t))       # parallel transport
        normal /= max(float(np.linalg.norm(normal)), 1e-9)
        binormal = np.cross(t, normal)
        ang = np.linspace(0.0, 2.0 * np.pi, sections, endpoint=False)
        rings.append(p + (d / 2.0) * (np.cos(ang)[:, None] * normal
                                      + np.sin(ang)[:, None] * binormal))

    verts = np.vstack(rings)
    n = sections
    faces = []
    for i in range(len(rings) - 1):
        a, b = i * n, (i + 1) * n
        for j in range(n):
            k = (j + 1) % n
            faces.append([a + j, a + k, b + k])
            faces.append([a + j, b + k, b + j])
    # end caps, as fans from an added centre vertex each
    verts = np.vstack([verts, path[0], path[-1]])
    c0, c1 = len(verts) - 2, len(verts) - 1
    last = (len(rings) - 1) * n
    for j in range(n):
        k = (j + 1) % n
        faces.append([c0, k, j])
        faces.append([c1, last + j, last + k])
    m = trimesh.Trimesh(vertices=verts, faces=np.array(faces), process=True)
    m.fix_normals()
    return m
