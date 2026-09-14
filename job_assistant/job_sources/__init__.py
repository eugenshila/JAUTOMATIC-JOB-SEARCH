"""Permitted job-source connector interfaces."""
from .base import JobRecord
from .catalog import SOURCE_CATALOG, SOURCE_NAMES, SourceDefinition
from .feed import PublicFeedConnector

__all__ = ["JobRecord", "PublicFeedConnector", "SOURCE_CATALOG", "SOURCE_NAMES", "SourceDefinition"]
