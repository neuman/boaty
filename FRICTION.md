# Friction log — building an RC boat with atompipe

Blunt notes, written as I went. Timestamps are rough ordering, not wall clock.
Quoted text is real terminal output.

---

## 0. Before running anything

**Friction: the skill tells you to set `$CLAUDE_PLUGIN_ROOT` and it is not set.**

`skills/atompipe/SKILL.md` says:

```sh
export PYTHONPATH="$CLAUDE_PLUGIN_ROOT/src:$PYTHONPATH"
alias atompipe='python3 -m atompipe'
```

`CLAUDE_PLUGIN_ROOT` is empty in my environment, so that line silently exports
`PYTHONPATH=/src:` and the next command fails with a plain ImportError. It is not
wrong, it is just that the four-line ladder of "try these in order" is written for a
human reading output, and an agent that pastes the wrong rung gets a confusing
failure one step later. In this project there is a venv shim
(`.venv/bin/atompipe`), which works and is what I used — but nothing in the docs
told me to look for that; the user did.

**Suggestion:** `atompipe doctor` should be runnable *before* you have a working
atompipe. A one-line bootstrap that finds the spine would remove the whole ladder.

## 1. `atompipe packs install` does not exist

`skills/atompipe/SKILL.md` says, twice, in the section about clearing a BLOCKED claim:

> Run `atompipe packs install <pack>` for the recipe, install the tool, and re-run.

There is no `install` subcommand:

```
$ atompipe packs install fluids-analytic
usage: atompipe packs [-h] <sub> ...
atompipe packs: error: argument <sub>: invalid choice: 'install'
  (choose from 'list', 'show', 'validate', 'add', 'remove')
```

The verb is `add`. Small, but it is in the *one* document an agent is told to read
before doing anything, in the paragraph about the failure mode the tool cares most
about (a BLOCKED claim left lying around), so it is the worst possible place for it.

Also: `atompipe packs list` prints `* = installed in this project (0 of 7
discoverable)` — but nothing on that screen tells you that "discoverable" and
"installed" are different states, or that `add` is what moves a pack between them.
I only found out because `atompipe gate list` said `no gates registered` after I had
already read three PACK.md files and assumed they were live. **For a while I thought
I had a working gate set and I had zero.** That is exactly the "looks validated and
is not" failure the method is about, one level up, in the tool itself.

## 2. `atompipe doctor` prints `[FAIL]` and exits 0

```
$ atompipe doctor; echo "exit=$?"
[ok  ] python             3.12.3 ...
[ok  ] spine              atompipe 0.1.0 ...
[FAIL] project            no .atompipe/ in ... — run `atompipe init`
3 checks — 1 failing, 0 warning(s)
exit=0
```

METHOD.md rule 4 is "Validators are gates, not loggers — a validator that prints a
problem and exits 0 is a decoration." `doctor` is the tool's own front door and it
is a decoration by its own definition. It cost me nothing here because I read the
output, but anything scripting `atompipe doctor && ...` gets a false green.

## 3. Packs are "discoverable" and "installed" and nothing says they are different

`atompipe packs list` shows seven packs and a footer:

```
* = installed in this project (0 of 7 discoverable)
```

Nothing on that screen explains that a discoverable pack contributes nothing, or that
`packs add` is what changes it. I had read three PACK.md files and built a mental model
of which gates I was going to use before `atompipe gate list` told me:

```
no gates registered. Install a pack (`atompipe packs`) or write gates/<name>.py in this project.
```

**For about twenty minutes I believed I had a working gate set and I had zero.** That
is the tool's own headline failure mode — looking validated and not being — reproduced
one level up, in the tool.

Suggestion: `atompipe status` should say "0 gates available, 7 packs discoverable but
not added" in the same breath, or `init` should offer to add the packs whose
claim_classes match the claims already in the ledger.

## 4. `atompipe check` warned me about a name collision I would never have found

Credit where it is due, and this is the single most valuable thing the tool did:

```
warning: model and build() disagree on min_freeboard_mm:
         config 25.0 vs build() 31.808492225817865 — gates read the config value
```

I had used one name for the freeboard THRESHOLD and for the freeboard MEASUREMENT.
The gate would have compared against 25.0 while the report printed 31.8, and both
numbers are plausible, and the error is in the reassuring direction. Nothing else in
my process would have caught it. This is rule 6 mechanised and it works.

## 5. Two packs collide on `bbox_mm` and only one can win

`fdm-print` reads `bbox_mm` for the single PART it is judging. `cad-solid` reads
`bbox_mm` for the ASSEMBLY. One projection cannot mean both.

Publishing the assembly there:

```
[FAIL] fdm.bed_fit : 480x186x87 mm vs 208x208 usable (220x220 bed - 2x6.0 brim) x 250 Z
```

— a 480 mm boat measured against a 220 mm printer bed. Not publishing it:

```
[skip] cad.bounding : bbox_mm is absent — nothing to compare, so nothing is claimed
```

