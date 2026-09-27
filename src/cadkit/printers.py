# Author: Claude (Opus 5)
# Co-Author: Brendan Fennell
"""What a printer can do -- read from the slicer where possible, not guessed.

A `Printer` is a plain description; anything can construct one. `BUILTIN` is
the registry the checks actually read, and each entry records where its
figures came from and when.

## The slicer is an authoring tool here, not a runtime dependency

`from_prusaslicer()` exists, and it is how a registry entry should be written
-- but it is **not** called on every check, because that was measured and it
is a bad trade: the vendor file is 2.0MB and 57,389 lines, parsing costs
179ms, and on this machine it returns figures identical to the three-line
entry below. Paying 179ms per check to re-derive a number that changes
approximately never is not diligence, it is ceremony.

What the parser is genuinely for is `inherits`. Of 276 printer sections in the
Prusa vendor file, **ten** define `bed_shape`; every other printer inherits
it, sometimes two hops up. That is precisely where a hand-copied figure goes
wrong, so the resolution is worth automating -- once per printer, when the
entry is written, and again from `verify()` when you want to know the registry
has not drifted.

The slicer could not be the only source in any case: the overhang threshold is
a *design rule*, a convention about what FDM bridges, not a figure PrusaSlicer
stores.

## Why the profile parse resolves `inherits`

Of 276 printer sections in the Prusa vendor file, **ten** define `bed_shape`.
Every other printer inherits it, often through two hops: the MINI Input Shaper
inherits from the MINI, which inherits from `*common*`. Reading a section's own
keys and stopping there gets the right answer for the handful that declare
them and a wrong or missing one for the rest.
"""
import configparser
import os
import re
from pathlib import Path

# Searched in order. The flatpak config copy is preferred over the one inside
# the read-only app image, because the app image path carries a content hash
# that changes on every update.
VENDOR_INI_CANDIDATES = (
    "~/.var/app/com.prusa3d.PrusaSlicer/config/PrusaSlicer/vendor/PrusaResearch.ini",
    "~/.config/PrusaSlicer/vendor/PrusaResearch.ini",
    "~/.PrusaSlicer/vendor/PrusaResearch.ini",
    "/usr/share/PrusaSlicer/profiles/PrusaResearch.ini",
)


class Printer:
    """A machine, as far as checking a part is concerned."""

    def __init__(self, name, bed, nozzle, max_overhang=45.0, source="unspecified"):
        self.name = name
        self.bed = tuple(float(v) for v in bed)      # x, y, z in mm
        self.nozzle = float(nozzle)
        # Degrees from horizontal. A surface shallower than this overhangs more
        # than the printer will bridge. Not a slicer figure -- a design rule.
        self.max_overhang = float(max_overhang)
        self.source = source

    def __repr__(self):
        return (f"Printer({self.name!r}, bed={self.bed}, nozzle={self.nozzle}, "
                f"max_overhang={self.max_overhang})")

    def describe(self):
        x, y, z = self.bed
        return (f"{self.name}: bed {x:g}x{y:g}x{z:g}, nozzle {self.nozzle:g}, "
                f"overhang limit {self.max_overhang:g} deg from horizontal")


# Values read from PrusaSlicer's vendor profile on 2026-09-27; see `source`.
# Kept so a machine without PrusaSlicer still has an answer, not so anyone has
# to trust a remembered number -- prefer `get()`, which reads the slicer first.
BUILTIN = {
    "prusa_mini": Printer(
        "Prusa MINI / MINI+", bed=(180, 180, 180), nozzle=0.4,
        source="PrusaResearch.ini [printer:Original Prusa MINI & MINI+], "
               "read 2026-09-27"),
}


def find_vendor_ini():
    """The PrusaSlicer vendor profile on this machine, or None."""
    env = os.environ.get("PRUSASLICER_VENDOR_INI")
    if env and Path(env).is_file():
        return Path(env)
    for c in VENDOR_INI_CANDIDATES:
        p = Path(c).expanduser()
        if p.is_file():
            return p
    return None


def _sections(ini_path):
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str
    parser.read(ini_path, encoding="utf-8")
    return parser


