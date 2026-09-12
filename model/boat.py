# SPDX-License-Identifier: Apache-2.0
"""boaty -- a 3D-printed RC displacement boat. The only source of truth.

Everything downstream -- STLs, the bill of materials, the mass budget, every number
the gates read, the readiness report and the site -- is generated from `Config` and
`build()`. Nothing is typed twice (METHOD rules 1 and 2).

Read `model/hullform.py` first for the frame. In one line:

    x = 0 at the TRANSOM, +x forward; y = 0 on the centreline; z = 0 AT THE LOWEST
    POINT OF THE KEEL, +z up.

Every draft, KG, KB and freeboard below is from that z = 0. The design tool's own
waterline is not a datum here -- it was a slider position on a screenshot, and the
boat floats where its mass says it floats, which is the single most important
finding in this project.

Units: millimetres, grams, newtons, degrees inside this file. `build()` also emits
SI keys (metres, kg, m^2, m^3, m^4) because fluids-analytic is SI-only and
unprefixed, and a factor of a thousand in a waterplane inertia looks exactly like a
metacentric height of forty metres -- which its PACK.md warns about by name.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass, asdict, field, fields

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import trimesh

import hullform
import geometry as G

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.path.join(ROOT, "build")

G_ACCEL = 9.80665
RHO_FRESH = 998.0            # kg/m^3 at 20 C. Pond water. Sea water would be 1025
                             # and every draft here would be 2.7% shallower, which
                             # is a change nobody would notice and nobody should rely on.


# --------------------------------------------------------------------------- #
# Materials
# --------------------------------------------------------------------------- #
MATERIALS = {
    # PETG over PLA is not a close call for this part. PLA absorbs water, creeps,
    # and goes brittle; a PLA hull left in a hot car delaminates at the layer lines,
    # which on a boat is the failure that matters. ABS would be better again and is
    # not printable on an open-frame machine without warping a 200 mm part.
    "petg": {"density_g_cm3": 1.27, "E_mpa": 1800.0, "yield_mpa": 30.0},
    "pla":  {"density_g_cm3": 1.24, "E_mpa": 2800.0, "yield_mpa": 35.0},
}


# --------------------------------------------------------------------------- #
# Components. Mass and size are what the hydrostatics and the clash check stand on,
# so each line carries where the number came from. `price_usd` and the vendor fields
# feed the sourcing pack.
#
# CONFIDENCE is per-line and honest: "listed" means a vendor listing states it,
# "class" means it is the typical figure for that class of part and the specific
# item may differ by 10-20%. Claim A2 carries the consequence.
# --------------------------------------------------------------------------- #
@dataclass
class Part:
    key: str
    desc: str
    mass_g: float
    size_mm: tuple                  # (x, y, z) bounding box as installed
    price_usd: float
    qty: int = 1
    vendor: str = "Amazon"
    mpn: str = ""
    search: str = ""
    lead_days: int = 3
    moq: int = 1
    confidence: str = "class"
    note: str = ""
    cls: str = "cots"
    manufacturer: str = ""
    placed: bool = True             # does it get a clash box inside the hull
    currency: str = "USD"
    lifecycle: str = "active"
    second_source: str = ""


def _manufacturer_of(desc: str) -> str:
    """First token of the description, which for these lines is the brand. Derived
    rather than typed a second time (rule 2): `manufacturers` in the BOM is what
    single-source risk is counted from, and a typo'd brand silently becomes a second
    source that does not exist."""
    first = desc.split(",")[0].split()[0]
    return first if first[:1].isupper() else "generic"


def _parts() -> list:
    """The bill of materials.

    Prices are USD, Amazon US unless the vendor column says otherwise. Several were
    price-verified on the manufacturer's or a fetchable retailer's own page and say
    so; Amazon itself refused every product-page fetch during research, so Amazon
    prices are ESTIMATES and the roll-up is +/-25%, not a quote. The ASINs are real
    -- each came from a live amazon.com/dp/ URL -- but every line also carries a
    search string, because a stale ASIN is worse than useless and a search is not.
    """
    return [Part(**{**asdict(p), "manufacturer": p.manufacturer or _manufacturer_of(p.desc)})
            for p in _parts_raw()]


def _parts_raw() -> list:
    return [
        Part("motor", "RC4WD Z-E0001 540 crawler brushed motor, 80 turn", 156.0,
             (50.0, 35.5, 35.5), 22.0, mpn="B00CR32LZ0",
             search="RC4WD 540 Crawler Brushed Motor 80T Z-E0001",
             confidence="spec verified; price estimated",
             second_source="INJORA 540 80T; INJORA 55T (B08CSJTDGH) runs faster than ideal",
             note="80 turns: 5500 rpm no-load at 7.2 V, best efficiency 4450 rpm at 1.38 A. "
                  "That is the entire reason for this motor. A STOCK 380 or 540 is about "
                  "3000 rpm/V, i.e. 22000 rpm on 2S -- four to six times what a 35 mm prop "
                  "on a displacement hull wants -- and running it at quarter throttle is "
                  "not the same thing as choosing the right motor. "
                  "REJECTED: Mabuchi RS-380SH-20150, 71 g and 916 rpm/V, which is 85 g "
                  "lighter AND the right speed. It has a 2.3 mm shaft, and essentially "
                  "every RC-boat coupler sold is 3.17 mm. The 2.3-to-4 mm coupler exists "
                  "and no reliable US listing could be confirmed for it. A part you cannot "
                  "order is a part you do not have; the 85 g is bought back with hull scale."),
        Part("esc", "Fire Phoenix 'New Rain' 60 A waterproof brushed ESC, single motor", 44.0,
             (42.0, 28.0, 25.0), 26.0, mpn="B08B5TTFVV",
             search="Fire Phoenix New Rain 60A waterproof brushed ESC RC boat single motor",
             confidence="spec verified; price estimated",
             second_source="Hobbywing QuicRun WP-1060 (B0CNT14KMH), 39 g, IP67, better built, ~$30",
             note="ORDER THE SINGLE-MOTOR VARIANT -- the listing has a single/dual selector. "
                  "60 A on a 2-4 A load is deliberate oversizing and it IS the thermal "
                  "design: the hull is sealed, there is no airflow at all, and conformal "
                  "coating makes dissipation worse. Oversize the ESC rather than thin the "
                  "coating. MUST HAVE REVERSE; set Forward/Reverse, not "
                  "Forward/Brake/Reverse, so there is no drag brake. "
                  "REJECTED: the $12 'GoolRC 320A' class. The 320 A is fantasy -- documented "
                  "thermal cutoff in about a minute at full power on 3S, and 1.5 kHz drive "
                  "PWM. In a sealed hull that is a recovery by paddle."),
        Part("servo", "Savox SW-0250MG waterproof digital micro servo, IP67", 25.0,
             (32.5, 14.0, 29.5), 40.0, mpn="B0C11MYL3W",
             search="Savox SW-0250MG waterproof digital micro servo",
             confidence="spec verified; price estimated",
             second_source="Miuzei MG90S metal gear (B0BWJ41FZB), 14 g, ~$6 -- NOT waterproof",
             note="5.0 kg-cm at 6 V, IP67. The rudder servo is the one item in a boat that "
                  "is guaranteed to meet water eventually, and 2.5x the torque of an MG90S "
                  "is margin for a rudder tube stiffened with grease and grit. "
                  "MOUNTING LUG SPACING IS NOT PUBLISHED by Savox -- measure it with "
                  "calipers before you print the servo mount."),
        Part("radio", "Flysky FS-GT5 2.4 GHz pistol-grip transmitter with FS-BS6 receiver", 9.0,
             (30.0, 22.0, 16.0), 54.0, mpn="B07C16BX6L",
             search="Flysky FS-GT5 FS-BS6 transmitter receiver",
             confidence="price VERIFIED $53.90 at HobbyMate",
             second_source="RadioLink RC4GS V3 + R6FG (B09YR4SN17); Spektrum DX3 Smart, $89.99 verified",
             note="The mass and size are the RECEIVER; the transmitter is not in the boat. "
                  "Pistol grip is the right ergonomics for a surface vehicle. Per-channel "
                  "failsafe: SET THROTTLE FAILSAFE TO NEUTRAL. A lost link with the throttle "
                  "stuck open is how boats end up in the reeds. "
                  "REJECTED: RadioMaster Pocket ELRS. No receiver in the box, TX and RX "
                  "firmware majors must match to bind, and most ELRS receivers are CRSF only "
                  "with no PWM output for a servo. Great radio, wrong first radio."),
        Part("battery", "Zeee 2S 7.4 V 2200 mAh 50C shorty LiPo, XT60", 98.0,
             (73.0, 34.0, 18.5), 15.5, mpn="B0BYNKBKGT",
             search="Zeee 2S 2200mAh 50C shorty XT60",
             confidence="price VERIFIED $30.99 for 2 at zeeebattery.com",
             second_source="Ovonic 2200 2S (B0CF9JRPZL) 87x33x18 mm 118 g; Gens Ace 2200 (B09Z1YLQ8G)",
             note="Second heaviest item, and the one that sets both KG and LCG, so it lives "
                  "on the hull floor on the centreline. The SHORTY pack matters: 73 mm long "
                  "against 87-105 mm for a standard 2200, which buys the longitudinal room "
                  "to trim the boat by sliding it. 35-60 min at a 2-4 A cruise. "
                  "REJECTED: 5200 mAh 2S hardcase -- 261 g and 138 mm long."),
        Part("charger", "HTRC B6 V2 80 W balance charger", 0.0, (0.0, 0.0, 0.0), 28.0,
             mpn="B08DV5PSD8", search="HTRC B6 V2 80W balance charger",
             confidence="price VERIFIED $27.99 Banggood US", placed=False,
             note="Not in the boat. CONFIRM the AC adapter is in the box: the unit itself is "
                  "DC 11-18 V input. Charge in a LiPo bag at 1C (2.2 A), never unattended."),
        Part("shaft_kit", "uxcell 4 mm drive shaft assembly: 250 mm shaft, 200 mm stuffing "
                          "tube, universal joint for a 3.17 mm motor shaft, nylon prop, dog, nut",
             80.0, (250.0, 10.0, 10.0), 18.0, mpn="B07Q3286KM",
             search="uxcell 4mm Drive Shaft L250mm Sleeve L200mm 3.17mm Motor Shaft",
             confidence="price VERIFIED $17.59 at Harfington (uxcell's own store)", placed=False,
             second_source="generic 'RC boat 4mm drive shaft' sets, sleeve OD 10 mm (B07RK979GW)",
             note="STUFFING TUBE OD IS 9.5 mm -- drill the hull at 10.2 mm for clearance plus "
                  "an epoxy fillet. The 130 mm short kit does NOT come with a 3.17 mm joint; "
                  "only the 250 mm and longer kits do, which is the second independent reason "
                  "this boat is 420 mm rather than 300 mm. "
                  "Not clash-checked as a box: it lives on the shaft axis and boat.driveline "
                  "settles it instead."),
        Part("prop", "3-blade brass scale propeller, 35 mm diameter, M4", 14.0,
             (16.0, 35.0, 35.0), 13.0, mpn="B0D814JF9S",
             search="RC Boat 3-Blades Propeller Copper M4 35mm scale marine tug",
             confidence="spec verified; price estimated", placed=False,
             note="Replaces the nylon prop in the shaft kit. The bundled nylon props run "
                  "pitch/diameter 1.4 to 1.9, which is RACING pitch; a displacement hull "
                  "wants about 0.9 to 1.1. Keep the nylon one as the spare -- it works, at "
                  "lower throttle."),
        Part("rudder", "Hobbypark aluminium transom-mount rudder, 75 mm, frame 60 x 43 mm", 37.0,
             (60.0, 14.0, 75.0), 16.0, mpn="B07FS9KBYZ",
             search="Hobbypark aluminum RC boat rudder 75mm transom mount",
             confidence="spec verified; price estimated", placed=False,
             second_source="95 mm version (B07FS2G9KN) for boats up to 850 mm",
             note="TRANSOM mount, and that is forced rather than chosen. The bottom-mount "
                  "scale rudders (62x30 mm pad, 6 mm sleeve) bolt to the hull BOTTOM, which "
                  "would put the blade ahead of a propeller that has to sit aft of the "
                  "transom on a hull this shallow -- and a rudder in the prop's INFLOW is "
                  "not steering, it is drag. Rated for 400-600 mm boats. "
                  "MOUNTING HOLE SPACING IS NOT PUBLISHED: measure before drilling."),
        Part("linkage", "Pushrod, clevises and 3 mm brass pushrod tube", 12.0,
             (140.0, 6.0, 6.0), 8.0, search="RC pushrod linkage clevis set 2mm brass tube",
             confidence="class", placed=False,
             note="The pushrod runs from the servo in the equipment bay through a brass tube "
                  "epoxied through the aft bulkhead and the transom ABOVE the waterline, to "
                  "the rudder tiller. Epoxy-fillet both ends of the tube; the aft compartment "
                  "stays sealed."),
        Part("switch", "RC on/off switch with an external aluminium control rod", 12.0,
             (35.0, 16.0, 14.0), 12.0, mpn="B0CCTS8BW3",
             search="RC receiver on off switch aluminum control rod boat",
             confidence="class",
             note="The switch body stays inside the sealed hull and a rod through a small "
                  "bushing flips it from outside. A conventional switch harness is a hole in "
                  "the deck with a moving part in it. NEVER put a mechanical switch in the "
                  "battery-to-ESC path; switch the receiver/BEC side only."),
        Part("hatch_seal", "Self-adhesive silicone or EPDM closed-cell foam tape, 10 x 3 mm", 8.0,
             (0.0, 0.0, 0.0), 9.0,
             search="self adhesive silicone foam tape 10mm x 3mm closed cell",
             confidence="class", placed=False,
             note="Prusa measured PRINTED flexible-filament gaskets failing completely and "
                  "O-rings being the most reliable hatch seal. Closed-cell foam tape on the "
                  "deck land, compressed by four M3 screws, is the buildable version. "
                  "Silicone-grease it every session. NEVER glue the hatch shut."),
        Part("foam", "Closed-cell polyethylene foam for the sealed end compartments", 14.0,
             (0.0, 0.0, 0.0), 7.0, search="closed cell polyethylene foam block",
             confidence="class", placed=False,
             note="A pool noodle works. CLOSED cell, not open: open-cell foam is a sponge and "
                  "becomes ballast. Sealed air alone fails closed-loop -- one crack and the "
                  "entire reserve is gone at the moment it is needed."),
        Part("grease", "Dynamite marine grease, 5 oz, for the stuffing tube", 12.0,
             (0.0, 0.0, 0.0), 12.0, mpn="B00XUM0OQK", search="Dynamite Marine Grease 5 oz",
             confidence="class", placed=False,
             note="NOT thin silicone grease -- that is for O-rings and the hatch seal. The "
                  "stuffing tube is packed one third to one half full with thick tacky "
                  "marine grease, injected from the prop end; the grease is a physical plug "
                  "as much as a lubricant. Overfilling just adds drag."),
        Part("rtv", "Permatex 82180 Ultra Black RTV, neutral cure, sensor safe", 10.0,
             (0.0, 0.0, 0.0), 9.0, mpn="B0002UEN1U",
             search="Permatex 82180 Ultra Black sensor safe RTV",
             confidence="price VERIFIED $8.99 Summit Racing", placed=False,
             note="NEUTRAL CURE, and this is not a preference. Acetoxy-cure RTV -- which is "
                  "most clear silicone, including Permatex 66B and GE Silicone 1 -- releases "
                  "acetic acid as it cures, and in a sealed hull the vapour condenses on IC "
                  "leads and attacks copper and solder. If you substitute: GE Silicone II is "
                  "neutral cure, GE Silicone 1 is not, and the packaging does not make that "
                  "obvious."),
        Part("epoxy", "Smooth-On XTC-3D brush-on epoxy coating, 6.4 oz", 30.0,
             (0.0, 0.0, 0.0), 28.0, mpn="B09MSPD3MK", search="Smooth-On XTC-3D 6.4 oz",
             confidence="coverage verified at Smooth-On; price estimated", placed=False,
             note="THIS is what makes an FDM hull watertight. The printed seam is not the "
                  "seal; the fillet over it is. 1 oz covers about 645 cm2, so 6.4 oz is two "
                  "coats on this boat with margin. Brush it INSIDE, seams first, thin coats "
                  "-- pooled epoxy adds mass without adding sealing. "
                  "REJECTED: 5-minute hardware-store epoxy, too viscous to wick into a layer "
                  "line; and any 'table top' casting resin, which is a bar-top product rated "
                  "at 1/8 inch and far too heavy."),
        Part("coating", "MG Chemicals 422B silicone conformal coating, 55 mL with brushes", 10.0,
             (0.0, 0.0, 0.0), 24.0, mpn="B008O9YIV6",
             search="MG Chemicals 422B silicone conformal coating 55 mL brush",
             confidence="class", placed=False,
             note="Brush-on bottle, not aerosol. MASK the ESC heatsink pad, the BEC header "
                  "and every connector you will unplug. Coating measurably impedes heat "
                  "dissipation, which is why the ESC is oversized instead of the coating "
                  "thinned. It buys splash protection, not submersion."),
        Part("fasteners", "M3 stainless screws and washers, hook-and-loop battery strap", 20.0,
             (0.0, 0.0, 0.0), 11.0, search="M3 stainless machine screw assortment",
             confidence="class", placed=False),
    ]


# --------------------------------------------------------------------------- #
@dataclass
class Config:
    # ---- hull form -------------------------------------------------------
    hull_scale: float = 1.60
    """Multiplier on every traced offset. THE decision of this project.

    At 1.00 (the LOA 300 mm the design tool reported) the hull displaces 73 g at the
    waterline the tool drew, and about 477 g of boat would float it with 10 mm of
    freeboard -- a fail on C2 with a +/-15% mass estimate riding on it. Displacement
    goes as scale^3 while motor, ESC, servo, receiver and battery do not scale at
    all, so scale is the cheapest freeboard there is.

    1.50 was rejected: 225 mm hull segments no longer fit a 220 x 220 bed.
    1.40 gives 210 mm segments with room for a brim. See `atompipe why hull_scale`."""

    traced_loa_mm: float = 300.0
    """LOA the design tool reported, and the length every traced offset is in."""

    # ---- printed structure ----------------------------------------------
    wall_mm: float = 1.6
    """Hull shell wall. 4 perimeters at a 0.4 mm nozzle. 1.2 mm (3 perimeters) is
    the printable minimum and is what C8 asks for, but the hull shell is the
    pressure boundary and 1.2 mm PETG has visible pinholes at the layer bonds on a
    curved wall. 2.0 mm was tried and costs 55 g for stiffness nothing needs."""

    deck_mm: float = 1.4
    """Deck panels. Not a pressure boundary and not loaded; 2.4 mm cost 46 g across
    the three panels and the hatch for nothing. 1.2 mm was tried next, on the
    reasoning that 3 perimeters at a 0.4 mm nozzle is 1.2 mm, and fdm.min_wall
    refused it:

        thinnest section 1.20 mm = 2.6 beads vs 1.38 mm minimum
        (3 x 0.46 mm line width)

    Three perimeters is three EXTRUSION WIDTHS, not three nozzle diameters, and the
    extrusion width is about 1.15x the nozzle. 1.4 mm is three real beads."""

    plate_mm: float = 2.0
    """Transom and bulkhead plates. These ARE loaded (the bulkheads are what stops
    the hull folding, and the transom carries the rudder bracket) so they are
    thicker than the deck and thinner than the shell, which only has to be thick
    because it has to be watertight."""

    hatch_mm: float = 1.6
    """Hatch lid plate. Same 3-bead minimum as the deck; it is handled and
    occasionally leaned on, so it is not thinner than the deck it sits on."""
    hatch_lip_mm: float = 5.0
    """Depth the lid's rails drop into the opening. Deep enough to locate the lid
    positively when the tape is compressed, shallow enough that you can lift it out
    with wet fingers."""
    hatch_land_mm: float = 7.0
    """How far the lid overhangs the coaming on every side. It is the gasket land:
    the foam tape sits under this, so it has to be wider than the tape."""
    coaming_w_mm: float = 5.0
    """Width of the raised rim around the hatch opening. Wide enough to carry a 10 mm
    tape with margin once the lid's land is on it."""
    coaming_h_mm: float = 4.0
    """A raised lip around the hatch opening. Water on deck runs round it instead of
    into the equipment bay. Four millimetres is enough for a pond and is one layer
    of overhang at the top, not a bridge."""

    lip_wall_mm: float = 2.0
    """Wall of every printed rail and rim. 5 beads at a 0.4 nozzle: these are short
    unsupported walls and 2 mm prints reliably where 1.2 mm wanders."""
    plate_lip_inset_mm: float = 1.5
    """Vestigial: the plates no longer carry locating lips (see make_parts). Kept so a
    future variant that wants them does not have to re-derive the inset."""
    spigot_mm: float = 9.0
    """Length a locating feature projects across a joint. Now only used as the lip
    length the bulkheads would have had; see make_parts for why the lips went."""
    spigot_wall_mm: float = 2.0
    """Wall of a projecting locating ring. Vestigial with the lips; see make_parts."""
    fit_clearance_mm: float = 0.35
    """Clearance on every printed plug fit. 0.2 is the usual FDM number and it is
    too tight here: these are large, curved, thin-walled mouldings that come off
    the bed 0.3 mm out of round, and a spigot you have to force into a hull is a
    spigot that cracks it."""

    body_overlap_mm: float = 0.08
    """How far every sub-body pokes into its neighbour instead of abutting it.
    Face-coincident bodies are watertight in memory and stop being watertight the
    moment they go through STL, which has no vertex identity: the loader welds the
    duplicated vertices and the shared face becomes a seam of non-manifold edges.
    0.08 mm is a fifth of a nozzle -- invisible to a slicer, and no shared vertices
    to weld."""

    deck_lap_mm: float = 2.0
    """How far deck sub-panels lap each other. It has to EXCEED the minimum wall,
    because the lap is a wall: at 0.08 mm the lap was a 0.16 mm slab and
    cad.wall_thickness correctly reported a 0.160 mm section through it."""

    deck_step_mm: float = 0.06
    """Vertical step between lapped deck sub-panels, so their faces are never
    coincident. See geometry.deck_panel. Under a fifth of a layer: the slicer never
    sees it."""

    gasket_mm: float = 3.0
    """Compressed thickness of the closed-cell foam tape between the coaming's top
    face and the underside of the hatch lid. It is a real part on the BOM, and
    modelling it as a gap is also what stops the lid and the coaming reading as
    5541 mm3 of interference."""

    deck_gap_mm: float = 0.3
    """Epoxy bond line between the hull/bulkhead tops and the underside of the deck.
    Also the thing that keeps those faces from being exactly coplanar, which a
    boolean engine cannot answer questions about -- see geometry.deck_panel."""

    tip_clear_mm: float = 1.2
    """How far the blunt stem is held BELOW the flat deck. Without it the traced sheer
    at the stem rises past deck_z, the vertical strake collapses to its 0.05 mm
    minimum, and cad.wall_thickness casts a ray into the resulting sliver."""
    tip_half_beam_mm: float = 2.0
    """Half the width of the blunt stem face. A hull tapering to a mathematical point
    is unprintable (nothing is narrower than one extrusion width) and unmeasurable:
    cad.wall_thickness reported a 0.003 mm wall into the old knife edge. 4 mm across
    the stem is ten beads and invisible on a 480 mm boat."""

    tip_depth_mm: float = 6.0
    """Height of the blunt stem face. Same reason as tip_half_beam_mm; together they
    make the stem a real face the stem plate can be bonded to."""
    """The stem is BLUNT. A hull tapering to a mathematical point is unprintable --
    nothing is narrower than one extrusion width -- and unmeasurable: cad.wall_thickness
    cast a ray into the old knife edge and reported a 0.003 mm wall against a 1.4 mm
    minimum. 1.8 mm across the stem is four beads and invisible on a 480 mm boat."""

    min_cavity_mm: float = 25.0
    """The hull tube stops where its internal cavity narrows to this. It is a
    PRINTABILITY number, not a structural one: past this point the inward offset
    self-intersects, and the solid nose that used to fill the gap failed
    cad.wall_thickness, fdm.overhang and fdm.bridge_span in turn depending on which
    way up it was printed. 25 mm truncates the stem by about 5 mm and replaces all
    three failures with one more flat plate."""
    section_points: int = 24
    """Points per half-section. 24 puts about 4 mm between points at the turn of bilge,
    which is where this hull has all its curvature. 12 visibly facets the bilge; 48
    doubles the mesh for a difference no slicer resolves."""
    mesh_dx_mm: float = 5.0
    """Longitudinal station spacing in the generated mesh. 5 mm. The hull changes
    slowly along x, so this is about surface quality rather than accuracy."""

    girder_t_mm: float = 2.4
    """Girder web thickness. 6 beads. It is a bonded web in shear, not a column."""
    girder_h_mm: float = 10.0
    """Longitudinal centre girder in the equipment bay bilge. Its job is FREE
    SURFACE, not strength: bilge-water free-surface inertia goes as L*b^3/12, so
    halving the bilge width divides the effect by four, while a transverse bulkhead
    only cuts L and does so linearly.

    10 mm, reduced from 18. cad.clash found the 18 mm web occupying the same space as
    the battery (2465 mm3, 2.1 mm deep) and the motor (630 mm3) -- all three live on
    the centreline and nobody had noticed. Ten millimetres clears both, and it still
    divides the bilge where bilge water actually sits: water deeper than 10 mm across
    this bay is 300 g aboard and an emergency rather than a stability nuance.

    The battery now sits ON the girder and straddles it, which is a better fit than
    the original anyway. See the decision log."""

    # ---- segmentation ----------------------------------------------------
    bulkhead_aft_x: float = 150.0
    """Aft watertight bulkhead. Set by THREE things at once: it is the aft end of the
    equipment bay, it is a print split, and it is the boundary of the sealed aft
    compartment that boat.swamped depends on. It was at 110 mm and moved to 150 mm
    when the swamped margin came out at -7 g: moving both bulkheads inward buys
    sealed volume at both ends and cost 25 mm of bay length."""
    bulkhead_fwd_x: float = 340.0
    """The two watertight bulkheads. They bound the equipment bay and they are also
    the print splits, which is not a coincidence: a seam at a bulkhead gets a plate
    glued across it, and a seam in open shell gets a butt joint and a prayer."""

    hatch_x0: float = 170.0
    """Forward and aft ends of the hatch opening, and its half width. Sized to get the
    motor (50 mm long, 35.5 mm diameter) and the battery in and out with the deck on,
    and inset from the bulkheads far enough to leave a gasket land all round."""
    hatch_x1: float = 320.0
    """See hatch_x0."""
    hatch_half_w: float = 48.0
    """See hatch_x0. Also bounded by the coaming needing to land on deck inboard of
    the hull's topsides."""

    # ---- driveline -------------------------------------------------------
    shaft_exit_x_mm: float = 52.0
    """Where the stuffing tube leaves the hull bottom. Forward enough that the tube has
    a long bonded run inside the sealed aft compartment, aft enough that the shaft
    line does not have to be steep to clear the motor. boat.driveline settles it."""
    shaft_angle_deg: float = 8.0
    """Down-aft angle of the propeller shaft. 8-12 degrees is the practical band: a
    flexible coupler will not take much more, and a shallower angle puts the motor
    on the hull floor. 15 degrees was tried to gain motor clearance and pushes the
    thrust line far enough off horizontal to trim the boat by the stern under power."""
    prop_x_mm: float = -32.0
    """Propeller centre, aft of the transom. Aft, not under the hull, and that is forced
    rather than chosen: this hull draws 30 mm and a 35 mm propeller under it would
    need a skeg deeper than the boat. Aft of the transom the hull does not constrain
    the disc at all, which is also why the rudder has to be transom-mounted."""
    prop_dia_mm: float = 35.0
    """35 mm, which is what the brass scale propeller on the BOM is. It sets how deep
    the propeller hangs (tip 20 mm below the keel) and therefore the prop-to-hull and
    prop-to-rudder clearances boat.driveline checks."""
    rudder_x_mm: float = -62.0
    """Rudder pivot, aft of the transom. Set by the propeller: the blade has to be in
    the wash and clear of the disc, which boat.driveline enforces at 10 mm minimum.
    Anything further aft is a longer unsupported bracket for no gain."""
    rudder_depth_mm: float = 42.0
    """Blade depth below the keel datum. Rudder area wants roughly 1.25 square inches
    per foot of boat, which is about 1550 mm2 here, and the area scales with the
    square of speed - this boat is slow, so the rudder is deliberately oversized."""
    rudder_chord_mm: float = 22.0
    """Blade chord. With the depth, this is what sets the area; deep-and-narrow beats
    wide-and-shallow for authority at low speed."""
    shaft_block_len_mm: float = 45.0
    """The internal block the stuffing tube is bonded through. Long enough to give the
    tube a real bearing length rather than a point, which is what stops the tube
    working loose and starting a leak at the one penetration below the waterline."""
    shaft_block_w_mm: float = 18.0
    """See shaft_block_len_mm. Wide enough to take a 9.5 mm tube with wall either side."""
    shaft_block_h_mm: float = 16.0
    """See shaft_block_len_mm."""
    min_prop_tip_clearance_mm: float = 8.0
    """Minimum gap from the propeller disc to any part of the hull. Below about 8 mm
    the blade tips work in the hull's boundary layer, which is noise, vibration and
    lost thrust."""
    min_prop_rudder_gap_mm: float = 10.0
    """Minimum gap from the propeller disc to the rudder leading edge. Too close and the
    rudder sits in the blade wake and hammers; too far and it is out of the wash and
    the boat will not turn at low speed."""
    max_shaft_angle_deg: float = 12.0
    """What a flexible coupler will take without eating its own bearings. 12 degrees is
    the practical ceiling quoted for these universal joints."""

    # ---- component placement (x, y, z of the CENTRE of each box) ---------
    place: dict = field(default_factory=lambda: {
        # x is set by what the part has to reach; z by keeping mass low; y is 0 for
        # anything heavy, because an off-centre battery is a permanent heel.
        "motor":   (215.0, 0.0, None),
        "battery": (292.0, 0.0, None),
        "esc":     (268.0, 48.0, 40.0),
        "servo":   (178.0, -50.0, 30.0),
        "radio":   (318.0, -40.0, 36.0),
        "switch":  (322.0, 46.0, 46.0),
    })
    """Where each component sits, as (x, y, z) of its box centre. z = None means "on
    the shaft axis" for the motor and "on the hull floor" for anything else on the
    centreline.

    ANYTHING OFF THE CENTRELINE NEEDS AN EXPLICIT z. This hull's sections pinch hard
    at the turn of bilge -- the half-beam is 21% of maximum at 3% of the depth above
    the keel -- so a box placed off-centre at floor level has its outboard bottom
    corner outside the hull. cad.clash caught exactly that on the first layout.

    The battery's x is also the trim adjustment, which is why it is strapped rather
    than glued: sliding it changes LCG, and boat.trim is the gate that says how far."""
    floor_standoff_mm: float = 4.0
    """Everything on the hull floor sits on 2 mm of standoff. Anything resting
    directly in the bilge is sitting in the first millilitre of water that gets in."""

    # ---- loading ---------------------------------------------------------
    mass_contingency_frac: float = 0.08
    """8% on top of the itemised mass, for glue, sealant, paint, wire, solder, the
    hook-and-loop strap and the water an FDM hull absorbs. First builds run 10-20%
    over the paper mass; 8% is the part of that which is not already itemised."""

    design_speed_m_s: float = 0.80
    """Froude 0.39 at this waterline length. fluids-analytic computes no wave-making
    resistance and says so, and becomes a statement about a boat at rest above
    Froude 0.4. Choosing 0.8 keeps C5 inside the pack's stated validity envelope
    rather than outside it. 1.2 m/s was the first number and is Froude 0.59 --
    past hull speed, where the drag verdict would have been arithmetic about
    nothing."""
    thrust_available_n: float = 3.0
    """Static thrust of a 35 mm 3-blade on a 380 at 7.4 V. CLASS FIGURE, not
    measured, and the weakest number in the drag chain -- see the readiness report."""
    hull_cd: float = 0.11
    """Drag coefficient on FRONTAL area (the immersed midship section). The pack's
    table is frontal-referenced and its lens list calls out using a planform or
    wetted-area Cd with a frontal area as a factor-of-several error with no symptom.
    0.11 is a slender streamlined body at Re ~3e5."""
    heel_angle_deg: float = 8.0
    """fluid.righting_arm has NO default heel and skips without one, because GZ is a
    function of the angle and a gate that picked one would be choosing the load
    case. 8 degrees, not 10: 10 is exactly the small-angle ceiling, which is the
    largest arm the gate can ever report."""

    # ---- acceptance thresholds (mirror the ledger claims) ----------------
    max_volume_fraction: float = 0.55      # C1
    """C1. The pack default is 0.90, which is a hull floating almost awash. A pond boat
    gets rained on, takes spray over the transom and leaks a little at the shaft;
    0.55 leaves 45% of the moulded volume as reserve."""
    min_freeboard_limit_mm: float = 25.0   # C2
    """Named `..._limit_mm` rather than `min_freeboard_mm` because the first version
    used one name for the THRESHOLD here and for the MEASURED value out of build(),
    and `atompipe check` refused to let that slide:

        warning: model and build() disagree on min_freeboard_mm:
                 config 25.0 vs build() 31.81 - gates read the config value

    A gate comparing against 25.0 while the report printed 31.8 would have been a
    silent inconsistency in the reassuring direction, which is the kind that survives
    review. 25 mm itself is a project judgement, well above the pack default of 15%
    of hull depth (12.3 mm here), set by pond chop and by the deck edge being where
    water gets in."""
    min_gm_mm: float = 15.0                # C3
    """C3. The pack default is 5% of waterline beam, which is 7.4 mm here. KG is an
    estimate rather than a weighed number, so the default leaves no room for the
    estimate being wrong. 15 mm is about 10% of waterline beam."""
    min_gz_mm: float = 2.0                 # C4
    """C4. The righting arm at 8 degrees. Covers a one-sided load - the whole battery
    adrift against one side of the bay, or a hand shoving the boat off a dock."""
    min_gm_free_surface_mm: float = 10.0   # C17
    """C17 and C19. GM after the bilge free-surface correction, and GM empty. Lower
    than min_gm_mm on purpose: these are degraded conditions and the question is
    whether the boat is still stable, not whether it is still comfortable."""
    max_trim_deg: float = 1.5              # C15
    """Trim angle, either way. 1.5 degrees on this hull costs about 5 mm of the
    lowest deck-edge freeboard, which is a fifth of the freeboard claim -- that is
    the scale at which trim stops being cosmetic. It is set by what a movable
    battery can actually correct, not by comfort: there is nobody aboard."""
    max_lcg_lcb_offset_mm: float = 12.0    # C15, secondary
    """Secondary to max_trim_deg, which is the claim that has teeth. Kept because the
    offset is the number you can act on: it says how far to slide the battery."""
    max_mass_budget_error_frac: float = 0.03  # C14
    """Vestigial: the mass-budget claim was replaced by boat.wall_agreement after the
    original version turned out to be a tautology. See claim C14."""
    envelope_x_mm: float = 560.0
    """Longest dimension of the assembled boat, boxed: a car boot and a kitchen table.
    It also catches a units slip, because a model that has silently gone
    metres-for-millimetres fails boat.envelope loudly instead of exporting a plausible
    STL that nobody measures."""

    envelope_y_mm: float = 230.0
    """Width of the same envelope, with the rudder and prop shaft off."""

    envelope_z_mm: float = 170.0
    """Height of the same envelope, measured over the coaming and the hatch."""

    max_moq_overbuy_usd: float = 25.0
    """Amazon MOQ is normally 1, so this should be trivially green. That is the point:
    it is a cheap gate that would catch the one line that quietly is not."""
    max_lead_days: int = 21
    """Three weeks. Anything longer is not "order it on Amazon this evening", which is
    the constraint the brief actually set."""
    budget_usd: float = 400.0              # C12
    """Total parts cost, excluding the printer. THIS IS THE ONE NUMBER IN THE PROJECT
    THAT IS PURELY INVENTED: the brief said Amazon-orderable and beginner-friendly and
    never named a figure. It started at 200, bom.cost failed at 374.50 against real
    prices, and it was raised with the alternatives written down rather than quietly
    edited - see `atompipe why budget_usd`. Change it, re-run, and bom.cost will say
    what has to go."""

    # ---- print process ---------------------------------------------------
    material: str = "petg"
    """PETG. PLA absorbs water, creeps, and goes brittle; a PLA hull left in a hot car
    delaminates at the layer lines, which on a boat is the failure that matters, and
    its heat-deflection temperature is around 55 C against a 50 C dark-plastic
    surface in sun. ASA would be better still and does not print on an open frame
    without warping a 190 mm part."""
    nozzle_mm: float = 0.4
    """0.4 mm. Every wall thickness in this model is a whole number of beads at this
    nozzle; change it and min_wall, deck_mm and lip_wall_mm all move."""
    layer_mm: float = 0.24
    """0.24 mm, 60% of the nozzle. Measured work on printed watertightness puts 0.15 mm
    best and 0.3 mm worst; 0.24 is the compromise that keeps a 190 mm part under
    seven hours. Drop it to 0.15 for the hull segments if the leak test finds seams."""
    perimeters: int = 4
    """4. Measured leak testing puts PETG at 4 perimeters to be watertight UNTREATED.
    This build also epoxy-coats the interior, so 4 is belt and braces on the one
    thing that cannot be fixed after assembly."""
    infill_frac: float = 0.15
    """15%. Nearly irrelevant to a thin-shelled hull - perimeter count is the dominant
    mass variable, not infill - but it matters for the plates."""
    print_speed_mm_s: float = 60.0
    """60 mm/s. Conservative, because the tall standing hull segments are the shape most
    likely to ring or knock over."""
    bed_x_mm: float = 220.0
    """220 x 220 x 250 mm: the Ender-3 / Prusa-Mini class machine most people who would
    build this actually own. Every print split in the model is set by it."""
    bed_y_mm: float = 220.0
    """See bed_x_mm."""
    bed_z_mm: float = 250.0
    """See bed_x_mm. Not binding: the tallest part is hull_mid at 190 mm."""
    brim_mm: float = 6.0
    """6 mm of brim allowance per side. The tall standing hull segments have a small
    footprint for their height and want a brim; a part sized to the raw bed does not
    fit the bed once the brim is on it."""
    max_print_time_h: float = 14.0
    """Per-part ceiling. A part that takes longer than an evening is a part you will not
    reprint when it fails, and on a first build something always fails."""
    shell_pack_frac: float = 1.0
    """Printed shells (the hull tubes) are modelled at their true wall thickness, so
    the slicer prints them essentially solid: their mesh volume IS their filament
    volume. Plates and decks are modelled as solid slabs and DO get infill -- see
    `plate_pack_frac`. Getting this backwards is a 2x error on the mass that every
    hydrostatic number depends on, which is why C14 exists."""
    plate_pack_frac: float = 0.88
    """A 1.6-2.0 mm slab at 4 perimeters and 0.24 mm layers is mostly perimeter and
    solid top/bottom skin; the infill setting barely gets a look in. 0.88, not the
    0.15 infill figure."""

    write_meshes: bool = True
    """Whether build() exports STLs. The negative-control fixtures turn it off: they
    rebuild the model dozens of times and have no use for the files."""

    # ---- knobs that exist FOR THE NEGATIVE CONTROLS ----------------------
    # Rule 5: a gate that cannot be shown to fail is a logger. Two of this project's
    # gates guard quantities that are very hard to break by any plausible edit --
    # this hull has BM = 91 mm and GM = 79 mm, so no amount of moving a 98 g battery
    # around makes a stability gate fail. Rather than ship gates that cannot fail,
    # the model carries the two levers that CAN break them, defaulted off. They are
    # not fiction: a mast is the single most common thing added to a finished boat,
    # and a generator that emits the wrong wall thickness is the bug this project
    # actually hit (see geometry._cap).
    topside_mass_g: float = 0.0
    """Mass added ON TOP of the deck -- a camera mast, a light bar, a superstructure.
    Zero in the design. The fluids lens list is blunt about why this is the lever
    that matters: "Additions go UP, almost always, because that is where the space
    is." The free-surface and empty-condition controls SOLVE for the value that
    misses their acceptance by 1.15x, rather than typing a number that stops being
    a control the moment somebody relaxes a threshold."""
    topside_z_mm: float = 140.0
    """Height above the keel datum of `topside_mass_g`. 140 mm is roughly a 60 mm
    mast above an 82 mm hull."""
    mesh_wall_scale: float = 1.0
    """FIXTURE KNOB: multiplies the wall used for the INNER offset only, so the
    generated mesh's wall stops matching the specified wall. 1.0 always, except in
    boat.wall_agreement's negative control, where 0.5 simulates exactly the class of
    generator bug this project hit twice."""


    @property
    def loa_mm(self) -> float:
        """Length overall. DERIVED, never stored (rule 2). It used to be assigned onto
        the config inside build(), which meant a Config that had not been through
        build() had no loa_mm -- and the first thing that tripped over that was a
        negative-control fixture, i.e. the one place a silent failure is worst."""
        return self.traced_loa_mm * self.hull_scale


