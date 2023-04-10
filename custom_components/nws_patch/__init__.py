"""Package definition for nws_patch."""
from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any, TypedDict, cast

from homeassistant.components.weather import (
    ATTR_FORECAST_NATIVE_TEMP,
    ATTR_FORECAST_NATIVE_TEMP_LOW,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.dt import parse_datetime

if TYPE_CHECKING:
    from homeassistant.components.nws.weather import NWSWeather
    from homeassistant.components.weather import WeatherEntity

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


NWS_FORECAST_PROP: Callable[[NWSWeather], Any] | None = None
NWS_STATE_ATTRIBUTE_PROP: Callable[[WeatherEntity], Any] | None = None


async def async_setup(hass: HomeAssistant, config: ConfigType, tries: int = 1) -> bool:
    """Extract original properties to allow install/uninstall without restarting."""

    _LOGGER.info("Getting ready to patch NWSWeather")
    try:
        from homeassistant.components.nws.weather import (  # pylint: disable=import-outside-toplevel
            NWSWeather,
        )
    except ModuleNotFoundError:
        await retry_setup(hass, config, tries, async_setup)
        return True

    # only copy out the props if we haven't prior, preventing a potential mixup
    global NWS_FORECAST_PROP  # pylint: disable=global-statement
    if NWS_FORECAST_PROP is None:
        NWS_FORECAST_PROP = NWSWeather.forecast

    global NWS_STATE_ATTRIBUTE_PROP  # pylint: disable=global-statement
    if NWS_STATE_ATTRIBUTE_PROP is None:
        NWS_STATE_ATTRIBUTE_PROP = NWSWeather.state_attributes

    return NWS_FORECAST_PROP is not None and NWS_STATE_ATTRIBUTE_PROP is not None


async def async_setup_entry(
    hass: HomeAssistant, config: ConfigType, tries: int = 1
) -> bool:
    """Patch the NWS forecast and state_attributes functions."""

    try:
        from homeassistant.components.nws.const import (  # pylint: disable=hass-component-root-import,import-outside-toplevel
            DAYNIGHT,
        )
        from homeassistant.components.nws.weather import (  # pylint: disable=import-outside-toplevel
            NWSWeather,
        )
    except ModuleNotFoundError:
        await retry_setup(hass, config, tries, async_setup_entry)
        return True

    class NWSWrap(NWSWeather):
        """Simple "class" to make typing a new property on the original class easier."""

        detailed_forecast: property

    def set_detailed_forecast(self: NWSWrap, forecast: str) -> None:
        _LOGGER.debug("setting detailed forecast: %s", forecast)
        setattr(self, "_detailed_forecast", forecast)

    def get_detailed_forecast(self: NWSWrap) -> str:
        _LOGGER.debug("getting detailed forecast")
        forecast = getattr(self, "_detailed_forecast", "")
        _LOGGER.debug(forecast)
        return forecast

    cast(  # pylint: disable=assignment-from-no-return
        NWSWrap, NWSForecast
    ).detailed_forecast = property(  # pylint: disable=too-many-function-args
        get_detailed_forecast
    ).setter(
        set_detailed_forecast
    )
    _LOGGER.debug("added detailed forecast property")

    def daily_forecast(self: NWSWrap) -> list[NewForecast] | list[NWSForecast] | None:
        """Convert the normal forecast to a daily forecast."""

        _LOGGER.debug("running for mode %s", self.mode)

        if NWS_FORECAST_PROP is None:
            _LOGGER.error("NWS forecast property has gone missing! :(")
            return cast(list[NWSForecast], [])

        # get the original forecast, and if none return none
        orig_forecast: list[
            NWSForecast
        ] | None = NWS_FORECAST_PROP.__get__(  # pylint: disable=unnecessary-dunder-call
            self
        )
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
                single_fcast = _convert_single_fcast(fcasts)
                forecast.append(single_fcast)
            elif len(fcasts) >= 2:
                new_fcast = _merge_fcasts(fcasts)
                if new_fcast:
                    forecast.append(new_fcast)
                else:
                    _LOGGER.warning(
                        "Day %s is unable to merge multiple forecasts: %s", day, fcasts
                    )
            else:
                _LOGGER.warning("Day %s has no forecasts: %s", day, fcasts)

        (first, second) = ("Tonight", "Tomorrow") if tomorrow else ("Today", "Tonight")
        description = f"### {first}\n"
        description += f"{orig_forecast[0]['detailed_description']}\n"
        description += f"### {second}\n"
        description += f"{orig_forecast[1]['detailed_description']}"

        self.detailed_forecast = description

        _LOGGER.debug("new forecast: %s", forecast)
        return forecast

    _LOGGER.info("Patching forecast")
    NWSWeather.forecast = property(daily_forecast)  # type: ignore[assignment]

    def add_detailed_description_state(self: NWSWrap) -> dict[str, Any]:
        if NWS_STATE_ATTRIBUTE_PROP is None:
            _LOGGER.error("NWS state attribute prop has gone missing :(")
            return {}

        state: dict[
            str, Any
        ] = NWS_STATE_ATTRIBUTE_PROP.__get__(  # pylint: disable=unnecessary-dunder-call
            self
        )

        if self.mode == DAYNIGHT:
            state["detailed_forecast"] = self.detailed_forecast

        return state

    _LOGGER.info("Patching state_attributes")
    NWSWeather.state_attributes = property(add_detailed_description_state)  # type: ignore[assignment, misc]

    _LOGGER.info("NWSWeather patched :3")

    return True


async def async_remove_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> None:
    """Restore original NWS forecast behavior on removal."""

    # remove unused required parameters
    del hass
    del config_entry

    _LOGGER.info("Removing nws forecast patch")

    from homeassistant.components.nws.weather import (  # pylint: disable=import-outside-toplevel
        NWSWeather,
    )

    NWSWeather.forecast = NWS_FORECAST_PROP  # type: ignore[assignment]
    NWSWeather.state_attributes = NWS_STATE_ATTRIBUTE_PROP  # type: ignore[assignment, misc]

    _LOGGER.info("Removed nws forecast path :c")


async def retry_setup(
    hass: HomeAssistant,
    config: ConfigType,
    tries: int,
    callback: Callable[[HomeAssistant, ConfigType, int], Coroutine[Any, Any, bool]],
) -> None:
    """Schedule a callback in 2 seconds in HA."""

    if tries > 10:
        _LOGGER.error(
            "Unable to patch nws component as pynws is not available after %d tries",
            tries - 1,
        )
        return

    tries = tries + 1
    _LOGGER.info("Package pynws not installed yet. scheduling try %d", tries)

    async def call_again(date: datetime) -> None:
        del date
        await callback(hass, config, tries)

    async_call_later(hass, timedelta(seconds=1), call_again)


def _merge_fcasts(fcasts: list[NWSForecast]) -> NewForecast | None:
    try:
        daycast = max(
            (f for f in fcasts if f["daytime"]), key=lambda item: item["datetime"]
        )
        nightcast = max(
            (f for f in fcasts if not f["daytime"]), key=lambda item: item["datetime"]
        )
    except ValueError:
        return None

    description = "### Day\n"
    description += daycast["detailed_description"].strip()
    description += "\n\n### Night\n"
    description += nightcast["detailed_description"].strip()

    merged = {**daycast}
    merged["detailed_description"] = description
    merged[ATTR_FORECAST_NATIVE_TEMP_LOW] = nightcast[ATTR_FORECAST_NATIVE_TEMP]

    return cast(NewForecast, merged)


def _convert_single_fcast(fcasts: list[NWSForecast]) -> NewForecast:
    title = "Day"

    new_cast = {**fcasts[0]}

    if not new_cast["daytime"]:
        title = "Night"
        new_cast[ATTR_FORECAST_NATIVE_TEMP_LOW] = new_cast[ATTR_FORECAST_NATIVE_TEMP]
        del new_cast[ATTR_FORECAST_NATIVE_TEMP]

    description = f"### {title}\n"
    description += cast(NWSForecast, new_cast)["detailed_description"].strip()
    new_cast["detailed_description"] = description
    del new_cast["daytime"]

    return cast(NewForecast, new_cast)
