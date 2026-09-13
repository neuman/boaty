# boaty — readiness (v0.1, 2026-09-13T02:27:38Z)

**v0.1 is NOT ready: 1 of 34 critical claims is unsettled — 1 failing (C8).** 20 of 34 claims are machine-verified against the current model. It is unverified in physical hardware: 5 claims need a real object (P1, P2, P3, P4, +1 more).

## What is PROVEN (machine-verified this run)

| Claim | Acceptance | Measured | Gate | Evidence |
|---|---|---|---|---|
| **C1** Floats at all-up mass consuming no more than 55% of the watertight hull volume | displaced volume fraction <= 0.55 | 0.3436 V_displaced/V_hull | `fluid.buoyancy` | *none written* |
| **C2** Deck edge stands at least 25 mm above the loaded waterline at the lowest point | freeboard >= 25.0 mm | 0.0496 m | `fluid.freeboard` | *none written* |
| **C3** Initial metacentric height GM is at least 15 mm at the loaded waterline | GM >= 15.0 mm | 0.0615 m | `fluid.metacentric` | *none written* |
| **C4** Righting arm GZ at 8 degrees of heel is at least 2 mm | GZ at 8 deg >= 2.0 mm | 0.0086 m | `fluid.righting_arm` | *none written* |
| **C5** Hull drag at the 0.8 m/s design speed is inside the static thrust the motor and propeller produce | drag force <= 3.0 N | 0.2714 N; 384000 Re | `fluid.drag`, `fluid.flow_regime` | *none written* |
| **C6** The drag correlation is being used inside the Reynolds range it was fitted over | Reynolds validity == 1.0 | 384000 Re | `fluid.flow_regime` | *none written* |
| **C7** Every printed part fits a 220x220x250 mm build volume with brim, carries at least 3 extrusion widths of wall, bridges n… | printability == 1.0 | 0.962 utilisation; 1.4 mm; 0.12 derated utilisation; 0.962 of limit; 0 problems; 0.00249 area fraction; 0 mm | `fdm.bed_fit`, `fdm.min_wall`, `fdm.layer_alignment`, `fdm.print_time_est`, `fdm.process_model_valid`, `fdm.overhang`, `fdm.bridge_span` | `/home/neuman/Documents/work/boaty/.atompipe/out/fdm-bed-fit-parts.txt`, `/home/neuman/Documents/work/boaty/.atompipe/out/fdm-overhang.txt` |
| **C9** No interference between the hull, the deck, and the placed motor, battery, ESC, servo, receiver and driveline | part interference == 0.0 clashing pairs | 0 pairs | `cad.clash` | `/home/neuman/Documents/work/boaty/.atompipe/out/cad-solid/clash_pairs.json` |
| **C10** The assembled boat fits inside a 560 x 230 x 170 mm envelope | bounding box <= 560.0 mm | 0.8571 utilisation; 0.857 fraction | `cad.bounding`, `boat.envelope` | *none written* |
| **C11** Every BOM line is orderable, priced in one currency, and has a known ship date | unorderable lines == 0.0 lines | 0 lines; 0 weeks; 0 lines | `bom.complete`, `bom.availability`, `bom.currency` | `/home/neuman/Documents/work/boaty/.atompipe/out/bom_complete.json`, `/home/neuman/Documents/work/boaty/.atompipe/out/bom_availability.json`, `/home/neuman/Documents/work/boaty/.atompipe/out/bom_currency.json` |
| **C12** Total build cost, excluding the printer, is at most 400 USD | rolled-up build cost <= 400.0 USD | 397.5 USD/unit | `bom.cost` | `/home/neuman/Documents/work/boaty/.atompipe/out/bom_cost.json` |
| **C13** No line forces a minimum-order overbuy worth more than 25 USD, and single-source risk is counted | MOQ overbuy <= 25.0 USD | 0 USD; 0 violations; 0 lines | `bom.moq`, `bom.process_rules`, `bom.single_source` | `/home/neuman/Documents/work/boaty/.atompipe/out/bom_moq.json`, `/home/neuman/Documents/work/boaty/.atompipe/out/bom_process_rules.json`, `/home/neuman/Documents/work/boaty/.atompipe/out/bom_single_source.json` |
| **C14** The wall thickness of every generated hull shell, measured from the exported mesh itself, matches the wall the model sp… | generated-vs-specified wall disagreement <= 0.15 fraction | 0.064 fraction | `boat.wall_agreement` | *none written* |
| **C15** The boat floats within 1.5 degrees of level, and the freeboard that survives the trim is still at least 25 mm | trim angle <= 1.5 deg | 0.867 deg | `boat.trim` | *none written* |
| **C16** The propeller shaft line leaves the hull through the hull bottom, the propeller disc clears the hull and the rudder, an… | driveline geometry violations == 0.0 violations | 0 violations | `boat.driveline` | *none written* |
| **C17** GM corrected for the free surface of bilge water in the equipment bay stays at least 10 mm | GM after free-surface correction >= 10.0 mm | 57.85 mm | `boat.free_surface` | *none written* |
| **C18** With the equipment bay completely flooded, the sealed fore and aft compartments still support the all-up mass plus the… | swamped freeboard >= 0.0 mm | 508.3 g | `boat.swamped` | *none written* |
| **C19** The hull is upright-stable and adequately floating in the EMPTY condition too, not only at design load | empty-condition GM >= 10.0 mm | 62.29 mm | `boat.empty` | *none written* |
| **C20** Every hole through the hull shell or a watertight bulkhead is enumerated with a sealing method, and at most one of them… | penetrations below the waterline <= 1.0 penetrations | 1 shell holes below waterline | `boat.hull_penetrations` | *none written* |
| **C21** Every drive and steering chain is continuous: no consecutive pair of members is more than 1 mm apart | worst gap in a drive or steering chain <= 1.0 mm | 0 mm; 0.3 mm | `boat.linkage_closed`, `cad.assembly_connected` | `/home/neuman/Documents/work/boaty/.atompipe/out/cad-solid/assembly_connected.json` |

