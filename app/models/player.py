from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class Player(BaseModel):
    """The processed player shape exposed by the API."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    club_id: UUID
    position_id: UUID
    player_name: str
    value: float
    attacking_ability: int = Field(ge=0, le=100)
    defensive_ability: int = Field(ge=0, le=100)
    kicking_ability: int = Field(ge=0, le=100)
    discipline: int = Field(ge=0, le=100)
    consistency: int = Field(ge=0, le=100)
    fitness: int = Field(ge=0, le=100)
    current_form: int = Field(ge=0, le=100)
