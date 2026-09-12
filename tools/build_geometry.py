#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Write the STLs from the model. Nothing here decides anything.

    build/*.stl        assembly coordinates -- what cad.clash and the viewer read
    build/print/*.stl  laid on the bed as printed -- what the fdm gates and your
                       slicer read

`atompipe check` calls model/boat.py's build() itself and writes the same files, so
this exists for the times you want the geometry without a gate sweep -- and because
tools/render.py needs the files to exist before it can draw them.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "model"))
import boat  # noqa: E402

if __name__ == "__main__":
    r = boat.build(boat.Config())
    printed = [k for k in r["part_geometry"]]
    print(f"{len(printed)} printed part(s), {r['printed_mass_g']:.0f} g, "
          f"{r['total_print_time_h']:.1f} h estimated")
    for k in sorted(printed):
        g = r["part_geometry"][k]
        print(f"  {k:14s} {g['mass_g']:6.1f} g  "
              f"{g['print_bbox_mm'][0]:6.1f} x {g['print_bbox_mm'][1]:6.1f} x {g['print_bbox_mm'][2]:6.1f} mm")