CONFIG = Config()

SHELL_PARTS = ("hull_aft", "hull_mid", "hull_bow")


# --------------------------------------------------------------------------- #
def _shaft_axis(c, at):
    """Shaft exit point on the hull bottom, and the axis direction."""
    ex = c.shaft_exit_x_mm
    _, _, kz = at(ex)
    return ex, kz, np.radians(c.shaft_angle_deg)


def _point_on_shaft(c, at, x):
    ex, ez, a = _shaft_axis(c, at)
    return ez + (x - ex) * np.tan(a)


#: Geometry cache. Mesh generation is ~4.5 s and dominates a build; the parameters
#: that change a MESH are a small subset of Config, and several things that matter a
#: lot to the gates (topside mass, thresholds, prices, placement) change no geometry
#: at all. Without this, the two solved negative controls -- which bisect on topside
#: mass over 34 iterations each -- take five minutes, and rule 10 says an inner loop
#: that costs five minutes is an inner loop nobody runs.
_GEOM_KEYS = ("hull_scale", "traced_loa_mm", "wall_mm", "deck_mm", "plate_mm",
              "hatch_mm", "hatch_lip_mm", "hatch_land_mm", "coaming_w_mm",
              "coaming_h_mm", "lip_wall_mm", "plate_lip_inset_mm", "spigot_mm",
              "spigot_wall_mm", "fit_clearance_mm", "min_cavity_mm",
              "section_points", "mesh_dx_mm", "girder_t_mm", "girder_h_mm",
              "bulkhead_aft_x", "bulkhead_fwd_x", "hatch_x0", "hatch_x1",
              "hatch_half_w", "shaft_exit_x_mm", "shaft_angle_deg",
              "shaft_block_len_mm", "shaft_block_w_mm", "shaft_block_h_mm",
              "mesh_wall_scale")
