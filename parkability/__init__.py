"""parkability — an "ease of parking" metric for Chicago, by ward / community area / zip.

A ward-wise-civic-tech direct-metric source (sibling to chainshare): pull parking
supply and scarcity signals, roll them up by geography, and publish summaries the
Penlight explorer ingests at the ward level.
"""

from .pipeline import PARKING_METRIC, PERMIT_METRIC, run

__all__ = ["run", "PARKING_METRIC", "PERMIT_METRIC"]
__version__ = "0.1.0"
