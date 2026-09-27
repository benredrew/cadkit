# Author: Claude (Opus 5)
# Co-Author: Brendan Fennell
"""Standard orthographic drawing sheets, one per part.

Shared across CAD projects on this machine rather than copied into each one.
It began as `drawing.py` inside the Aquarium project; the examples below still
come from there, because they are what the design was argued out against.

## Why this is not `cq.exporters.export(..., "SVG")`

That exporter takes a `projectionDir` and builds its projection frame with
`gp_Ax2(gp_Pnt(), gp_Dir(*projectionDir))` -- the two-argument constructor,
which lets OCCT invent the X axis. OCCT's choice is deterministic but
arbitrary, so the *roll* of every view is whatever falls out: the lamp shade's
front elevation came out on its side, and the first sheet built from it had the
ISO and the section upside down. Rotating the finished PNG to compensate is
guesswork that has to be redone per part and per direction.

Here the caller states the view direction *and* which way is up, and the frame
is built to match. `_orient` rotates the shape so the view direction becomes
+Z and up becomes +Y; after that every view projects along the same fixed axis
and 2D x/y are just the model's x/y. Nothing downstream has to know which view
it is looking at.

## What a sheet holds

Four views, all at **one scale** -- an orthographic drawing whose views are not
to a common scale is not a drawing, it is four pictures. Third-angle layout is
noted in the title block.

    FRONT           SECTION A-A
    PLAN            ISO

A right-side view is deliberately absent from the default set. The parts this
was built against are surfaces of revolution, so the side view *is* the front
view and the cell is better spent on the section. For a part that is not
axisymmetric that default is wrong -- pass `views=` with an explicit list,
which is what it is for.

The section is cut on the vertical centre plane, the near half removed, and the
exposed cut face hatched at 45 degrees. Hatching is what separates a section
from a part someone has broken in half; it is drawn from the real cut faces, so
a part whose section is not what the author imagined shows it here.
"""
import math
from datetime import date

import cadquery as cq
from cadquery.occ_impl.exporters.svg import PATHTEMPLATE, getPaths
from cadquery.occ_impl.shapes import Compound, Shape, TOLERANCE
from OCP.BRepBuilderAPI import BRepBuilderAPI_Transform
from OCP.BRepLib import BRepLib
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt, gp_Trsf
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape

# Sheet proportions default to a full-screen workspace tile on the machine this
# was written for, so the drawing fills an image viewer edge to edge with no
# letterbox bars. Any project wanting different proportions passes `size=` --
# A4/A3 landscape is 1.414, US Letter landscape 1.294.
#
# Measured rather than assumed: a 1920x1080 panel at scale 1.5 gives a 1280x720
# logical desktop; Omarchy reserves 26 for the bar and leaves gaps, so a single
# tiled window comes out 1256x670 logical, which is 1884x1005 real pixels.
# Drawing at exactly that means the SVG user unit is one output pixel too, so
# rasterising at 1884x1005 needs no resampling.
#
# What matters here is the ratio, not the size -- any viewer scaling to fit
# shows no bars as long as the aspect matches. Re-measure with
# `hyprctl clients -j` if the panel, the scale or the bar height changes; pass
# `size=` to `sheet` for a one-off at different proportions (A3 is 1.414).
TILE_ASPECT = 1256 / 670       # 1.87463
SHEET_W = 1884.0
SHEET_H = 1005.0
MARGIN = 26.0
GUTTER = 18.0
TITLE_H = 132.0
CELL_PAD = 46.0          # clear space inside a cell, around the view
LABEL_H = 34.0

STROKE = 1.5
HIDDEN_STROKE = 1.0
HATCH_PITCH = 7.0

# The sheet is dark on screen and light on paper, and it gets there without a
# second file or a flag to remember.
#
# Colours are written twice: once as ordinary presentation attributes carrying
# the dark palette, which every rasteriser honours including librsvg, and once
# as a `@media print` CSS block carrying the light one. CSS beats presentation
# attributes, so a browser printing this swaps to black-on-white of its own
# accord, while `rsvg-convert` -- which has no notion of print media -- keeps
# the dark screen version. That ordering is the whole trick, and it is why the
# dark values must stay inline rather than move into a screen CSS rule.
#
# The PNG beside the SVG is a *screen* artefact and really is dark. Print the
# SVG, not the PNG.
INK = "#e8eaed"          # visible edges
HIDDEN_INK = "#6f7780"   # dashed hidden detail
FRAME_INK = "#565c65"    # sheet frame and title block rule
HATCH_INK = "#8b939c"    # section hatching
DIM_INK = "#8b939c"      # field labels in the title block
PAPER = "#15171b"        # not pure black: pure black crushes the hatch