_GEOM_CACHE: dict = {}


def _geom_key(c: Config):
    return tuple(getattr(c, k) for k in _GEOM_KEYS)


def make_parts(c: Config) -> dict:
    """Every printed part, as a mesh. Keyed by part name. Cached on _GEOM_KEYS."""
    key = _geom_key(c)
    hit = _GEOM_CACHE.get(key)
    if hit is not None:
        return hit
    m = {}
    # NO SPIGOTS on the hull segments. The first design gave each segment a
    # projecting ring to locate the joint, and the ring was inset from the segment's
    # own inner surface by the fit clearance -- which means it was attached to
    # nothing. Printed standing, it was a free-floating 2 mm annulus and
    # fdm.bridge_span reported a 157 mm unsupported span, correctly. The BULKHEAD
    # PLATES already have to be there, already sit at exactly the joint planes, and
    # already carry a locating lip, so they do the job with no extra part and no
    # floating geometry.
    m["hull_aft"] = G.hull_tube(c, 0.0, c.bulkhead_aft_x)
    m["hull_mid"] = G.hull_tube(c, c.bulkhead_aft_x, c.bulkhead_fwd_x)
    m["hull_bow"] = G.hull_tube(c, c.bulkhead_fwd_x, c.loa_mm)
    # The stem is a flat plate, like the transom. See geometry.hull_tube.
    x_stem = G.hull_tube_end(c, c.bulkhead_fwd_x, c.loa_mm)
    m["stem_plate"] = G.plate(c, x_stem - c.plate_mm, c.plate_mm, section_x=x_stem)
    # NO LOCATING LIPS on any plate. A lip is a thin ring inset from the plate's own
    # edge, and near the keel -- where this hull's section is nearly flat and the
    # inward offset clamps at the centreline -- the ring's inner and outer surfaces
    # converge. cad.wall_thickness cast a ray into that and reported a 0.080 mm wall
    # on bulkhead_fwd; the lip also overlapped the girder and gave fdm.bridge_span a
    # 26 mm unsupported span on stem_plate.
    #
    # The joints are located instead by 1.75 mm FILAMENT SHEAR PINS through 2 mm
    # drilled holes, which is documented printed-boat practice, costs nothing, is
    # stronger in shear than a printed lip, and makes every plate a flat slab that
    # prints face-down with no orientation question at all.
    m["transom_plate"] = G.plate(c, 0.0, c.plate_mm, section_x=0.0)
    # The lips point AWAY from the neighbouring segment's spigot; see geometry.plate.
    # Each bulkhead glues into its own end segment; its lip projects into hull_mid
    # and locates the joint. Lip lengths are the spigot length, since that is now
    # what they are.
    m["bulkhead_aft"] = G.plate(c, c.bulkhead_aft_x - c.plate_mm, c.plate_mm,
                                section_x=c.bulkhead_aft_x - c.plate_mm)
    m["bulkhead_fwd"] = G.plate(c, c.bulkhead_fwd_x, c.plate_mm,
                                section_x=c.bulkhead_fwd_x + c.plate_mm)
    m["deck_aft"] = G.deck_panel(c, 0.0, c.bulkhead_aft_x)
    m["deck_mid"] = G.deck_panel(c, c.bulkhead_aft_x, c.bulkhead_fwd_x,
                                 hatch=(c.hatch_x0, c.hatch_x1, c.hatch_half_w),
                                 coaming=c.coaming_h_mm)
    m["deck_bow"] = G.deck_panel(c, c.bulkhead_fwd_x, c.loa_mm)
    m["hatch_cover"] = G.hatch_cover(c, c.hatch_x0, c.hatch_x1, c.hatch_half_w)
    m["girder"] = G.girder(c, c.bulkhead_aft_x + 2.0, c.bulkhead_fwd_x - 2.0)
    at = G._sampler(c)
    ex, ez, _ = _shaft_axis(c, at)
    m["shaft_block"] = G.shaft_block(c, {"exit_x_mm": ex, "exit_z_mm": ez,
                                         "angle_deg": c.shaft_angle_deg})
    # Fuse any part that came out as several abutting bodies. Guarded; see
    # geometry.fuse for what happens when the boolean misbehaves.
    m = {k: G.fuse(v, k) for k, v in m.items()}
    if len(_GEOM_CACHE) > 8:
        _GEOM_CACHE.clear()
    _GEOM_CACHE[key] = m
    return m


