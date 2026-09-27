<!--
Author: Claude (Opus 5)
Co-Author: Brendan Fennell
-->
# cadkit

The shared CAD workflow for every project on this machine. For any agent —
Claude, Codex, or otherwise.

**Three capabilities, and they are independent on purpose.** Generating a
model must not require a viewer to be running, nor a drawing sheet to be
produced; each of those costs a human interaction or seconds of compute that a
plain rebuild should never pay. `import cadkit` connects to nothing and
launches nothing — ask for the part you want.

| | |
|---|---|
| modelling | CadQuery and the project's own part scripts — needs nothing here |
| viewing | `cadkit.viewer` — launch one, find one, or carry on without one |
| drawings | `cadkit.sheet` — orthographic sheets |
| checking | `cadkit.check` — is the solid sound, and printable? |
| labelling | `cadkit.engrave` — dimensions cut into the part |

## Viewing: `cadkit.viewer`

```python
from cadkit import viewer
viewer.show(solid, name="part", port=None)   # False if nothing is listening
viewer.serve()                                # start one on a free port
```

`show` **never raises because no viewer is running.** It says so and returns
False, so the same part script runs identically whether or not anyone is
watching. It only uses an explicit port or `CAD_VIEWER_PORT`; it never guesses
at a listener that may belong to someone else. Never make a build depend on a
GUI.

Ports are contended — sessions have pushed to each other's viewers and
screenshotted the wrong model. `CLAIMED` lists the ports with standing owners
(3939 Aquarium, 3940/3941 Oil_Shelf); `free_port()` skips them and probes the
rest. From the shell:

```bash
cad-python -m cadkit.viewer --status      # who is up
cad-python -m cadkit.viewer               # start one on a free port
```

## Drawings: `cadkit.sheet`

```python
from cadkit import sheet
sheet.sheet(solid, "output/part_sheet.svg", "PART NAME",
            fields=[("PART", "part.py"), ("ENVELOPE", "175.0 x 175.0 x 42.0")])
```

Call it from a part script's `__main__`, beside the STEP export, so the
drawing regenerates from the same solid that is exported and cannot drift
from the part it describes.

A sheet is third angle: FRONT, SECTION A-A top right, PLAN, ISOMETRIC — four
views to **one common scale**, the section hatched from the solid's real cut
faces. `views=` takes an explicit list; the default set omits a right-side
view because the parts this was built against are axisymmetric, which is the
wrong default for a part that is not. `size=` overrides the sheet
proportions, which default to a full-screen workspace tile (A4/A3 landscape
is 1.414, US Letter landscape 1.294).

## Checking: `cadkit.check`

```bash
cad-python -m cadkit.check FILE    # 0 pass, 1 fail, 2 unreadable
```

```python
from cadkit import check
check.solid(part)                  # Report; .ok, .line(), .require()
check.solid(part, bodies=3)        # multi-body is legitimate; state the count
```

**Run it and print `report.line()` before claiming a part is finished.** An
agent's confidence is worth nothing; only an executed check counts. A model
that builds and displays can still have non-finite bounds, five naked edges
and a volume off by 140% — that exact part exists in this project's history.

`bodies=` states the expectation. `bodies=None` reports without judging. What
is never acceptable is not knowing.

### `check.printable`

```python
from cadkit import check, printers
check.printable(part, printers.get("prusa_mini"))
```

Bed fit blocks; overhang warns. Read both the worst angle and the dominant
band — one deliberate 2mm bridge makes the worst case 0 degrees and tells you
nothing about the 14,000mm2 at 25.

**Do not parse PrusaSlicer's vendor profile at runtime.** It was tried and
measured: 2.0MB, 179ms per call, identical answer to the registry's 1
microsecond. `printers.verify()` does the comparison when adding a printer or
from a test. Overhang limit is not in that file anyway -- it is a design rule.

## Two things that will otherwise cost you a session

- **Do not reach for `cq.exporters.export(..., "SVG")`.** It builds its
  projection with the two-argument `gp_Ax2`, letting OCCT invent the X axis,
  so the roll of each view is arbitrary — elevations land on their side,
  isometrics upside down. It fails *silently*: the image is perfectly valid
  and simply oriented wrong, and correcting it by rotating the output is
  guesswork repeated per part and per direction. `cadkit.sheet` takes a view
  direction **and** an up vector, and orients the shape before projecting.
- **Sheets are dark on screen and light on paper.** The dark palette rides on
  presentation attributes; a `@media print` block carries the light one and
  wins, so a browser printing the SVG swaps to black-on-white while
  `rsvg-convert` keeps the dark version. **Print the SVG, not the PNG** — any
  PNG beside it is a screen artefact and really is dark.

## Installing into a project

`uv` is installed (via mise, recorded in `~/.config/mise/config.toml`), so
this is an ordinary editable install:

```bash
VIRTUAL_ENV=<project>/.venv uv pip install -e ~/Projects/cadkit --no-deps
```

**`--no-deps` is not optional.** `cadquery` is declared in `pyproject.toml`
because it is genuinely required, but the host project pins it — adding a
drawing library must never be able to move a modelling dependency. Verified:
installing this way left `requirements-lock.txt` untouched.

Until 2026-09-27 uv was missing from this machine and the install was a hand
written `.pth` file. That worked but had no metadata, so nothing was listed by
`uv pip list`, nothing could be uninstalled, and `[project.scripts]` entry
points were never created. If you find a bare `cadkit.pth` in a venv, it is a
leftover of that era — replace it with the command above.

Already installed in the shared CAD environment, which every CAD project
reaches through **`cad-python`** (`~/.local/bin/cad-python` →
`~/.local/share/cad/venv`). Projects must not invoke another project's
`.venv/bin/python` directly — Oil_Shelf did, and a rename in Aquarium would
have broken it.

`pyproject.toml` is a real package definition, so if `pip` or `uv` ever
appears, `uv pip install -e . --no-deps` supersedes the `.pth`.
