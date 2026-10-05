"""Sports analytics on top of the interpreter: the kind of metrics Opta, StatsBomb, SkillCorner and
Second Spectrum publish, computed from the synthetic feed. See ``docs/analytics.md``."""

from .store import load_models, save_models

__all__ = ["load_models", "save_models"]