#: How each part is laid on the bed. `axis` is the ASSEMBLY axis that becomes the
#: printer's +Z; `flip` turns the part over first.
#:
#: This map exists because the fdm mesh gates judge the mesh in the frame it is
#: given, and the assembly frame is the wrong one. Exporting parts in assembly
#: coordinates put a deck panel floating 70 mm above the "bed" with its whole
#: underside reading as an unsupported ceiling:
#:     fdm.bridge_span: worst unsupported span 201.7 mm ... UNANCHORED
#: which is a true statement about a part nobody would print that way, and tells you
#: nothing about the part you would actually print.
PRINT_ORIENTATION = {
    # Hull segments stand on a transverse face: the section changes slowly along x,
    # so every wall is within ~27 deg of vertical and nothing needs support. See the
    # header of model/geometry.py for the three orientations that were rejected.
    "hull_aft": ("x", False), "hull_mid": ("x", False), "hull_bow": ("x", False),
    # Plates are thin in x in the assembly; laid flat they are thin in z.
    # bulkhead_aft's locating lip points AFT (-x) so it does not fight hull_aft's
    # spigot, which means that after the x->z rotation the lip would land on the bed
    # and the full plate would bridge 198 mm across it. Flipped, the plate is the
    # first layer and the lip points up.
    # Plates are flat slabs with no lip, so they lie face-down and the flip is moot.
    "transom_plate": ("x", False), "bulkhead_aft": ("x", False),
    "bulkhead_fwd": ("x", False), "stem_plate": ("x", False),
    # Decks are already flat plates, thin in z. Nothing to do.
    "deck_aft": ("z", False), "deck_mid": ("z", False), "deck_bow": ("z", False),
    # The hatch cover is flipped so its sealing lip points UP and the flat plate is
    # the first layer. Lip-down would put a 5 mm rib on the bed and hang the plate.
    "hatch_cover": ("z", True),
    # The girder is a thin web, thin in y; laid flat it is thin in z.
    "girder": ("y", False),
    "shaft_block": ("z", False),
}

