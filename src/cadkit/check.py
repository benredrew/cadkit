# Author: Claude (Opus 5)
# Co-Author: Brendan Fennell
"""Is this actually a sound solid? Answer by measuring, not by believing.

A CAD model built by an agent -- or by anyone working fast -- fails in ways
that look like success. Every check here exists because its absence let
something through:

- A revolve of collinear samples **built, displayed, and was garbage**: an
  infinite bounding box and a volume of 284cm3 for a part that is really 117.
  Nothing raised. The viewer showed a shape. Only measuring caught it.
- `Shape.Closed()` returned False on a watertight part -- and on a second part
  known to print fine. It is an OCCT flag that booleans do not maintain, not a
  watertightness test. Counting edges with fewer than two adjacent faces is.
- A boolean that quietly yields two solids is invisible in a viewer, and every
  downstream export silently takes the first one.

So the rule this module encodes: **an agent's confidence is worth nothing;
only an executed check counts.** Run it, print the verdict, and let a failure
be as loud as a traceback.

## Bodies are an expectation, not a constant

Plenty of legitimate parts are multi-body -- an assembly, or a part split so
its regions can take different print settings, as `lid_screen/screen.py` does.
So `bodies=` states what the author expects and the check compares against it.
`bodies=None` reports the count without judging it. What is never acceptable
is not knowing.

## Scope

Did this come out a sound solid? Not: will it slice well, is it strong
enough, is it the right shape. Printability is `check.printable` and does not
exist yet; correctness against intent is the author's job.
"""
import math

from OCP.Bnd import Bnd_Box
from OCP.BRepBndLib import BRepBndLib
from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
from OCP.TopExp import TopExp
from OCP.TopTools import TopTools_IndexedDataMapOfShapeListOfShape

# Beyond this, a coordinate is not a part -- it is a degenerate boolean. The
# phantom that prompted this read ~2e100 on a part 175mm across.
SANE_MM = 1e6


def _plural(n):
    return f"{n} body" if n == 1 else f"{n} bodies"


class Check:
    """One finding: what was asked, whether it held, and the measurement.

    `level` separates "this will not print" from "look at this". An overhang
    is a warning: plenty of parts print fine with support, or with the author
    having decided the droop lands somewhere invisible. A part larger than the
    bed is not a warning.
    """

    def __init__(self, name, ok, detail, level="fail"):
        self.name, self.ok, self.detail, self.level = name, ok, detail, level

    @property
    def blocking(self):
        return not self.ok and self.level == "fail"

    def __repr__(self):
        mark = "ok  " if self.ok else ("WARN" if self.level == "warn" else "FAIL")
        return f"{mark} {self.name}: {self.detail}"


class Report:
    def __init__(self, checks):
        self.checks = checks

    @property
    def ok(self):
        """True if nothing blocking failed. Warnings do not make it False."""
        return not any(c.blocking for c in self.checks)

    @property
    def failures(self):
        return [c for c in self.checks if c.blocking]

    @property
    def warnings(self):
        return [c for c in self.checks if not c.ok and c.level == "warn"]

    def line(self, label="check"):
        """One line for a part script to print. Silence is not evidence."""
        pad = f"{label:<12s} "
        if self.failures:
            out = "FAILED -- " + "; ".join(
                f"{c.name}: {c.detail}" for c in self.failures)
        else:
            out = ", ".join(c.detail for c in self.checks if c.ok)
        if self.warnings:
            out += "  <-- " + "; ".join(
                f"{c.name}: {c.detail}" for c in self.warnings)
        return pad + out

    def require(self):
        """Raise if anything failed -- for a gate that must not be ignored."""
        if not self.ok:
            raise ValueError("solid check failed -- " + "; ".join(
                f"{c.name}: {c.detail}" for c in self.failures))
        return self

    def __repr__(self):
        return "\n".join(repr(c) for c in self.checks)


def _naked_edges(solid):
    """Edges with fewer than two adjacent faces: a hole in the skin.

    This is the watertightness test. `Shape.Closed()` is a stored flag that
    boolean operations do not keep up to date -- it reads False on parts that
    are provably closed -- so it cannot be used for this.
    """
    m = TopTools_IndexedDataMapOfShapeListOfShape()
    TopExp.MapShapesAndAncestors_s(solid.wrapped, TopAbs_EDGE, TopAbs_FACE, m)
    bad = sum(1 for i in range(1, m.Extent() + 1)
              if m.FindFromIndex(i).Extent() < 2)
    return bad, m.Extent()