PRINT_CSS = """
@media print {
  /* The sheet is landscape and 1884px wide, which at 96dpi is 19.6in -- onto a
     portrait page that prints cropped, not scaled. Ask for landscape and let
     the viewBox do the fitting. */
  @page { size: landscape; margin: 8mm; }
  svg { width: 100%; height: 100%; }
  .bg { fill: #ffffff; }
  .frame { stroke: #333333; }
  .lines { stroke: #111111; }
  .hidden { stroke: #9a9a9a; }
  .hatch { stroke: #7a7a7a; }
  .txt { fill: #111111; }
  .txt-dim { fill: #777777; }
}
"""


def _unit(v):
    n = math.sqrt(sum(c * c for c in v))
    if n < 1e-12:
        raise ValueError("zero-length direction")
    return tuple(c / n for c in v)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _orient(shape, direction, up):
    """Rotate `shape` so `direction` becomes +Z and `up` becomes +Y.

    The whole point of the module: after this, every view is the same
    projection along +Z, and the roll is the caller's stated `up` rather than
    OCCT's arbitrary choice of X axis.
    """
    d = _unit(direction)
    right = _cross(up, d)
    if math.sqrt(sum(c * c for c in right)) < 1e-9:
        raise ValueError("up is parallel to the view direction")
    right = _unit(right)
    screen_up = _cross(d, right)

    trsf = gp_Trsf()
    trsf.SetValues(right[0], right[1], right[2], 0.0,
                   screen_up[0], screen_up[1], screen_up[2], 0.0,
                   d[0], d[1], d[2], 0.0)
    return Shape(BRepBuilderAPI_Transform(shape.wrapped, trsf, True).Shape())


def _project(oriented, hidden):
    """Hidden-line projection along +Z. Returns (visible, hidden) path data."""
    hlr = HLRBRep_Algo()
    hlr.Add(oriented.wrapped)
    hlr.Projector(
        HLRAlgo_Projector(gp_Ax2(gp_Pnt(), gp_Dir(0, 0, 1), gp_Dir(1, 0, 0)))
    )
    hlr.Update()
    hlr.Hide()
    shapes = HLRBRep_HLRToShape(hlr)

    def gather(*compounds):
        out = []
        for c in compounds:
            if not c.IsNull():
                out.append(c)
        for el in out:
            BRepLib.BuildCurves3d_s(el, TOLERANCE)
        return list(map(Shape, out))

    vis = gather(shapes.VCompound(), shapes.Rg1LineVCompound(),
                 shapes.OutLineVCompound())
    hid = gather(shapes.HCompound(), shapes.OutLineHCompound()) if hidden else []
    hidden_paths, visible_paths = getPaths(vis, hid)
    bb = Compound.makeCompound(vis + hid).BoundingBox()
    return visible_paths, hidden_paths, bb


def _cut_faces(oriented):
    """The faces lying in the cutting plane -- what a section hatches.

    After `_orient` the camera looks down +Z, and the half between camera and
    plane has been removed, so the cut face is the planar, Z-normal face at
    the shape's own zmax. Taking them from the solid rather than from the
    profile that drew it means the hatch shows what was really cut.
    """
    zmax = oriented.BoundingBox().zmax
    faces = []
    for f in oriented.Faces():
        if f.geomType() != "PLANE":
            continue
        try:
            n = f.normalAt()
        except Exception:
            continue
        if abs(abs(n.z) - 1.0) > 1e-6:
            continue
        if abs(f.Center().z - zmax) > 1e-4:
            continue
        faces.append(f)
    return faces


def _wire_path(wire):
    """One closed SVG subpath for a wire, edges walked in connection order."""
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.TopAbs import TopAbs_REVERSED

    pts = []
    exp = BRepTools_WireExplorer(wire.wrapped)
    while exp.More():
        edge = exp.Current()
        curve = cq.Edge(edge)._geomAdaptor()
        disc = GCPnts_QuasiUniformDeflection(
            curve, 1e-3, curve.FirstParameter(), curve.LastParameter()
        )
        seq = [disc.Value(i + 1) for i in range(disc.NbPoints())] if disc.IsDone() else []
        if edge.Orientation() == TopAbs_REVERSED:
            seq.reverse()
        for p in seq:
            xy = (p.X(), p.Y())
            if not pts or abs(pts[-1][0] - xy[0]) > 1e-9 or abs(pts[-1][1] - xy[1]) > 1e-9:
                pts.append(xy)
        exp.Next()
    if len(pts) < 3:
        return ""
    return "M" + " L".join(f"{x:.4f},{y:.4f}" for x, y in pts) + " Z"


