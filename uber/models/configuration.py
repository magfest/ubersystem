from typing import Any

from sqlalchemy import String
from sqlalchemy.dialects.postgresql.json import JSONB
from sqlalchemy.ext.mutable import MutableDict

from uber.models import MagModel
from uber.models.types import DefaultField as Field

__all__ = ['Configuration']


class Configuration(MagModel, table=True):
    """One section of runtime-editable settings; see uber.config.DatabaseConfigSection."""
    section_name: str = Field(sa_type=String(255), unique=True)
    config_data: dict[str, Any] = Field(sa_type=MutableDict.as_mutable(JSONB), default_factory=dict)
    version: int = 1
