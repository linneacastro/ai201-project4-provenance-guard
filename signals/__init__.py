"""Detection signals for Provenance Guard."""

from .llm import classify_with_llm
from .stylometry import classify_with_stylometry

__all__ = ["classify_with_llm", "classify_with_stylometry"]