def _half(shape, normal, reach=1e4):
    """Remove the half of `shape` on the camera side of the centre plane."""
    n = _unit(normal)
    box = cq.Workplane("XY").box(reach, reach, reach, centered=True)
    # `normal` points AT the camera, so the half to remove is the one on the
    # +normal side: the cutter sits there, its far face on the origin plane.
    # Getting this backwards removes the far half instead, which leaves the cut
    # face pointing away and renders a section indistinguishable from the
    # front view -- silently, since the projection is perfectly valid.
    box = box.translate(tuple(c * reach / 2 for c in n))
    return cq.Workplane(obj=shape).cut(box).val()


# direction: where the camera is; up: which way is up on the paper.
VIEW_FRONT = dict(key="front", label="FRONT", direction=(0, -1, 0), up=(0, 0, 1),
                  hidden=True, cut=False)
VIEW_SECTION = dict(key="section", label="SECTION A-A", direction=(0, -1, 0),
                    up=(0, 0, 1), hidden=False, cut=True)
VIEW_PLAN = dict(key="plan", label="PLAN", direction=(0, 0, 1), up=(0, 1, 0),
                 hidden=False, cut=False)
VIEW_ISO = dict(key="iso", label="ISOMETRIC", direction=(1, -1, 1), up=(0, 0, 1),
                hidden=False, cut=False)

# Section top right, as a section belongs beside the view it is taken from.
STANDARD = (VIEW_FRONT, VIEW_SECTION, VIEW_PLAN, VIEW_ISO)


def _render(shape, view, cut_normal):
    """One view: oriented, projected, and measured, still in model units."""
    src = _half(shape, cut_normal) if view["cut"] else shape
    oriented = _orient(src, view["direction"], view["up"])
    visible, hidden, bb = _project(oriented, view["hidden"])
    hatch = []
    if view["cut"]:
        try:
            for face in _cut_faces(oriented):
                subpaths = [_wire_path(w) for w in face.Wires()]
                joined = " ".join(p for p in subpaths if p)
                if joined:
                    hatch.append(joined)
        except Exception:
            hatch = []   # a sheet without hatching still beats no sheet
    return dict(view=view, visible=visible, hidden=hidden, bb=bb, hatch=hatch)