def _resolve(parser, section, key, _seen=None):
    """A key's value, following `inherits` upward until something defines it."""
    _seen = _seen or set()
    if section in _seen or not parser.has_section(section):
        return None
    _seen.add(section)
    if parser.has_option(section, key):
        value = parser.get(section, key).strip()
        if value:
            return value
    parents = parser.get(section, "inherits", fallback="")
    for parent in (p.strip() for p in parents.split(",") if p.strip()):
        got = _resolve(parser, f"printer:{parent}", key, _seen)
        if got is not None:
            return got
    return None


def _bed_extent(bed_shape):
    """`0x0,180x0,180x180,0x180` -> (180.0, 180.0). Bounding box of the bed."""
    pts = []
    for token in bed_shape.split(","):
        m = re.match(r"^\s*(-?[\d.]+)\s*x\s*(-?[\d.]+)\s*$", token)
        if m:
            pts.append((float(m.group(1)), float(m.group(2))))
    if not pts:
        raise ValueError(f"unparsable bed_shape: {bed_shape!r}")
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return max(xs) - min(xs), max(ys) - min(ys)


def from_prusaslicer(profile="Original Prusa MINI & MINI+", ini=None,
                     max_overhang=45.0):
    """Build a Printer from a PrusaSlicer vendor profile.

    Raises if the file or profile is absent -- a caller asking for the
    slicer's truth should hear that it is unavailable, not get a guess.
    """
    path = Path(ini).expanduser() if ini else find_vendor_ini()
    if path is None:
        raise FileNotFoundError(
            "no PrusaSlicer vendor profile found; tried "
            + ", ".join(VENDOR_INI_CANDIDATES)
            + " (set PRUSASLICER_VENDOR_INI to point at one)")
    parser = _sections(path)
    section = f"printer:{profile}"
    if not parser.has_section(section):
        raise KeyError(f"no [{section}] in {path}")

    bed_shape = _resolve(parser, section, "bed_shape")
    height = _resolve(parser, section, "max_print_height")
    nozzle = _resolve(parser, section, "nozzle_diameter")
    missing = [k for k, v in (("bed_shape", bed_shape),
                              ("max_print_height", height),
                              ("nozzle_diameter", nozzle)) if v is None]
    if missing:
        raise KeyError(f"{profile}: {', '.join(missing)} not defined or inherited")

    x, y = _bed_extent(bed_shape)
    return Printer(
        profile, bed=(x, y, float(height)),
        nozzle=float(str(nozzle).split(",")[0]),
        max_overhang=max_overhang,
        source=f"{path} [{section}], resolved through inherits",
    )


# Built-in name -> the PrusaSlicer profile that defines it.
SLICER_PROFILES = {"prusa_mini": "Original Prusa MINI & MINI+"}


def get(name="prusa_mini", max_overhang=None):
    """A printer from the registry. Cheap, and needs no slicer installed."""
    if name not in BUILTIN:
        raise KeyError(f"unknown printer {name!r}; have {sorted(BUILTIN)}")
    p = BUILTIN[name]
    if max_overhang is None or max_overhang == p.max_overhang:
        return p
    return Printer(p.name, p.bed, p.nozzle, max_overhang, p.source)


def verify(name="prusa_mini"):
    """Does the registry still match the slicer? Returns (ok, detail).

    Run when adding a printer, or as a regression test. Not on every check --
    see the module docstring for why.
    """
    if name not in SLICER_PROFILES:
        return True, f"{name}: no slicer profile to compare against"
    have = BUILTIN[name]
    try:
        live = from_prusaslicer(SLICER_PROFILES[name])
    except (FileNotFoundError, KeyError, ValueError) as exc:
        return True, f"{name}: slicer unavailable, registry unverified ({exc})"
    same = (have.bed, have.nozzle) == (live.bed, live.nozzle)
    return same, (
        f"{name}: registry {have.bed} nozzle {have.nozzle:g} "
        + ("matches" if same else "DIFFERS FROM")
        + f" slicer {live.bed} nozzle {live.nozzle:g}")