Every row above is backed by at least one gate that actually ran and returned a pass — a skipped, errored or never-run gate can never be the evidence for a row. Where another gate also covers the claim and did **not** produce a pass, the row is marked **PARTIAL** and names it with the reason: the claim stands on the gates that ran, and you can see which ones did not.

## What is NOT verified

These need the real object. No gate in any pack can settle them, and no number of passing gates above changes that.

- **P1** The printed hull, the hull/deck joint and the stuffing tube keep the inside dry for a 30 minute run
  - **Test that would settle it:** measure water ingress <= 5.0 ml in 30 min on the built object and compare against the acceptance
  - **Why it matters:** No CFD run makes a printed seam watertight. FDM layer lines leak by capillary action even when the mesh is perfectly closed, and the shaft gland leaks by design unless it is greased. This is settled…
  - **Record the result:** `atompipe claim physical P1 --pass|--fail --detail "..." --when <ISO date>`
- **P2** The radio holds control to at least 50 m over open water
  - **Test that would settle it:** measure control range >= 50.0 m on the built object and compare against the acceptance
  - **Why it matters:** Water reflects, the receiver sits inside a closed hull, and antenna placement decides this. Only a range test settles it.
  - **Record the result:** `atompipe claim physical P2 --pass|--fail --detail "..." --when <ISO date>`
- **P3** Motor, ESC and battery stay under 60 C after a continuous 10 minute run
  - **Test that would settle it:** measure component temperature <= 60.0 deg C on the built object and compare against the acceptance
  - **Why it matters:** A sealed hull has no airflow. The thermal-analytic pack could model a steady-state lumped rise, but the inputs (real motor efficiency at this load, real internal air movement) are guesses, so a green…
  - **Record the result:** `atompipe claim physical P3 --pass|--fail --detail "..." --when <ISO date>`
- **P4** The boat holds a straight course without constant correction and turns inside a 2 m radius
  - **Test that would settle it:** measure turning radius <= 2.0 m on the built object and compare against the acceptance
  - **Why it matters:** Directional stability is a dynamic, free-running property. Nothing in any installed pack computes yaw stability, and a CFD install would not settle it either without a 6-DOF manoeuvring model. A pond…
  - **Record the result:** `atompipe claim physical P4 --pass|--fail --detail "..." --when <ISO date>`
- **P5** The hull does not warp off the print bed and the two hull halves actually mate
  - **Test that would settle it:** measure joint gap <= 0.3 mm on the built object and compare against the acceptance
  - **Why it matters:** Warp is a function of the machine, the enclosure, the ambient temperature and the filament batch. A printability gate says the geometry is printable; it does not say your printer will print it.
  - **Record the result:** `atompipe claim physical P5 --pass|--fail --detail "..." --when <ISO date>`

