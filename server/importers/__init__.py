"""Bringing recordings in from elsewhere.

An imported recording carries a strictly weaker evidence set than one this
project captured, and the admissibility rule (SS3.2) then does what it should:
a claim with nothing to cite is not made. That is the rule working, and it is
worth watching happen.
"""

from server.importers.devtools import import_devtools
from server.importers.transcript import describe, load_transcript

__all__ = ["describe", "import_devtools", "load_transcript"]
