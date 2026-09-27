# Author: Claude (Opus 5)
# Co-Author: Brendan Fennell
"""Orthographic drawing sheets from CadQuery solids.

    import drafting
    drafting.sheet(solid, "output/part_sheet.svg", "PART NAME",
                   fields=[("PART", "part.py"), ("ENVELOPE", "100 x 50 x 20")])

See `sheet.py` for what the sheet contains and why it does not use
`cq.exporters`' SVG output.
"""
from .sheet import (                      # noqa: F401
    STANDARD,
    VIEW_FRONT,
    VIEW_ISO,
    VIEW_PLAN,
    VIEW_SECTION,
    sheet,
)

__all__ = ["sheet", "STANDARD", "VIEW_FRONT", "VIEW_SECTION", "VIEW_PLAN", "VIEW_ISO"]
