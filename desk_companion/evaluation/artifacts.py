"""Private attempt storage, including read compatibility for original batches."""
from pathlib import Path


def attempt_profile(output):
    output=Path(output)
    compact=output/'p';legacy=output/'private-profile'
    return legacy if legacy.is_dir()and not compact.exists()else compact