## Open gaps

None. Every measurable claim has at least one gate registered against it.

## Standing constraints

Carried on faith. None of this is proven; all of it is visible, which is the whole trade.

### Assumptions

- **A1** The hull shape pixel-traced from the screenshot is within +/-1.5 mm of the hull the design tool actually holds
  - The source is a PNG, not a file. Three independent scale estimates agree to 2.1%, which bounds the systematic error, but the curve traces are 4-5 px thick at 0.235 mm/px. If the user can export an STL or offsets from th…
- **A2** Component masses are the vendor listed figures and are within +/-15% of the parts that arrive
  - Listed masses on marketplace hobby parts are frequently the bare component without leads, connectors or mounting hardware. The mass budget carries a contingency line for this.
- **A3** The vertical centre of gravity is estimated from the placed component positions, not weighed
  - KG is the input GM is most sensitive to and the one nobody measures. C3 asks for 15 mm of GM against a pack default of 6.6 mm specifically to absorb this.
- **A4** PETG at 1.27 g/cm3. Printed part mass is mesh volume times a packing fraction: 1.00 for the hull shells, which are mode…
  - Getting this backwards is a 2x error on the mass every hydrostatic number depends on. A 1.4-2.0 mm slab at 4 perimeters and 0.24 mm layers is mostly perimeter and solid skin, so 0.88 rather than the 15% infill setting.…
- **A5** Design speed 0.8 m/s. Above that this hull is at or past hull speed and every drag number in this project stops meaning…
  - Hull speed for a 480 mm waterline is 1.25*sqrt(0.48) = 0.87 m/s, and 0.8 m/s is Froude 0.37. fluids-analytic computes no wave-making resistance, says so in its own PACK.md, and becomes a statement about a boat at rest a…
- **A6** Static thrust from the 35 mm propeller on the 80-turn motor at 7.4 V is at least 3.0 N
  - The weakest number in the drag chain and the only one with no source at all: a class figure, not a measurement and not a manufacturer curve. The MARGIN is what makes it survivable - computed resistance at the design spe…
- **A7** The equipment bay stays dry enough that bilge water is a few millimetres at most; the free-surface correction in C17 is…
  - C18 covers the fully flooded case separately and by a different mechanism (sealed, foam-filled end compartments). C17 is the small-water case: a stiffness question, not a flotation one. Conflating the two is how a boat…
- **A8** Print settings are a 0.4 mm nozzle, 0.24 mm layers, 4 perimeters, 15% infill, 60 mm/s, on a 220x220x250 mm class machine
  - Every printability verdict is against these. A 0.6 mm nozzle changes the minimum printable wall and therefore the deck thickness; a 180x180 bed does not fit hull_mid at all. Stated so the verdicts mean something to a re…

### Parameters with no recorded rationale

A number nobody can defend is a number the next agent will change — and then re-litigate, and then change back. `atompipe why <param>` is empty for each of these.

| Param | Value | Source | Protected by |
|---|---|---|---|
| `screw_d_mm` | 3 | *unsourced* | — |
| `screw_head_d_mm` | 5.5 | *unsourced* | — |
| `tube_inboard_x_mm` | 156 | *unsourced* | — |
| `shaft_d_mm` | 4 | *unsourced* | — |
| `coupler_d_mm` | 12 | *unsourced* | — |
| `coupler_len_mm` | 25 | *unsourced* | — |
| `prop_hub_d_mm` | 8 | *unsourced* | — |
| `prop_hub_len_mm` | 14 | *unsourced* | — |
| `rudder_stock_d_mm` | 3 | *unsourced* | — |
| `rudder_tiller_mm` | 20 | *unsourced* | — |
| `pushrod_d_mm` | 3.2 | *unsourced* | — |
| `pushrod_tube_od_mm` | 5 | *unsourced* | — |
| `pushrod_y_mm` | -50 | *unsourced* | — |
| `min_freeboard_mm` | 25 | *unsourced* | — |

## Failing / blocked

