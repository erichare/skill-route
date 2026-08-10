"""SkillRoute core package."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _package_version

from skillroute.catalog import Catalog, default_catalog_path
from skillroute.models import SkillRecord
from skillroute.routing import Router

__all__ = ["Catalog", "Router", "SkillRecord", "default_catalog_path"]

try:
    __version__ = _package_version("skillroute")
except PackageNotFoundError:  # pragma: no cover - only hit when run from an unbuilt tree
    __version__ = "0.0.0.dev0"