def _bounds(shape):
    """Exact bounds, off the geometry rather than any cached triangulation."""
    box = Bnd_Box()
    BRepBndLib.AddOptimal_s(shape.wrapped, box, False, False)
    if box.IsVoid():
        return None
    return box.Get()


def solid(shape, bodies=1):
    """Check `shape` is a sound solid (or `bodies` of them).

    `bodies=None` reports the count without requiring a particular one.
    Returns a Report; `.ok` is the verdict, `.line()` is what to print.
    """
    if hasattr(shape, "val"):
        shape = shape.val()
    solids = shape.Solids()
    checks = []

    n = len(solids)
    if bodies is None:
        checks.append(Check("bodies", True, _plural(n)))
    else:
        checks.append(Check(
            "bodies", n == bodies,
            _plural(n) + ("" if n == bodies else f", expected {bodies}")))

    if not solids:
        checks.append(Check("solid", False, "no solid at all"))
        return Report(checks)

    bad = [i for i, s in enumerate(solids) if not s.isValid()]
    checks.append(Check("valid", not bad,
                        "geometry valid" if not bad else f"invalid: bodies {bad}"))

    naked_total, edge_total, leaky = 0, 0, []
    for i, s in enumerate(solids):
        nk, tot = _naked_edges(s)
        naked_total += nk
        edge_total += tot
        if nk:
            leaky.append(f"body {i}: {nk}")
    checks.append(Check(
        "watertight", naked_total == 0,
        f"0 naked edges of {edge_total}" if naked_total == 0
        else f"{naked_total} naked edges ({', '.join(leaky)})"))

    b = _bounds(shape)
    if b is None:
        checks.append(Check("bounds", False, "bounding box is void"))
    else:
        finite = all(math.isfinite(v) and abs(v) < SANE_MM for v in b)
        dx, dy, dz = b[3] - b[0], b[4] - b[1], b[5] - b[2]
        checks.append(Check(
            "bounds", finite,
            f"{dx:.2f} x {dy:.2f} x {dz:.2f} mm" if finite
            else "bounding box is not finite -- degenerate geometry"))

    try:
        vol = shape.Volume()
        pos = vol > 0
        detail = f"{vol / 1000:.1f} cm3"
        if b is not None and finite:
            box_vol = max((b[3] - b[0]) * (b[4] - b[1]) * (b[5] - b[2]), 1e-9)
            if vol > box_vol * 1.001:
                pos, detail = False, (
                    f"{vol / 1000:.1f} cm3 exceeds its own bounding box "
                    f"({box_vol / 1000:.1f} cm3)")
        checks.append(Check("volume", pos, detail))
    except Exception as exc:
        checks.append(Check("volume", False, f"could not be measured: {exc}"))

    return Report(checks)