### [FAIL ] C8 — Every exported solid is a closed, correctly-wound, non-degenerate volume with no wall thinner than 1.2 mm  *(fail, critical)*
- **Acceptance:** mesh validity == 1.0
- `[ok  ] cad.watertight : 0 bad edge(s) across 31 part(s), limit 0 — worst component_battery: 0 open, 0 non-manifold of 12 faces; 31 part(s) welded at 0.0001 mm on load (component_battery, component_esc, component_motor...) — a soup format has no vertex identity of its own`
- `[ok  ] cad.is_volume : 0 of 31 part(s) are not volumes, limit 0 (total 710347 mm^3 enclosed); 31 part(s) welded at 0.0001 mm on load (component_battery, component_esc, component_motor...) — a soup format has no vertex identity of its own`
- `[ok  ] cad.degenerate_faces : 0 repair(s) needed across 31 part(s), limit 0 — worst component_battery: welded 0 vertex/vertices at 0.0001 mm, dropped 0 face(s) below 1e-08 mm^2 over 1 pass(es); 31 part(s) welded at 0.0001 mm on load (component_battery, component_esc, component_motor...) — a soup format has no vertex identity of its own`
- `[FAIL] cad.wall_thickness : thinnest wall 0.000 mm on hull_mid at (302.486, -50.4, 13.345) vs 1.400 mm minimum [min_wall_mm] (17300/17304 inward face-normal rays hit; sampler, not a proof)`
  - evidence: `/home/neuman/Documents/work/boaty/.atompipe/out/cad-solid/wall_thickness.json`

### Gates that produced no proof

- `[skip] fluid.pipe_pressure_drop : model provides no bore: one of pipe_diameter_m, inner_diameter_m, bore_m, hydraulic_diameter_m, duct_diameter_m, pipe_id_m (m, INTERNAL diameter - nominal pipe size is not a bore)`  *(skipped; claims: pressure-drop, head-loss, pipe-flow)*

A gate that did not run is not a gate that passed. Until each of these produces a verdict, the claims they cover rest on whatever else happened to run.

## Reproduce

This file is generated. Re-derive every row above with:

```sh
atompipe check --tier 0          # the inner loop: analytic gates only, seconds
atompipe check --tier 1          # everything registered
atompipe report --write          # regenerates docs/readiness.md
```

One gate at a time — this is the command behind each row:

```sh
atompipe check --only fluid.drag                 # drag, resistance
atompipe check --only fluid.pipe_pressure_drop   # pressure-drop, head-loss, pipe-flow
atompipe check --only fluid.flow_regime          # flow-regime, drag, resistance, pressure-drop, head-loss, pipe-flow
atompipe check --only fluid.buoyancy             # buoyancy, flotation, displacement
atompipe check --only fluid.freeboard            # freeboard, reserve-buoyancy
atompipe check --only fluid.metacentric          # stability, metacentric-height
atompipe check --only fluid.righting_arm         # righting-arm, stability-margin
atompipe check --only cad.bounding               # geometry, envelope, packaging, mechanical, cad
atompipe check --only fdm.bed_fit                # manufacturability, fdm, additive, printability
atompipe check --only fdm.min_wall               # manufacturability, fdm, additive, printability
atompipe check --only fdm.layer_alignment        # manufacturability, fdm, additive, structural, printability
atompipe check --only fdm.print_time_est         # manufacturability, fdm, additive, cost, printability
atompipe check --only fdm.process_model_valid    # manufacturability, fdm, additive, printability, structural, process-validity
atompipe check --only bom.complete               # sourcing, procurement, bom, cost, availability, supply-chain
atompipe check --only bom.cost                   # cost, build-cost, budget, unit-cost
atompipe check --only bom.availability           # availability, lead-time, ship-date, stock
# ... and 22 more; `atompipe gate list` prints them all
```

And prove the gates above can actually fail, which is the only reason their passes mean anything:

```sh
atompipe gate selftest           # runs every negative control; a gate that passes its
                                 # own known-bad fixture is a logger, not a gate
```

Run reproduced here: recorded 2026-09-13T02:27:38Z, tier 1 (build), 8.7s, model `60f8ae10da3b`, inputs `862ca0d1d6d9`, atompipe 0.1.0.
A different model hash reproduces a different claim, not a different result.

---

*Generated by `atompipe report` from `.atompipe/ledger.json`. Do not hand-edit: it is an output, not a source. If a line here is wrong, the ledger is wrong.*
