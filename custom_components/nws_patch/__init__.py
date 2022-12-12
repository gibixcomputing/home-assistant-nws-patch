"""Package definition for nws_patch."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import logging
from typing import Any, TypedDict, cast

from homeassistant.components.weather import (
    ATTR_FORECAST_NATIVE_TEMP,
    ATTR_FORECAST_NATIVE_TEMP_LOW,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.dt import parse_datetime

_LOGGER = logging.getLogger(__name__)


class NWSForecast(TypedDict):
    """Strong type for incoming NWS forecast data."""

    detailed_description: str
    datetime: str
    daytime: bool
    native_temperature: float


class NewForecast(TypedDict):
    """Strong type for outgoing modified NWS forecast data."""

    detailed_description: str
    datetime: str
    native_temperature: float
    native_templow: float


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Patch NWS forecast and state_attributes methods on setup."""

    # remove unused arguments
    del hass
    del config

    _LOGGER.info("getting ready to patch NWSWeather")
    from homeassistant.components.nws.const import DAYNIGHT
    from homeassistant.components.nws.weather import NWSWeather

    class NWSWrap(NWSWeather):
        detailed_forecast: property

    def set_detailed_forecast(self: NWSWrap, forecast: str) -> None:
        _LOGGER.debug("setting detailed forecast: %s", forecast)
        setattr(self, "_detailed_forecast", forecast)

    def get_detailed_forecast(self: NWSWrap) -> str:
        _LOGGER.debug("getting detailed forecast")
        forecast = getattr(self, "_detailed_forecast", "")
        _LOGGER.debug(forecast)
        return forecast

    cast(NWSWrap, NWSWeather).detailed_forecast = property(
        get_detailed_forecast
    ).setter(set_detailed_forecast)
    _LOGGER.debug("added detailed forecast property")

    nws_forecast = NWSWeather.forecast

    def daily_forecast(self: NWSWrap) -> list[NewForecast] | list[NWSForecast] | None:
        """Convert the normal forecast to a daily forecast."""

        _LOGGER.debug("running for mode %s", self.mode)

        # get the original forecast, and if none return none
        orig_forecast: list[NWSForecast] | None = nws_forecast.__get__(self)
        if not orig_forecast:
            return None

        # if this is not the DAYNIGHT forecast return it unaltered.
        if self.mode != DAYNIGHT:
            _LOGGER.debug("returning original forecast for mode %s", self.mode)
            return orig_forecast

        bucket: dict[datetime, list[NWSForecast]] = defaultdict(list)
        for item in orig_forecast:
            date = parse_datetime(item["datetime"])
            if not date:
                continue

            date = date.replace(hour=0, minute=0, second=0, microsecond=0)
            bucket[date].append(item)

        _LOGGER.debug("buckets: %s", bucket)

        forecast: list[NewForecast] = []
        tomorrow = False
        for day, fcasts in bucket.items():
            _LOGGER.debug("bucket: %s: %d", day, len(fcasts))
            if len(fcasts) == 1:
                tomorrow = True
                updated = {**fcasts[0]}
                if not updated["daytime"]:
                    updated[ATTR_FORECAST_NATIVE_TEMP_LOW] = updated[
                        ATTR_FORECAST_NATIVE_TEMP
                    ]
                    del updated[ATTR_FORECAST_NATIVE_TEMP]

                del updated["daytime"]

                forecast.append(cast(NewForecast, updated))
            elif len(fcasts) == 2:
                daytime = [f for f in fcasts if f["daytime"]][0]
                nighttime = [f for f in fcasts if not f["daytime"]][0]

                merged = {**daytime}
                merged[
                    "detailed_description"
                ] = f"### Day\n{daytime['detailed_description'].strip()}\n\n### Night\n{nighttime['detailed_description'].strip()}"

                merged[ATTR_FORECAST_NATIVE_TEMP_LOW] = nighttime[
                    ATTR_FORECAST_NATIVE_TEMP
                ]
                forecast.append(cast(NewForecast, merged))
            else:
                if fcasts:
                    _LOGGER.warning("day %s has more than 2 forecasts: %s", day, fcasts)
                else:
                    _LOGGER.warning("day %s has no forecasts", day)

        (first, second) = ("Tonight", "Tomorrow") if tomorrow else ("Today", "Tonight")
        description = f"### {first}\n"
        description += f"{orig_forecast[0]['detailed_description']}\n"
        description += f"### {second}\n"
        description += f"{orig_forecast[1]['detailed_description']}"

        self.detailed_forecast = description

        _LOGGER.debug("new forecast: %s", forecast)
        return forecast

    _LOGGER.info("patching forecast")
    NWSWeather.forecast = property(daily_forecast)  # type: ignore[assignment]

    nws_state_attributes = NWSWeather.state_attributes

    def add_detailed_description_state(self: NWSWrap) -> dict[str, Any]:
        state: dict[str, Any] = nws_state_attributes.__get__(self)

        if self.mode == DAYNIGHT:
            state["detailed_forecast"] = self.detailed_forecast

        return state

    _LOGGER.info("patching state_attributes")
    NWSWeather.state_attributes = property(add_detailed_description_state)  # type: ignore[assignment, misc]

    _LOGGER.info("NWSWeather patched :3")

    return True


async def async_setup_entry(hass: HomeAssistant, config: ConfigType) -> bool:
    """Needed for config_flow to work, do nothing and return True."""

    # remove unused required parameters
    del hass
    del config
    return True
