"""Compatibility import: report and Astra use the same retrieval/comparison functions."""
import sys
from ptm_shared import finding_literature as _shared
sys.modules[__name__] = _shared
