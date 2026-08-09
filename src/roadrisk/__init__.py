"""Modular road risk assessment panel.

Layering rule, inherited from the M51 panel and not to be broken:
``roadrisk.core`` is a plain library. It never imports the web, worker or CLI
layers, and it must stay runnable from a script with nothing else installed.
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