# --- Printability -----------------------------------------------------------
def _triangles(shape, deflection=0.1):
    """World-space triangles of the tessellated shape: (normal, area, zmin).

    Overhang is a property of the surface, not of the faces the modeller
    happened to make -- a cone is one face with a different normal everywhere,
    and a fillet's normal sweeps through the whole range. Tessellating and
    measuring per triangle handles every surface type the same way; reading a
    single `normalAt` per face would be right only for planes.
    """
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    BRepMesh_IncrementalMesh(shape.wrapped, deflection, False, 0.5, True)
    out = []
    exp = TopExp_Explorer(shape.wrapped, TopAbs_FACE)
    while exp.More():
        face = TopoDS.Face_s(exp.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation_s(face, loc)
        if tri is not None:
            trsf = loc.Transformation()
            reversed_ = face.Orientation() == TopAbs_REVERSED
            nodes = [tri.Node(i).Transformed(trsf)
                     for i in range(1, tri.NbNodes() + 1)]
            for i in range(1, tri.NbTriangles() + 1):
                a, b, c = tri.Triangle(i).Get()
                p, q, r = nodes[a - 1], nodes[b - 1], nodes[c - 1]
                ux, uy, uz = q.X() - p.X(), q.Y() - p.Y(), q.Z() - p.Z()
                vx, vy, vz = r.X() - p.X(), r.Y() - p.Y(), r.Z() - p.Z()
                nx = uy * vz - uz * vy
                ny = uz * vx - ux * vz
                nz = ux * vy - uy * vx
                mag = math.sqrt(nx * nx + ny * ny + nz * nz)
                if mag < 1e-12:
                    continue
                if reversed_:
                    nx, ny, nz = -nx, -ny, -nz
                out.append(((nx / mag, ny / mag, nz / mag), mag / 2.0,
                            min(p.Z(), q.Z(), r.Z()), max(p.Z(), q.Z(), r.Z())))
        exp.Next()
    return out


def overhangs(shape, limit=45.0, deflection=0.1):
    """Downward-facing area shallower than `limit` degrees from horizontal.

    Returns (worst_angle, offending_area, total_downward_area, dominant_angle).
    The angle is measured from the bed: a vertical wall is 90 and prints; a
    flat ceiling is 0 and must be bridged. The face resting on the bed is
    excluded -- it is the first layer, not an overhang.

    `dominant_angle` is where most of the offending area actually sits, and is
    usually the more useful number. A part can have a 0-degree worst case from
    a deliberate 2mm bridge while its real problem is fifteen thousand square
    millimetres at 25 degrees; reporting only the worst hides that.

    Measured on a tessellation, so an angle across a curved surface reads about
    half a degree shallower than the true surface -- the chord is flatter than
    the arc. That bias is toward flagging, which is the right direction for a
    warning.
    """
    if hasattr(shape, "val"):
        shape = shape.val()
    tris = _triangles(shape, deflection)
    if not tris:
        return None, 0.0, 0.0
    bed_z = min(t[2] for t in tris)

    worst, offending, downward = 90.0, 0.0, 0.0
    bands = {}
    for (nx, ny, nz), area, zlo, zhi, in tris:
        if nz >= -1e-6:
            continue                                  # not facing downward
        angle = math.degrees(math.acos(min(1.0, -nz)))
        if angle < 1e-6 and zhi - bed_z < 1e-6:
            continue                                  # the bed contact face
        downward += area
        if angle < limit:
            offending += area
            worst = min(worst, angle)
            band = int(angle // 5) * 5
            bands[band] = bands.get(band, 0.0) + area
    dominant = max(bands, key=bands.get) if bands else None
    return ((worst if offending else None), offending, downward, dominant)


def printable(shape, printer=None, bodies=1, deflection=0.1):
    """Can this machine make it? Bed fit is blocking; overhang is a warning.

    An overhang is a warning because plenty of parts print through one -- with
    support, or because the author decided the droop lands somewhere that does
    not matter. A part larger than the bed is not a matter of judgement.
    """
    from . import printers as _printers

    if hasattr(shape, "val"):
        shape = shape.val()
    printer = printer or _printers.get()
    report = solid(shape, bodies=bodies)
    checks = list(report.checks)

    b = _bounds(shape)
    if b is None or not all(math.isfinite(v) and abs(v) < SANE_MM for v in b):
        checks.append(Check("bed", False,
                            "cannot measure the part -- see bounds above"))
        return Report(checks)

    dx, dy, dz = b[3] - b[0], b[4] - b[1], b[5] - b[2]
    bx, by, bz = printer.bed
    fits = dx <= bx + 1e-2 and dy <= by + 1e-2 and dz <= bz + 1e-2
    over = [f"{n} {v:.1f}>{lim:g}" for n, v, lim
            in (("x", dx, bx), ("y", dy, by), ("z", dz, bz)) if v > lim + 1e-2]
    checks.append(Check(
        "bed", fits,
        f"{dx:.1f} x {dy:.1f} x {dz:.1f} fits {bx:g}x{by:g}x{bz:g}" if fits
        else f"exceeds {printer.name} bed: {', '.join(over)}"))

    try:
        worst, bad_area, down_area, dominant = overhangs(
            shape, printer.max_overhang, deflection)
        if worst is None:
            checks.append(Check(
                "overhang", True,
                f"none below {printer.max_overhang:g} deg"
                f" ({down_area:.0f} mm2 downward)"))
        else:
            checks.append(Check(
                "overhang", False,
                f"{bad_area:.0f} mm2 below {printer.max_overhang:g} deg "
                f"from horizontal; worst {worst:.1f}, most of it near "
                f"{dominant:g}-{dominant + 5:g}", level="warn"))
    except Exception as exc:
        checks.append(Check("overhang", False,
                            f"could not be measured: {exc}", level="warn"))

    return Report(checks)