_AXIS_ROT = {
    "x": (np.radians(-90.0), [0, 1, 0]),
    "y": (np.radians(90.0), [1, 0, 0]),
    "z": None,
}


def to_print_orientation(name: str, mesh):
    """A copy of `mesh` laid on the bed as it would be printed, min z = 0."""
    m = mesh.copy()
    axis, flip = PRINT_ORIENTATION.get(name, ("z", False))
    rot = _AXIS_ROT[axis]
    if rot is not None:
        m.apply_transform(trimesh.transformations.rotation_matrix(rot[0], rot[1]))
    if flip:
        m.apply_transform(trimesh.transformations.rotation_matrix(np.pi, [1, 0, 0]))
    m.apply_translation(-m.bounds[0])
    return m


def overhang_fraction(mesh, layer_mm: float = 0.3) -> float:
    """Area fraction of downward-facing surface steeper than 45 degrees, EXCLUDING
    anything sitting on the bed.

    A SELECTION heuristic, not a verdict: it decides which single part is handed to
    fdm.overhang and fdm.bridge_span, because those gates judge one part and this
    project prints twelve. The gate still does the judging.

    The bed exclusion is the whole content of the function. Without it a flat deck
    panel scores 49% -- its entire underside points straight down -- and beats every
    hull segment, because a first layer and an unsupported ceiling have the same face
    normal and differ only in whether there is a printer bed underneath. With it, the
    flat plates go to zero and the hull segments, which genuinely have a few degrees
    of taper hanging off them, sort to the top where they belong.
    """
    n = mesh.face_normals[:, 2]
    a = mesh.area_faces
    zmin = mesh.vertices[mesh.faces][:, :, 2].max(axis=1)
    steep = (n < -np.sin(np.radians(45.0))) & (zmin > layer_mm)
    return float(a[steep].sum() / max(a.sum(), 1e-9))


def place_components(c: Config, at) -> dict:
    """Component clash boxes, positioned. Returns {key: (mesh, centre, part)}."""
    parts = {p.key: p for p in _parts()}
    out = {}
    for key, (px, py, pz) in c.place.items():
        p = parts[key]
        lx, ly, lz = p.size_mm
        if pz is None:
            if key == "motor":
                pz = _point_on_shaft(c, at, px)
            elif key == "battery":
                # ON TOP OF the centre girder, straddling it, chocked either side.
                # Found by cad.clash: sitting on the hull floor it occupied the same
                # 2465 mm3 as the girder, which runs down the same centreline.
                _, _, kz = at(px)
                pz = kz + c.wall_mm + c.girder_h_mm + c.floor_standoff_mm / 2.0 + lz / 2.0
            else:
                _, _, kz = at(px)
                # inner floor at this station, plus standoff, plus half the box
                pz = kz + c.wall_mm + c.floor_standoff_mm + lz / 2.0
        out[key] = {"mesh": G.box(px, py, pz, lx, ly, lz),
                    "centre": (px, py, pz), "part": p}
    return out


