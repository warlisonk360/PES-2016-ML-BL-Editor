#!/usr/bin/env python3
"""Entry point for the PES 2016 ML-BL Editor (PC) AppImage."""

import os
import sys

# Make the bundled package importable both from the AppDir and directly.
_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

from pes2016mlbl.gui import run  # noqa: E402

if __name__ == "__main__":
    # Um save pode ser passado como argumento ("abrir com..." / arrastar e
    # soltar): pes2016-mlbl-editor BL00000000
    run(sys.argv[1] if len(sys.argv) > 1 else None)