def _esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def sheet(shape, path, title, fields=(), views=STANDARD, cut_normal=(0, -1, 0),
          size=(SHEET_W, SHEET_H)):
    """Write a standard four-view sheet for `shape` to `path` (SVG).

    `fields` are (label, value) pairs for the title block. `cut_normal` points
    at the camera for the sectioned view -- the half on that side comes away.
    """
    if hasattr(shape, "val"):
        shape = shape.val()
    sheet_w, sheet_h = float(size[0]), float(size[1])

    rendered = [_render(shape, v, cut_normal) for v in views]

    # One scale for every view. Orthographic views not drawn to a common scale
    # are four pictures, not a drawing.
    grid_w = (sheet_w - 2 * MARGIN - GUTTER) / 2
    rows = (len(rendered) + 1) // 2
    # Every view is drawn at one scale, but the rows need not be equal: a row
    # of 42mm-tall elevations does not deserve the same band as a row of 175mm
    # plans. Sizing each row to its own tallest view lets the common scale come
    # out as large as the sheet allows instead of being set by the squarest
    # view and stranding the rest in white space.
    row_tall = [
        max((r["bb"].ylen for r in rendered[i * 2:i * 2 + 2]), default=1e-9)
        for i in range(rows)
    ]
    fixed = 2 * CELL_PAD + LABEL_H
    drawable_h = sheet_h - 2 * MARGIN - TITLE_H - GUTTER * (rows - 1) - rows * fixed
    scale = min(
        (grid_w - 2 * CELL_PAD) / max(r["bb"].xlen for r in rendered),
        drawable_h / max(sum(row_tall), 1e-9),
    )
    row_h = [scale * t + fixed for t in row_tall]
    row_y = []
    acc = MARGIN
    for h in row_h:
        row_y.append(acc)
        acc += h + GUTTER

    out = [
        f'<?xml version="1.0" encoding="UTF-8" standalone="no"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{sheet_w:.0f}" '
        f'height="{sheet_h:.0f}" viewBox="0 0 {sheet_w:.0f} {sheet_h:.0f}">',
        f'<rect class="bg" width="{sheet_w:.0f}" height="{sheet_h:.0f}" fill="{PAPER}"/>',
        f'<style>{PRINT_CSS}</style>',
        '<defs>',
    ]
    pitch = HATCH_PITCH / scale
    out.append(
        f'<pattern id="hatch" patternUnits="userSpaceOnUse" '
        f'width="{pitch:.4f}" height="{pitch:.4f}" '
        f'patternTransform="rotate(45)">'
        f'<line class="hatch" x1="0" y1="0" x2="0" y2="{pitch:.4f}" stroke="{HATCH_INK}" '
        f'stroke-width="{0.9 / scale:.4f}"/></pattern>'
    )
    out.append('</defs>')

    # Sheet frame.
    out.append(
        f'<rect class="frame" x="{MARGIN:.1f}" y="{MARGIN:.1f}" '
        f'width="{sheet_w - 2 * MARGIN:.1f}" height="{sheet_h - 2 * MARGIN:.1f}" '
        f'fill="none" stroke="{FRAME_INK}" stroke-width="2"/>'
    )

    for i, r in enumerate(rendered):
        col, row = i % 2, i // 2
        x0 = MARGIN + col * (grid_w + GUTTER)
        y0 = row_y[row]
        bb = r["bb"]
        cx = x0 + grid_w / 2
        cy = y0 + LABEL_H + (row_h[row] - LABEL_H) / 2
        mx, my = (bb.xmin + bb.xmax) / 2, (bb.ymin + bb.ymax) / 2

        out.append(f'<g>')
        out.append(
            f'<text x="{x0 + CELL_PAD / 2:.1f}" y="{y0 + LABEL_H - 8:.1f}" '
            f'font-family="DejaVu Sans, Helvetica, sans-serif" font-size="21" '
            f'letter-spacing="1.5" class="txt" fill="{INK}">{_esc(r["view"]["label"])}</text>'
        )
        out.append(
            f'<g transform="translate({cx:.3f},{cy:.3f}) '
            f'scale({scale:.6f},{-scale:.6f}) translate({-mx:.4f},{-my:.4f})" '
            f'fill="none">'
        )
        for d in r["hatch"]:
            out.append(
                f'<path d="{d}" fill="url(#hatch)" fill-rule="evenodd" '
                f'stroke="none"/>'
            )
        if r["hidden"]:
            dash = f'{2.5 / scale:.4f},{2.0 / scale:.4f}'
            out.append(
                f'<g class="hidden" stroke="{HIDDEN_INK}" stroke-width="{HIDDEN_STROKE / scale:.4f}" '
                f'stroke-dasharray="{dash}">'
            )
            for p in r["hidden"]:
                out.append(PATHTEMPLATE % p)
            out.append('</g>')
        out.append(
            f'<g class="lines" stroke="{INK}" stroke-width="{STROKE / scale:.4f}" '
            f'stroke-linecap="round" stroke-linejoin="round">'
        )
        for p in r["visible"]:
            out.append(PATHTEMPLATE % p)
        out.append('</g></g></g>')

    # Title block.
    ty = sheet_h - MARGIN - TITLE_H
    out.append(
        f'<rect class="frame" x="{MARGIN:.1f}" y="{ty:.1f}" width="{sheet_w - 2 * MARGIN:.1f}" '
        f'height="{TITLE_H:.1f}" fill="none" stroke="{FRAME_INK}" stroke-width="2"/>'
    )
    out.append(
        f'<text x="{MARGIN + 22:.1f}" y="{ty + 46:.1f}" '
        f'font-family="DejaVu Sans, Helvetica, sans-serif" font-size="30" '
        f'font-weight="bold" letter-spacing="1" class="txt" fill="{INK}">{_esc(title)}</text>'
    )
    all_fields = list(fields) + [
        ("SCALE", f"1:{1 / scale * 3.7795:.2f}" if scale else "-"),
        ("PROJECTION", "third angle"),
        ("DATE", date.today().isoformat()),
    ]
    # Lay the fields out across the block's real width rather than marching
    # right on a per-field guess -- one extra field used to walk DATE off the
    # edge of the sheet. Widths are still estimated from the text, but they are
    # then normalised to the space available, so the row always fits and adding
    # a field crowds the others instead of falling off.
    left = MARGIN + 22
    right = sheet_w - MARGIN - 22
    want = [max(len(str(v)) * 10.5, len(str(l)) * 8.5) + 30 for l, v in all_fields]
    room = right - left
    if sum(want) > room:
        k = room / sum(want)
        want = [w * k for w in want]
    fx = left
    for (label, value), w in zip(all_fields, want):
        out.append(
            f'<text x="{fx:.1f}" y="{ty + 80:.1f}" font-family="DejaVu Sans, '
            f'Helvetica, sans-serif" font-size="14" letter-spacing="1.2" '
            f'class="txt-dim" fill="{DIM_INK}">{_esc(label)}</text>'
        )
        out.append(
            f'<text x="{fx:.1f}" y="{ty + 106:.1f}" font-family="DejaVu Sans, '
            f'Helvetica, sans-serif" font-size="19" class="txt" fill="{INK}">{_esc(value)}</text>'
        )
        fx += w

    out.append('</svg>')
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    return path
