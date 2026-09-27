<!--
Author: Claude (Opus 5)
Co-Author: Brendan Fennell
-->
# drafting

Orthographic drawing sheets from CadQuery solids, shared across the CAD
projects on this machine instead of copied into each one. For any agent —
Claude, Codex, or otherwise.

```python
import drafting
drafting.sheet(solid, "output/part_sheet.svg", "PART NAME",
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

## Two things that will otherwise cost you a session

- **Do not reach for `cq.exporters.export(..., "SVG")`.** It builds its
  projection with the two-argument `gp_Ax2`, letting OCCT invent the X axis,
  so the roll of each view is arbitrary — elevations land on their side,
  isometrics upside down. It fails *silently*: the image is perfectly valid
  and simply oriented wrong, and correcting it by rotating the output is
  guesswork repeated per part and per direction. `drafting` takes a view
  direction **and** an up vector, and orients the shape before projecting.
- **Sheets are dark on screen and light on paper.** The dark palette rides on
  presentation attributes; a `@media print` block carries the light one and
  wins, so a browser printing the SVG swaps to black-on-white while
  `rsvg-convert` keeps the dark version. **Print the SVG, not the PNG** — any
  PNG beside it is a screen artefact and really is dark.

## Installing into a project

There is **no `pip` in the project venvs and `uv` is not installed**, so the
editable install is a `.pth` file naming this package's `src` directory:

```bash
echo /home/benredrew/Projects/drafting/src \
  > <project>/.venv/lib/python3.12/site-packages/drafting.pth
```

Python puts that directory on `sys.path` at startup, so edits here take effect
immediately with nothing to rebuild. Remove the file to uninstall. `cadquery`
is declared in `pyproject.toml` but deliberately **not** installed by this —
the host project provides it, and its pinned version must not be disturbed.

Already installed in `~/Projects/Aquarium/.venv`, which is also the
interpreter `~/Projects/Oil_Shelf` runs on, so both have it.

`pyproject.toml` is a real package definition, so if `pip` or `uv` ever
appears, `uv pip install -e . --no-deps` supersedes the `.pth`.
