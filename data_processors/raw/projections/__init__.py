"""Projection site Phase 2 processors."""

from data_processors.raw.projections.numberfire_processor import NumberFireProjectionsProcessor
from data_processors.raw.projections.fantasypros_processor import FantasyProsProjectionsProcessor
from data_processors.raw.projections.dailyfantasyfuel_processor import DailyFantasyFuelProjectionsProcessor
from data_processors.raw.projections.dimers_processor import DimersProjectionsProcessor

__all__ = [
    'NumberFireProjectionsProcessor',
    'FantasyProsProjectionsProcessor',
    'DailyFantasyFuelProjectionsProcessor',
    'DimersProjectionsProcessor',
]
