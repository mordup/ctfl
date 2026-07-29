"""Claude Tracker For Linux"""

__version__ = "2.8.0"
__changelog__ = (
    "Token counts were roughly doubled — Claude Code logs one record per "
    "content block, each repeating the same usage. Your figures will drop by "
    "about half; the new ones are correct. Cost estimates now also use current "
    "model pricing and bill cache writes by their actual TTL, and the monthly "
    "spend bar appears for accounts with usage credits."
)
