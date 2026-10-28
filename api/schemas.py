"""Request and response shapes for the API.

Both databases use these, so SQL and Mongo return the same JSON.
Field names match the API contract in HANDOFF.md.
"""
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TrafficRecord(BaseModel):
    """One hourly record. Used for POST and for every response."""

    date_time: datetime = Field(..., examples=["2018-10-01T00:00:00"])
    traffic_volume: int = Field(..., ge=0, examples=[812])
    temp: float = Field(..., gt=0, description="Kelvin", examples=[281.3])
    rain_1h: float = Field(0.0, ge=0, examples=[0.0])
    snow_1h: float = Field(0.0, ge=0, examples=[0.0])
    clouds_all: float = Field(0.0, ge=0, le=100, examples=[40.0])
    weather_main: str = Field(..., max_length=20, examples=["Clouds"])
    is_holiday: int = Field(0, ge=0, le=1, examples=[0])
    is_imputed: int = Field(0, ge=0, le=1, examples=[0])


class TrafficRecordUpdate(BaseModel):
    """PUT body. Send only the fields you want to change.

    date_time is not here: it is the record's key, so it can't change.
    """

    traffic_volume: Optional[int] = Field(None, ge=0)
    temp: Optional[float] = Field(None, gt=0)
    rain_1h: Optional[float] = Field(None, ge=0)
    snow_1h: Optional[float] = Field(None, ge=0)
    clouds_all: Optional[float] = Field(None, ge=0, le=100)
    weather_main: Optional[str] = Field(None, max_length=20)
    is_holiday: Optional[int] = Field(None, ge=0, le=1)
    is_imputed: Optional[int] = Field(None, ge=0, le=1)