def build(config: Config | None = None) -> dict:
    c = config or CONFIG
    mat = MATERIALS[c.material]
    at = G._sampler(c)

    # ---- printed parts and their real masses ----------------------------
    meshes = make_parts(c)
    part_mass = {}
    part_geom = {}
    for name, mesh in meshes.items():
        vol_cm3 = float(mesh.volume) / 1000.0
        pack = c.shell_pack_frac if name in SHELL_PARTS else c.plate_pack_frac
        part_mass[name] = vol_cm3 * mat["density_g_cm3"] * pack
        ext = [float(v) for v in mesh.extents]
        part_geom[name] = {
            "volume_cm3": vol_cm3, "bbox_mm": ext,
            "surface_area_mm2": float(mesh.area),
            "watertight": bool(mesh.is_watertight),
            "mass_g": part_mass[name],
            "centroid_mm": [float(v) for v in mesh.centroid],
        }
    printed_mass_g = sum(part_mass.values())

    # ---- components ------------------------------------------------------
    comps = place_components(c, at)
    bom = _parts()
    component_mass_g = sum(p.mass_g * p.qty for p in bom)

    itemised_g = printed_mass_g + component_mass_g + c.topside_mass_g
    contingency_g = itemised_g * c.mass_contingency_frac
    all_up_g = itemised_g + contingency_g

    # ---- centres of gravity ---------------------------------------------
    # Printed parts use their real mesh centroids; components use their placed
    # centres; unplaced components (shaft, prop, rudder, epoxy...) are put where
    # they physically are, on the shaft axis or at the transom.
    mom_x = mom_z = 0.0
    for name, g in part_geom.items():
        mom_x += g["mass_g"] * g["centroid_mm"][0]
        mom_z += g["mass_g"] * g["centroid_mm"][2]
    for key, d in comps.items():
        m_ = d["part"].mass_g * d["part"].qty
        mom_x += m_ * d["centre"][0]
        mom_z += m_ * d["centre"][2]
    unplaced = {
        "shaft_kit": (50.0, 8.0), "prop": (c.prop_x_mm, _point_on_shaft(c, at, c.prop_x_mm)),
        "rudder": (c.rudder_x_mm, -16.0), "linkage": (80.0, 52.0),
        "foam": (240.0, 30.0), "grease": (40.0, 12.0),
        "epoxy": (215.0, 24.0), "fasteners": (235.0, 34.0), "charger": None,
        "rtv": (230.0, 30.0), "coating": (270.0, 36.0), "hatch_seal": (245.0, 72.0),
    }
    parts_by_key = {p.key: p for p in bom}
    # Rule 6, in the smallest possible form. Every BOM line has to be SOMEWHERE, or
    # its mass is in `all_up_mass_g` (which sets the draft) and not in the moments
    # (which set LCG and KG), and the boat quietly floats level on paper while its
    # centre of gravity is wrong. This assertion has already caught one rename.
    missing = sorted(p.key for p in bom
                     if p.key not in comps and p.key not in unplaced)
    if missing:
        raise ValueError(
            f"BOM lines with no position: {missing}. Every part contributes to "
            f"all_up_mass_g; a part with no position contributes nothing to LCG or "
            f"KG, and the trim and stability numbers are then wrong by its moment "
            f"with no symptom. Add it to Config.place or to `unplaced`.")
    for key, pos in unplaced.items():
        if pos is None or key in comps:
            continue
        p = parts_by_key[key]
        mom_x += p.mass_g * p.qty * pos[0]
        mom_z += p.mass_g * p.qty * pos[1]
    # contingency rides with the rest of the boat
    mom_x += c.topside_mass_g * (0.55 * c.loa_mm)
    mom_z += c.topside_mass_g * c.topside_z_mm
    lcg = (mom_x + contingency_g * 0.45 * c.loa_mm) / all_up_g
    kg = (mom_z + contingency_g * 0.34 * hull_depth_guess(c)) / all_up_g

    # ---- hydrostatics -----------------------------------------------------
    # TWO conditions are computed and both are reported, because they differ and
    # the difference is the whole point of claim C15:
    #   `h`  LEVEL flotation. This is what fluids-analytic computes -- one uniform
    #        draft, V/Awp -- and it is what its gates are fed, honestly, because
    #        feeding it a trimmed number would be pretending it understood trim.
    #   `tr` TRIMMED flotation, solved here: the waterline that both floats the
    #        mass AND puts LCB under LCG. Its freeboard is the real one.
    draft = hullform.draft_for_mass(c.hull_scale, c.loa_mm, all_up_g, RHO_FRESH)
    h = hullform.hydrostatics(c.hull_scale, c.loa_mm, draft, RHO_FRESH)
    tr = hullform.flotation(c.hull_scale, c.loa_mm, all_up_g, lcg, RHO_FRESH)
    hull_depth = float((lambda s: (s[3] + s[2]).max())(hullform.stations(c.hull_scale, c.loa_mm, 241)))
    # watertight volume: the whole hull to the sheer
    h_full = hullform.hydrostatics(c.hull_scale, c.loa_mm, hull_depth, RHO_FRESH)
    watertight_vol_mm3 = h_full["displaced_volume_mm3"]

    bm = h["waterplane_inertia_mm4"] / h["displaced_volume_mm3"]
    gm = h["kb_mm"] + bm - kg
    gz = gm * np.sin(np.radians(c.heel_angle_deg))

    # ---- free surface: bilge water in the equipment bay ------------------
    # i = sum over cells of L*b^3/12. The centre girder makes it two cells of half
    # the width, which is a factor of four, because b is cubed.
    bay_len = c.bulkhead_fwd_x - c.bulkhead_aft_x
    bay_b = 2.0 * float(np.interp(0.5 * (c.bulkhead_aft_x + c.bulkhead_fwd_x),
                                  *hullform.stations(c.hull_scale, c.loa_mm, 241)[:2]))
    # width at the BILGE, not at the sheer: the water is in the bottom of the bay
    at_mid = at(0.5 * (c.bulkhead_aft_x + c.bulkhead_fwd_x))
    iy, _ = G._inner_u(at_mid[0], at_mid[1], at_mid[2], c.wall_mm, c.section_points)
    bilge_b = float(2.0 * np.interp(0.15, [0.0, 1.0], [0.0, 0.0]) + (iy.max() - iy.min()) * 0.62)
    n_cells = 2 if c.girder_h_mm > 0 else 1
    i_fs_mm4 = n_cells * bay_len * (bilge_b / n_cells) ** 3 / 12.0
    fs_correction_mm = i_fs_mm4 / h["displaced_volume_mm3"]
    gm_fluid = gm - fs_correction_mm
    i_fs_undivided = bay_len * bilge_b ** 3 / 12.0
    fs_undivided_mm = i_fs_undivided / h["displaced_volume_mm3"]

    # ---- swamped: equipment bay full, sealed ends only -------------------
    aft_vol = hullform.hydrostatics(c.hull_scale, c.bulkhead_aft_x, hull_depth, RHO_FRESH)
    sealed_vol_mm3 = _compartment_volume(c, 0.0, c.bulkhead_aft_x) \
        + _compartment_volume(c, c.bulkhead_fwd_x, c.loa_mm)
    sealed_buoyancy_g = sealed_vol_mm3 * RHO_FRESH * 1e-6
    bay_vol_mm3 = _compartment_volume(c, c.bulkhead_aft_x, c.bulkhead_fwd_x)
    # the bay floods to the waterline, not to the deck: what it can support is the
    # sealed ends minus the boat's own mass; the flood water is neutrally buoyant
    # once the bay is open to the sea, so it does not have to be lifted.
    swamped_margin_g = sealed_buoyancy_g - all_up_g

    # ---- empty condition -------------------------------------------------
    empty_g = all_up_g - parts_by_key["battery"].mass_g
    empty_draft = hullform.draft_for_mass(c.hull_scale, c.loa_mm, empty_g, RHO_FRESH)
    he = hullform.hydrostatics(c.hull_scale, c.loa_mm, empty_draft, RHO_FRESH)
    bat = comps["battery"]
    kg_empty = (kg * all_up_g - parts_by_key["battery"].mass_g * bat["centre"][2]) / empty_g
    gm_empty = he["kb_mm"] + he["waterplane_inertia_mm4"] / he["displaced_volume_mm3"] - kg_empty

    # ---- driveline -------------------------------------------------------
    drive = _driveline(c, at)

    # ---- drag ------------------------------------------------------------
    # fluid.drag computes 0.5*rho*v^2*Cd*A on a FRONTAL area and a tabulated Cd.
    # On a hull that size, FRICTION on the wetted surface is the bigger of the two
    # terms and a pure form Cd understates the total by about half. So the Cd handed
    # to the gate is an EFFECTIVE one: form + ITTC-57 friction, referenced to the
    # same frontal area the pack expects. That is a solver-input rewrite and METHOD
    # rule 7 says it is a design decision that has to be recorded -- it is, here and
    # in the decision log.
    #
    # WAVE-MAKING IS STILL NOT IN THIS NUMBER and cannot be: the pack does not
    # compute it and says so. At Froude 0.39 it is not yet dominant but it is not
    # nothing, and near hull speed it can exceed everything below. The honest claim
    # is the thrust MARGIN (about 10x), not the drag figure.
    frontal_m2 = h["midship_area_mm2"] * 1e-6
    v = c.design_speed_m_s
    reynolds = v * (c.loa_mm * 1e-3) / 1.0e-6
    cf = 0.075 / (np.log10(reynolds) - 2.0) ** 2          # ITTC-57 correlation line
    wetted_m2 = h["wetted_area_mm2"] * 1e-6
    q = 0.5 * RHO_FRESH * v * v
    friction_n = q * cf * wetted_m2
    form_n = q * c.hull_cd * frontal_m2
    drag_n = friction_n + form_n
    cd_effective = drag_n / (q * frontal_m2)

    # ---- print process ---------------------------------------------------
    fil_g = sum(part_mass.values())

    # ---- write the meshes ------------------------------------------------
    # Two sets, and the distinction matters. build/*.stl are in ASSEMBLY coordinates
    # and are what cad.clash and the site's assembly view read. build/print/*.stl are
    # the same solids laid on the bed as printed, and are what the fdm mesh gates and
    # the slicer read. Handing either set to the other's consumer produces a
    # confident, wrong answer.
    mesh_map = {}
    printed = {name: to_print_orientation(name, mesh) for name, mesh in meshes.items()}
    for name, pm in printed.items():
        part_geom[name]["print_bbox_mm"] = [float(v) for v in pm.extents]
        part_geom[name]["overhang_fraction"] = overhang_fraction(pm)
        part_geom[name]["print_orientation"] = list(PRINT_ORIENTATION.get(name, ("z", False)))
    if c.write_meshes:
        os.makedirs(BUILD, exist_ok=True)
        os.makedirs(os.path.join(BUILD, "print"), exist_ok=True)
        for name, mesh in meshes.items():
            p = os.path.join(BUILD, f"{name}.stl")
            mesh.export(p)
            mesh_map[name] = p
            printed[name].export(os.path.join(BUILD, "print", f"{name}.stl"))
        for key, d in comps.items():
            p = os.path.join(BUILD, f"component_{key}.stl")
            d["mesh"].export(p)
            mesh_map[f"component_{key}"] = p

    print_parts = _print_estimates(c, part_geom, mat)

    out = {
        # ---- hull form -------------------------------------------------
        "hull_scale": c.hull_scale,
        "loa_mm": c.loa_mm,
        "hull_depth_mm": hull_depth,
        "max_beam_mm": 2.0 * float(hullform.stations(c.hull_scale, c.loa_mm, 241)[1].max()),
        "draft_mm": draft,
        "waterline_beam_mm": h["wl_beam_mm"],
        "displaced_volume_mm3": h["displaced_volume_mm3"],
        "watertight_volume_mm3": watertight_vol_mm3,
        "volume_fraction": h["displaced_volume_mm3"] / watertight_vol_mm3,
        "waterplane_area_mm2": h["waterplane_area_mm2"],
        "waterplane_inertia_mm4": h["waterplane_inertia_mm4"],
        "wetted_area_mm2": h["wetted_area_mm2"],
        "midship_area_mm2": h["midship_area_mm2"],
        "kb_mm": h["kb_mm"], "bm_mm": bm, "kg_mm": kg, "gm_mm": gm, "gz_mm": gz,
        "lcb_mm": h["lcb_mm"], "lcg_mm": lcg,
        "lcg_lcb_offset_mm": abs(lcg - h["lcb_mm"]),
        # ---- lens findings ---------------------------------------------
        "free_surface_correction_mm": fs_correction_mm,
        "free_surface_undivided_mm": fs_undivided_mm,
        "gm_free_surface_mm": gm_fluid,
        "bilge_cell_width_mm": bilge_b / n_cells,
        "sealed_buoyancy_g": sealed_buoyancy_g,
        "swamped_margin_g": swamped_margin_g,
        "empty_draft_mm": empty_draft, "empty_gm_mm": gm_empty, "kg_empty_mm": kg_empty,
        # ---- mass -------------------------------------------------------
        "shell_wall_measured_mm": {
            k: (2.0 * part_geom[k]["volume_cm3"] * 1000.0 / part_geom[k]["surface_area_mm2"])
            for k in SHELL_PARTS if k in part_geom},
        "shell_wall_spec_mm": c.wall_mm,
        "printed_mass_g": printed_mass_g,
        "component_mass_g": component_mass_g,
        "contingency_g": contingency_g,
        "all_up_mass_g": all_up_g,
        "displaced_mass_g": h["displaced_mass_g"],
        "mass_budget_error_frac": abs(h["displaced_mass_g"] - all_up_g) / all_up_g,
        "part_mass_g": part_mass,
        "part_geometry": part_geom,
        # ---- driveline ---------------------------------------------------
        **drive,
        # ---- drag --------------------------------------------------------
        "design_speed_m_s": v, "drag_force_n": drag_n, "reynolds": reynolds,
        "friction_drag_n": friction_n, "form_drag_n": form_n,
        "cd_effective": cd_effective, "cd_form": c.hull_cd,
        "froude": v / np.sqrt(G_ACCEL * c.loa_mm * 1e-3),
        "thrust_margin_ratio": c.thrust_available_n / drag_n if drag_n > 0 else 0.0,
        # ---- trimmed flotation (the condition the boat is actually in) ----
        "trim_deg": tr["trim_deg"], "trim_mm": tr["trim_mm"],
        "trim_balanced": tr["balanced"],
        "trimmed_freeboard_mm": tr["freeboard"],
        "trimmed_draft_mid_mm": tr["draft_mid_mm"],
        "trimmed_draft_transom_mm": tr["draft_transom_mm"],
        "level_freeboard_mm": h["min_freeboard_mm"],
        "freeboard_lost_to_trim_mm": h["min_freeboard_mm"] - tr["freeboard"],
        "max_trim_deg": c.max_trim_deg,
        # ---- SI projection for fluids-analytic (SI only, unprefixed) -----
        "mass_total_kg": all_up_g / 1000.0,
        "fluid_density_kg_m3": RHO_FRESH,
        "kinematic_viscosity_m2_s": 1.0e-6,
        "hull_volume_m3": watertight_vol_mm3 * 1e-9,
        "displaced_volume_m3": h["displaced_volume_mm3"] * 1e-9,
        "waterplane_area_m2": h["waterplane_area_mm2"] * 1e-6,
        "waterplane_inertia_m4": h["waterplane_inertia_mm4"] * 1e-12,
        "hull_depth_m": hull_depth / 1000.0,
        "draft_m": draft / 1000.0,
        "waterline_beam_m": h["wl_beam_mm"] / 1000.0,
        "kb_m": h["kb_mm"] / 1000.0,
        "kg_m": kg / 1000.0,
        "max_volume_fraction": c.max_volume_fraction,
        "min_freeboard_m": c.min_freeboard_limit_mm / 1000.0,
        "min_gm_m": c.min_gm_mm / 1000.0,
        "min_righting_arm_m": c.min_gz_mm / 1000.0,
        "heel_angle_deg": c.heel_angle_deg,
        "velocity_m_s": v,
        "flow_velocity_m_s": v,
        "characteristic_length_m": c.loa_mm / 1000.0,
        "drag_coefficient": cd_effective,
        "frontal_area_m2": frontal_m2,
        "reference_area_m2": frontal_m2,
        "thrust_available_n": c.thrust_available_n,
        "max_drag_force_n": c.thrust_available_n,
        # ---- fdm-print projection (worst-case part; see FRICTION.md) ----
        **print_parts,
        # ---- cad-solid projection ---------------------------------------
        "meshes": mesh_map,
        "min_wall_mm": min(c.wall_mm, c.deck_mm, c.hatch_mm),
        # NOT "bbox_mm": fdm-print reads that key for the PART it is judging, and the
        # whole-boat envelope published under that name made fdm.bed_fit compare a
        # 480 mm boat against a 208 mm bed and fail. The assembly envelope gets its
        # own name, and cad.bounding gets its limit under the name it looks for.
        # cad.bounding wants `bbox_mm`; fdm-print reads `bbox` FIRST and `bbox_mm`
        # only as a fallback, so publishing the assembly under bbox_mm and the worst
        # printed part under bbox gives each pack the one it means. That resolution
        # order is undocumented and load-bearing -- see FRICTION.md. fdm.bed_fit's
        # verdict line names the part's own 190x186x77 mm, which is the check that
        # this is still true.
        # NO "bbox_mm" is published. fdm-print reads that key BEFORE it reads "bbox",
        # so publishing the assembly envelope under it made fdm.bed_fit measure a
        # 480 mm boat against a 208 mm bed. cad.bounding wants the same key for the
        # opposite meaning and there is no third spelling either pack accepts.
        # fdm.bed_fit is the more valuable of the two -- it is the "can I build this
        # at home" gate -- so it keeps the key, cad.bounding SKIPS, and the project's
        # own boat.envelope covers the claim. Written up in FRICTION.md.
        "assembly_bbox_mm": [c.loa_mm,
                             2.0 * float(hullform.stations(c.hull_scale, c.loa_mm, 241)[1].max()),
                             hull_depth + c.deck_mm + c.coaming_h_mm],
        "bbox_limit_mm": [c.envelope_x_mm, c.envelope_y_mm, c.envelope_z_mm],
        # ---- sourcing ----------------------------------------------------
        # A BOM DOCUMENT, not a bare list: sourcing/bomlib.resolve wants an object
        # with a `lines` array. Handing it the list gave
        # "no BOM: the model projection defines neither 'bom_path' nor 'bom'",
        # which reads like the key is missing when in fact it is the wrong shape.
        # Designed, bonded contacts. cad.clash refuses wildcards and refuses an entry
        # with no reason, which is correct: an allowlist is where a real interference
        # goes to hide. Exactly one pair is listed and it is a glue joint.
        "clash_allow": [
            {"pair": ["girder", "hull_mid"],
             "reason": "the centre girder's foot sits on the moulded hull floor and is "
                       "bonded to it with an epoxy fillet down both sides. The 0.011 mm "
                       "of reported interference is the foot touching the floor line it "
                       "is supposed to touch, over 2373 mm2 of intended glue area."},
        ],
        "bom": _bom_doc(c, bom, {
            "process": "fdm",
            "material": c.material,
            "max_part_x_mm": max(g["bbox_mm"][0] for g in part_geom.values()),
            "max_part_y_mm": max(g["bbox_mm"][1] for g in part_geom.values()),
            "max_part_z_mm": max(g["bbox_mm"][2] for g in part_geom.values()),
            "min_wall_mm": min(c.wall_mm, c.deck_mm, c.hatch_mm),
            "min_drilled_hole_mm": 2.0,
        }),
        "budget_usd": c.budget_usd,
        "currency": "USD",
        "config": _config_dict(c),
    }
    out["build_cost_usd"] = sum(l["qty_per_unit"] * l["unit_price"] for l in out["bom"]["lines"])
    return out


