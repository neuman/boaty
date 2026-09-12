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


def fuse(mesh, name=""):
    """Union a multi-body part into one solid, CHECKED, or hand back the original.

    The module builds parts as abutting closed bodies and avoids booleans on purpose
    (see the header). One part -- the mid deck, which is four slabs and four coaming
    rails -- has to be a single body anyway, because a multi-body mesh has internal
    faces and the mesh gates cannot tell an internal face from a void:
    cad.wall_thickness cast a ray along the seam between two overlapping deck slabs
    and reported a 0.003 mm section through 1.4 mm of solid plastic.

    So the boolean is used, and it is WRAPPED (rule 7). A boolean that quietly
    returns an empty mesh is how a part disappears from an assembly with every gate
    still green, so the result has to be one watertight positive-volume body whose
    volume is within 25% of the sum of the inputs -- overlaps mean it must be a
    little smaller, never larger, and never a fraction. Anything else, the original
    multi-body mesh is returned unchanged and the gates get to complain about the
    real thing rather than about a silent substitution.
    """
    if mesh.body_count <= 1:
        return mesh
    before = float(mesh.volume)
    try:
        u = trimesh.boolean.union(mesh.split(only_watertight=False))
    except Exception:
        return mesh
    if u is None or len(u.faces) == 0:
        return mesh
    if not (u.is_watertight and u.is_volume and u.body_count == 1):
        return mesh
    if not (0.75 * before <= float(u.volume) <= 1.02 * before):
        return mesh
    # Clean the slivers the boolean leaves behind, then CHECK IT THROUGH STL.
    # In memory the union came back watertight and a valid volume; through the file
    # format the gates actually read, it came back with 2 non-manifold edges and 59
    # zero-area faces, because STL has no vertex identity and the loader welds at
    # 1e-4 mm. Checking the in-memory object was checking the wrong artifact -- the
    # same mistake as judging a part in assembly coordinates.
    try:
        u.update_faces(u.nondegenerate_faces(height=1e-4))
        u.remove_unreferenced_vertices()
        u.merge_vertices(digits_vertex=4)
        rt = trimesh.load(trimesh.util.wrap_as_stream(u.export(file_type="stl")),
                          file_type="stl", process=True)
    except Exception:
        return mesh
    if not (rt.is_watertight and rt.is_volume and rt.body_count == 1):
        return mesh
    if not (0.75 * before <= float(rt.volume) <= 1.02 * before):
        return mesh
    return u


def box(cx, cy, cz, lx, ly, lz):
    b = trimesh.creation.box(extents=(lx, ly, lz))
    b.apply_translation((cx, cy, cz))
    return b


def hatch_cover(cfg, hx0, hx1, hhw):
    """Lid for the equipment bay: a plate with two downstand side rails, swept as ONE
    closed body.

    Built as a single swept profile rather than a plate plus four boxes, because a
    multi-body mesh has INTERNAL faces and the fdm mesh gates cannot tell an internal
    face from a ceiling. The four-box version put the rails' undersides 0.1 mm inside
    the plate, and fdm.bridge_span read them as a 149 mm unsupported span over solid
    material that a slicer would have unioned away. The gate was not wrong about the
    mesh it was given; the mesh was the wrong thing to give it.

    Fore and aft the cover is flat and lands on the foam tape; the rails are what
    locate it in the opening and shed water sideways.
    """
    at = _sampler(cfg)
    dz = deck_z(cfg.hull_scale, cfg.loa_mm) + cfg.deck_gap_mm
    c = cfg.fit_clearance_mm
    w = cfg.lip_wall_mm
    W = hhw + cfg.coaming_w_mm + cfg.hatch_land_mm   # lid covers the coaming
    ro = hhw - c                           # outer face of the rail
    ri = ro - w                            # inner face of the rail
    # The lid sits ON TOP of the coaming, with the foam tape on the coaming's top
    # face, and its rails drop through the coaming into the opening. The first
    # version put the lid at deck level, where its outboard land ran straight through
    # the coaming: cad.clash, 34325 mm3, 1.9 mm deep over 18040 mm2.
    z0 = dz + cfg.deck_mm + cfg.coaming_h_mm + cfg.gasket_mm
    _rail = cfg.coaming_h_mm + cfg.hatch_lip_mm + cfg.fit_clearance_mm
    # a Pi section: lid across the top, two legs hanging into the opening
    poly = np.array([
        [-W, z0 + cfg.hatch_mm], [W, z0 + cfg.hatch_mm],
        [W, z0], [ro, z0], [ro, z0 - _rail], [ri, z0 - _rail],
        [ri, z0], [-ri, z0], [-ri, z0 - _rail],
        [-ro, z0 - _rail], [-ro, z0], [-W, z0],
    ], float)
    a = hx0 - cfg.hatch_land_mm
    b = hx1 + cfg.hatch_land_mm
    return _sweep([(float(a), poly), (float(b), poly)])


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
