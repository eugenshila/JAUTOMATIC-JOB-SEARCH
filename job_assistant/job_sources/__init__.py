"""Permitted job-source connector interfaces."""
from .base import JobRecord
from .feed import PublicFeedConnector

__all__ = ["JobRecord", "PublicFeedConnector"]