`fdm-print` also accepts `bbox`, and I tried publishing the part under `bbox` and the
assembly under `bbox_mm`, on the theory that the more specific key would win. It does
not: **`bbox_mm` is resolved before `bbox`**, which is undocumented and is the opposite
of what the key names suggest. So `fdm.bed_fit` — the gate that answers "can I build
this at home", which is the whole brief — kept the key, `cad.bounding` skips, and I
wrote a project gate `boat.envelope` to cover the claim instead.

**This is a real design bug in the pack ecosystem, not a mistake I made.** Two packs
that are both in the tool's own default set cannot be used together on a project that
has an assembly and printed parts, which is every mechanical project. A pack-scoped
key namespace (`fdm.bbox_mm`, `cad.bbox_mm`) would fix it. `atompipe doctor` could
detect it: it knows which packs are installed and could diff their key vocabularies.

## 6. `atompipe doctor` prints `[FAIL]` and exits 0

Already noted above. Worth repeating because it never got better: across the whole
session, `doctor` was the command the docs told me to run when confused, and its exit
code never reflected its own findings.

## 7. `claim edit` takes the build lock

Running claim edits while a `gate selftest` was in progress:

```
error: another atompipe run (pid 724928) holds
/home/neuman/Documents/work/boaty/.atompipe/build.lock — wait for it to finish
```

Correct behaviour for a lock, and the message is good. But **`claim edit` does not
build anything** — it edits a row in the ledger — and five claim edits silently did
not apply while I moved on believing they had. The failure is visible in stderr and
invisible in the result. A finer-grained lock, or a `--wait` flag, would help. So
would a non-zero exit code, which would have stopped my script.

## 8. A param record outlives the param

After I removed a derived key from `build()`, `atompipe status` kept reporting it:

```
standing: 1 param with no rationale
undefended params: min_freeboard_mm — no rationale recorded
```

The key is not in the model any more, by grep. Minor, but it means the undefended-param
count is a floor rather than a measurement, and that is the kind of number people stop
reading once it stops going to zero.

## 9. The fdm-print pack judges ONE part; real projects print many

`fdm.overhang`, `fdm.bridge_span` and `fdm.bed_fit` all read a single `mesh_path`.
This project prints thirteen parts. There is no multi-part mode, and no way to say
"run this gate over each of these".

My workaround: the model computes a cheap per-part statistic, picks the worst part by
the metric each gate cares about, and hands that one over — so the verdict is an
envelope over the print set rather than a statement about a part chosen at random.
That is stated in the readiness report because a reader would otherwise reasonably
assume all thirteen were checked. **They were not. One was, and it was the worst one.**

The same limitation bit differently: `part_name` picks the worst-OVERHANG part, which
changed five times during the session as I fixed geometry, so the gate silently moved
to judging a different object between runs. A verdict that changes subject without
saying so is hard to reason about.

## 10. The mesh gates judge the frame you hand them, and the assembly frame is wrong

Exporting parts in assembly coordinates gave:

```
[FAIL] fdm.bridge_span : worst unsupported span 201.7 mm ... (UNANCHORED)
```

on a flat deck panel. Entirely true of a deck panel floating 70 mm above the "bed" in
hull coordinates, and entirely useless, because nobody prints it there. I now export
two sets — `build/*.stl` in assembly coordinates for the clash check and the viewer,
and `build/print/*.stl` laid on the bed as printed — and the fdm gates read the second.

Nothing in `fdm-print`'s PACK.md says which frame it expects. It should, in the first
paragraph: **the mesh must be in print orientation with the bed at z=0**. The pack has
a `build_axis` parameter, which implies the mesh might be in any frame, but the
overhang and bridge gates plainly assume z is up AND that the part is sitting on the
bed — my flat panel had a `build_axis` of z and still measured nonsense.

Related: `load_axis` silently wanted a VECTOR, not a string. `"z"` produced

```
[skip] fdm.layer_alignment : the projection has no load_axis / primary_load_axis
```

which reads as "you did not set it" when I had.

## 11. cad.clash on printed multi-body parts: two false positives I had to chase

```
[FAIL] cad.clash : worst reported 31277.200 mm^3 on bulkhead_fwd/deck_mid
       ... inf mm equivalent depth over 0.00 mm^2
```

Those two parts' bounding boxes **do not overlap on any axis**. They share one face
exactly. A boolean engine asked about two solids that touch on a coplanar face returns
nonsense, and the gate's own output says so if you read it — `inf` depth over `0.00 mm²`
is the engine shrugging. But the headline number is 31 cm³ and reads as a real clash,
and I spent a while looking for geometry that was not there.

The gate already knows how to say "the boolean's answer about this pair is meaningless"
(it says exactly that when a part is not a volume). It should say the same when the
depth is non-finite or the contact area is zero, and it should not report a volume it
does not believe.

Second one: the gate fires on parts that are DESIGNED to be bonded together. That is
what `clash_allow` is for and the mechanism is good — it refuses wildcards and refuses
an entry with no reason, which is exactly right. But the default of "any contact is a
failure" means a glued assembly starts out with a page of failures, and the temptation
to write a wildcard is strongest at exactly that moment. A `sliding_fits` style
declaration for "bonded joint" would be the honest middle.

