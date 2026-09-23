"""Reconstruct a presentation from a recorded talk."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("extract-slides")
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"

__all__ = ["__version__"]
