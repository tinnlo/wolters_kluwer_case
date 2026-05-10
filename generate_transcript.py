"""Compatibility shim — re-exports everything from src/generate_transcript.

The module was moved to src/generate_transcript.py. Existing consumers
(tests, automation) that import from the top-level ``generate_transcript``
module continue to work via this shim.
"""
from src.generate_transcript import *  # noqa: F401, F403
from src.generate_transcript import _count_unique_source_urls  # noqa: F401