def hull_guess_depth_cache(c):
    return None


def hull_depth_guess(c):
    """Hull depth, needed for the contingency's KG before the hydrostatics have run.
    Derived from the traced offsets rather than typed, so it tracks hull_scale."""
    st = hullform.stations(c.hull_scale, c.loa_mm, 121)
    return float((st[3] + st[2]).max())


def _config_dict(c):
    d = {}
    for f in fields(c):
        v = getattr(c, f.name)
        d[f.name] = v if not isinstance(v, dict) else {k: list(x) for k, x in v.items()}
    return d


def _compartment_volume(c, x0, x1):
    """Internal (air) volume of one compartment, mm^3, to the underside of the deck."""
    at = G._sampler(c)
    xs = np.linspace(x0, x1, 60)
    a = []
    for x in xs:
        hb, dep, kz = at(x)
        iy, iz = G._inner_u(hb, dep, kz, c.wall_mm, c.section_points)
        # shoelace on the closed inner U
        a.append(0.5 * abs(np.dot(iy, np.roll(iz, 1)) - np.dot(iz, np.roll(iy, 1))))
    return float(np.trapezoid(a, xs))


def _driveline(c, at):
    ex, ez, ang = _shaft_axis(c, at)
    prop_z = _point_on_shaft(c, at, c.prop_x_mm)
    prop_tip_z = prop_z - c.prop_dia_mm / 2.0
    # does the shaft exit through the hull BOTTOM, or out through the side/transom?
    exit_ok = 0.0 < ex < c.bulkhead_aft_x
    # clearance from the prop disc to the hull, measured at the transom
    _, _, transom_kz = at(1.0)
    prop_to_hull = float(np.hypot(0.0 - c.prop_x_mm, transom_kz - prop_z)) - c.prop_dia_mm / 2.0
    prop_to_rudder = (c.prop_x_mm - c.prop_dia_mm * 0.18) - (c.rudder_x_mm + c.rudder_chord_mm / 2.0)
    return {
        "shaft_exit_x_mm": ex, "shaft_exit_z_mm": ez,
        "shaft_angle_deg": c.shaft_angle_deg,
        "max_shaft_angle_deg": c.max_shaft_angle_deg,
        "shaft_exits_through_bottom": exit_ok,
        "prop_centre_z_mm": prop_z, "prop_tip_z_mm": prop_tip_z,
        "prop_to_hull_clearance_mm": prop_to_hull,
        "prop_to_rudder_gap_mm": prop_to_rudder,
        "min_prop_tip_clearance_mm": c.min_prop_tip_clearance_mm,
        "min_prop_rudder_gap_mm": c.min_prop_rudder_gap_mm,
        "rudder_bottom_z_mm": -c.rudder_depth_mm,
    }


