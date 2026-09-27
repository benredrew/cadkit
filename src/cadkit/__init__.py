# Author: Claude (Opus 5)
# Co-Author: Brendan Fennell
"""Shared CAD workflow helpers, used by every CAD project on this machine.

Three capabilities, deliberately independent of one another:

    modelling   CadQuery itself, plus the project's own part scripts
    viewing     cadkit.viewer -- launch a viewer, find one, or carry on
    drawings    cadkit.sheet  -- orthographic drawing sheets

**Importing this package connects to nothing and launches nothing.** Building
a model must not require a viewer to be running or a sheet to be produced, so
neither submodule is imported here; ask for the one you want:

    from cadkit import viewer, sheet

`cadkit.viewer.show` is a no-op when no viewer is listening -- it says so and
returns False rather than raising -- so the same part script runs identically
whether or not anyone is watching it.
"""
__all__ = ["viewer", "sheet", "check"]