## 12. What cost me the most time, and it was not atompipe's fault

The traced hull section came out of the screenshot **non-monotone** — half-beam
wobbling by a factor of five between adjacent depths, because I sorted the traced
points by depth when the trace samples depth-per-half-beam. The inward offset then
folded over itself at the turn of bilge, the wall polygon enclosed 501 mm² where the
ribbon was really 869, every printed part was 40% light, and every hydrostatic integral
ran on a corrugated hull.

**Every geometry gate passed the whole time.** `cad.watertight` passed.
`cad.is_volume` passed. `cad.degenerate_faces` passed. The masses looked plausible.
The boat floated on paper. Nothing that checks a mesh against ITSELF could have caught
it, because the mesh was internally perfect and described the wrong hull.

What caught it was comparing the wall thickness the model SPECIFIES against the wall
thickness implied by the generated mesh's own volume and area — two independent routes
to one number, which is METHOD rule 6, and which I only wrote because the method told
me to. That is now `boat.wall_agreement`, and it is the gate in this project that has
actually earned its existence.

**So: rule 6 paid for the whole exercise.** I would not have written that check on my
own. I would have written the three geometry gates that check a mesh against itself,
watched them go green, and shipped a corrugated hull.

## 13. Things I wanted and could not get

- **A way to run a gate over N parts.** See 9.
- **Per-pack key namespaces.** See 5.
- **`atompipe check --only <gate>` for tier-1 mesh gates without re-running build().**
  A full tier-1 sweep is 40-80 s, almost all of it the boolean engine, and I ran it
  about thirty times while chasing geometry. A `--only` that skipped the other mesh
  gates would have made the loop four times faster. (`--only` exists; the cost is the
  build and the mesh export, which happen regardless.)
- **A worked example of a project that has BOTH an assembly and printed parts.**
  `examples/bracket` is one part with no mesh at all, so it exercises none of the
  cad-solid/fdm-print interaction where all of my time went. The packs are individually
  well documented and their intersection is not documented at all.
- **Somewhere to put a number that is not a model parameter.** The budget is a
  judgement I invented; `atompipe decide` records the reasoning beautifully, but the
  number still has to live in the model dataclass next to hull offsets traced from
  evidence. Those are different kinds of number and the report does not distinguish
  them.

## 14. Did the overhead earn its keep?

Honest answer, itemised.

**Earned it, clearly:**

- **Rule 5, negative controls.** The registry refusing a gate without one forced me to
  build a falsification for all seven project gates. Two of them (`boat.free_surface`,
  `boat.empty`) could not be made to fail by any plausible edit, because this hull has
  BM 91 mm and GM 72 mm — which is *itself the finding* that the boat is extremely
  stiff, and I only learned it because I had to try. Both controls now SOLVE for the
  mass that misses the acceptance rather than typing one, so they survive a threshold
  change. `34 control(s): 34 fired, 0 BROKEN`.
- **Rule 6, cross-representation agreement.** See 12. It found the one bug that would
  have sunk the project, and the tool found a second one (the `min_freeboard_mm` name
  collision) by itself.
- **Rule 8, adversarial lenses before building.** `packs/fluids-analytic/lenses.md`
  changed the design four times before a single STL existed: the sealed foam-filled end
  compartments, the centre girder, checking the EMPTY condition, and the whole trim
  solver. None of those would have occurred to me, and three of them are now claims
  with gates.
- **The claim/evidence discipline.** Writing C2 as "25 mm of freeboard" before knowing
  the answer is what made the LOA 300 hull's failure a *fact* rather than an opinion I
  could talk myself out of.

**Earned it, quietly:**

- **Rule 3, provenance on every constant.** Tedious — I documented about sixty
  parameters and the tool nagged me until I did. It paid three times that I noticed,
  every time I came back to a number I had set an hour earlier and the docstring told
  me what had already been rejected. It will pay much more for the next reader.
- **Rule 9, separating proven from assumed.** The readiness report is the deliverable I
  would actually hand someone, and it is honest in a way my own summary would not have
  been.

**Did not earn it, or cost more than it gave:**

- **Rule 10, cheap inner loops — as an aspiration.** A tier-0 sweep is now under a
  second and a tier-1 sweep is 40-80 s. Getting there took me an explicit
  vectorisation pass on the hydrostatics (17 s to 0.65 s) and a geometry cache that I
  had to write myself. The doctrine says the loop must be cheap; nothing in the tool
  helps you make it cheap, and the default path — a model that rebuilds every mesh on
  every gate invocation — is not.
- **The site.** `site init` + `site build` is two commands and produces a genuinely
  good page with a 3D assembly, a GZ curve and the BOM. But in a text session I never
  looked at it, and the brief's reader will see the markdown. It cost two minutes, so
  it is not a complaint, but it did not change anything I did.

**The one-sentence version:** the parts of atompipe that made me prove a negative —
negative controls, cross-representation checks, adversarial lenses — found real
problems I would have shipped. The parts that made me write things down were tedious
and correct. The parts that got in the way were all in the packs' shared vocabulary,
not in the method.
