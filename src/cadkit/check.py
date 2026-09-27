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
    """One finding: what was asked, whether it held, and the measurement."""

    def __init__(self, name, ok, detail):
        self.name, self.ok, self.detail = name, ok, detail

    def __repr__(self):
        return f"{'ok  ' if self.ok else 'FAIL'} {self.name}: {self.detail}"


class Report:
    def __init__(self, checks):
        self.checks = checks

    @property
    def ok(self):
        return all(c.ok for c in self.checks)

    @property
    def failures(self):
        return [c for c in self.checks if not c.ok]

    def line(self):
        """One line for a part script to print. Silence is not evidence."""
        if self.ok:
            return "check        " + ", ".join(c.detail for c in self.checks)
        return "check        FAILED -- " + "; ".join(
            f"{c.name}: {c.detail}" for c in self.failures
        )

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
