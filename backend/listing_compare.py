"""Compatibility shim for Suggested-vs-Live listing comparison.

Canonical implementation: `reporting.listing_content`.
"""
from reporting.listing_content import *  # noqa: F401,F403
from reporting.listing_content import _normalized_record, _parse_upload  # noqa: F401