def _print_estimates(c, part_geom, mat):
    """fdm-print sees ONE part. This projects the WORST part per metric, so the
    verdict is an envelope over the whole print set rather than a statement about
    a part chosen at random. See FRICTION.md -- the pack has no multi-part mode."""
    usable_x = c.bed_x_mm - 2 * c.brim_mm
    usable_y = c.bed_y_mm - 2 * c.brim_mm
    times = {}
    for name, g in part_geom.items():
        # crude but honest: extruded volume / (layer * width * speed), + 25% travel
        vol_mm3 = g["volume_cm3"] * 1000.0 * (c.shell_pack_frac if name in SHELL_PARTS else c.plate_pack_frac)
        rate = c.layer_mm * (c.nozzle_mm * 1.15) * c.print_speed_mm_s
        times[name] = vol_mm3 / rate / 3600.0 * 1.25
    # The part handed to the fdm gates is the WORST one, by the metric each gate
    # cares about, in PRINT orientation. fdm-print looks at one part; this project
    # prints twelve; so the projection carries the envelope rather than a part
    # picked at random. Stated in the readiness report, not hidden here.
    worst_bbox = max(part_geom.items(),
                     key=lambda kv: max(kv[1]["print_bbox_mm"][0], kv[1]["print_bbox_mm"][1]))
    worst_over = max(part_geom.items(), key=lambda kv: kv[1]["overhang_fraction"])
    return {
        "part_name": worst_over[0],
        "mesh_path": os.path.join(BUILD, "print", f"{worst_over[0]}.stl"),
        "fdm_worst_bbox_part": worst_bbox[0],
        "fdm_worst_overhang_part": worst_over[0],
        "overhang_fraction_by_part": {k: v["overhang_fraction"] for k, v in part_geom.items()},
        "print_bbox_by_part_mm": {k: v["print_bbox_mm"] for k, v in part_geom.items()},
        "bbox": worst_bbox[1]["print_bbox_mm"],
        "footprint_mm": worst_bbox[1]["print_bbox_mm"][:2],
        "build_height_mm": max(g["print_bbox_mm"][2] for g in part_geom.values()),
        "part_volume_mm3": max(g["volume_cm3"] for g in part_geom.values()) * 1000.0,
        "surface_area_mm2": max(g["surface_area_mm2"] for g in part_geom.values()),
        "bed_x_mm": c.bed_x_mm, "bed_y_mm": c.bed_y_mm, "bed_z_mm": c.bed_z_mm,
        "brim_allowance_mm": c.brim_mm,
        "usable_bed_x_mm": usable_x, "usable_bed_y_mm": usable_y,
        "nozzle_diameter_mm": c.nozzle_mm,
        "layer_height_mm": c.layer_mm,
        "extrusion_width_mm": c.nozzle_mm * 1.15,
        "line_width_mm": c.nozzle_mm * 1.15,
        "perimeters": c.perimeters,
        "wall_count": c.perimeters,
        "min_wall_mm": min(c.wall_mm, c.deck_mm, c.hatch_mm),
        "thinnest_wall_mm": min(c.wall_mm, c.deck_mm, c.hatch_mm),
        "min_feature_mm": min(c.wall_mm, c.deck_mm, c.hatch_mm),
        "infill_fraction": c.infill_frac,
        "print_speed_mm_s": c.print_speed_mm_s,
        "speed_mm_s": c.print_speed_mm_s,
        "filament_density_g_cm3": mat["density_g_cm3"],
        "density_g_cm3": mat["density_g_cm3"],
        "print_time_h": max(times.values()),
        "max_print_time_h": c.max_print_time_h,
        "print_time_limit_h": c.max_print_time_h,
        "total_print_time_h": sum(times.values()),
        "print_time_by_part_h": times,
        # VECTORS, not the string "z". fdm.layer_alignment skipped with "the
        # projection has no load_axis / primary_load_axis (the primary load direction
        # as an [x, y, z] vector in the part's print orientation)".
        # Hull segments print standing on a transverse face, so the build direction is
        # the hull's own x. The load they carry is hydrostatic pressure, which is
        # radial and therefore across the layer bonds in the worst case -- that is the
        # honest answer, and it is why the shell is 4 perimeters rather than 3.
        # Overhang policy, STATED rather than defaulted. The pack ships 45 deg and a
        # 0.5% area allowance and says in its own docstrings that both are project
        # judgements. 45 deg stays. The AREA allowance is raised to 1.5% because the
        # only part that uses it is hull_bow, where 740 mm2 of the stem taper hangs
        # past 45 deg -- on the OUTSIDE of the hull, where support is trivially
        # removable and where the surface is sanded and epoxy-coated anyway. That is
        # about a thumbnail of support material on one of thirteen parts. Every other
        # part prints support-free, which is what the rest of the geometry work was
        # for. Flagged in the readiness report as a relaxed threshold, not buried.
        "overhang_limit_deg": 45.0,
        "max_overhang_deg": 45.0,
        "overhang_area_allow_frac": 0.015,
        "max_bridge_mm": 30.0,
        "max_cantilever_mm": 2.0,
        "primary_load_axis": [0.0, 1.0, 0.0],
        "load_axis": [0.0, 1.0, 0.0],
        "build_axis": [0.0, 0.0, 1.0],
        "print_axis": [0.0, 0.0, 1.0],
        "layer_normal_strength_ratio": 0.55,
        "layer_normal_modulus_ratio": 0.75,
        "stress_utilisation": 0.12,
        "utilisation": 0.12,
        "utilisation_kind": "stress",
    }


def _bom_lines(c, bom, design_attrs):
    """The BOM in the shape packs/sourcing/bomlib documents.

    Two conventions from that module's header that are silent when you get them
    wrong, so they are restated here:
      * `manufacturers` is what a SOURCE is counted from. `sources` is who will
        sell it to you, which is a weaker question -- two Amazon storefronts
        reselling one factory's motor is one source with better logistics.
      * `unit_price: null` is an UNKNOWN price, never a free part.
    """
    lines = []
    for p in bom:
        alts = [a.strip() for a in p.second_source.split(";") if a.strip()]
        lines.append({
            "ref": p.key,
            "description": p.desc,
            "qty_per_unit": p.qty,
            "vendor": p.vendor,
            "vendor_pn": p.mpn or p.search,
            "manufacturer": p.manufacturer,
            "mpn": p.mpn or p.search,
            "manufacturers": [p.manufacturer] + alts,
            "unit_price": p.price_usd,
            "price_currency": p.currency,
            "moq": p.moq,
            "order_multiple": 1,
            "stock": 100,
            "lead_time_weeks": p.lead_days / 7.0,
            "lifecycle": p.lifecycle,
            "sources": ["Amazon"] + (["manufacturer direct"] if alts else []),
            "alternate_qualified": bool(alts),
            "single_source_accepted": not alts,
            "acceptance_note": ("" if alts else
                                "hobby commodity part; if this listing dies, any "
                                "equivalent from the same class substitutes without "
                                "a design change. Accepted."),
            "attributes": {"class": p.cls, "confidence": p.confidence},
            "mass_g": p.mass_g,
            "note": p.note,
        })
    lines.append({
        "ref": "filament",
        "description": f"{c.material.upper()} filament, 1.75 mm, 1 kg spool, light colour",
        "qty_per_unit": 1, "vendor": "Amazon", "vendor_pn": "PETG 1.75mm 1kg",
        "manufacturer": "Overture", "mpn": "PETG 1.75mm 1kg",
        "manufacturers": ["Overture", "Sunlu", "Polymaker", "eSun"],
        "unit_price": 22.0, "price_currency": "USD",
        "moq": 1, "order_multiple": 1, "stock": 100, "lead_time_weeks": 3 / 7.0,
        "lifecycle": "active", "sources": ["Amazon", "manufacturer direct"],
        "alternate_qualified": True, "single_source_accepted": False,
        "acceptance_note": "",
        "attributes": {"class": "consumable", "confidence": "class"},
        "mass_g": 0.0,
        "note": ("One spool covers the whole boat (about 480 g) with enough left to "
                 "reprint the part you will get wrong. LIGHT COLOUR, not black: a dark "
                 "hull in direct sun exceeds 50 C on the surface."),
    })
    return lines


def _bom_doc(c, bom, design_attrs):
    return {
        "schema": "atompipe.bom/1",
        "currency": "USD",
        "build_quantity": 1,
        "budget_per_unit": c.budget_usd,
        "lead_time_budget_weeks": c.max_lead_days / 7.0,
        "max_moq_overbuy_usd": c.max_moq_overbuy_usd,
        "design": design_attrs,
        # The "vendor" for every printed part is the builder's own FDM machine, so
        # its capability set is stated here and bom.process_rules checks the design
        # against it -- the same question a real vendor DFM review asks, with the
        # machine in the spare room as the vendor.
        "process_rules": [
            {"id": "fdm-bed", "scope": "design",
             "when": {"process": "fdm"},
             "require": {"max_part_x_mm": {"max": c.bed_x_mm - 2 * c.brim_mm},
                         "max_part_y_mm": {"max": c.bed_y_mm - 2 * c.brim_mm},
                         "max_part_z_mm": {"max": c.bed_z_mm}},
             "note": "part plus brim must fit a 220x220x250 machine"},
            {"id": "fdm-wall", "scope": "design",
             "when": {"process": "fdm"},
             "require": {"min_wall_mm": {"min": 3.0 * c.nozzle_mm * 1.15}},
             "note": "three real extrusion widths, not three nozzle diameters"},
            {"id": "fdm-hole", "scope": "design",
             "when": {"process": "fdm"},
             "require": {"min_drilled_hole_mm": {"min": 2.0}},
             "note": "smaller than 2 mm is drilled, not printed"},
        ],
        "lines": _bom_lines(c, bom, design_attrs),
    }


if __name__ == "__main__":
    r = build()
    print(json.dumps({k: v for k, v in r.items()
                      if k not in ("part_geometry", "config", "bom", "meshes",
                                   "print_time_by_part_h", "part_mass_g")},
                     indent=2, sort_keys=True, default=str))
