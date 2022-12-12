"""Config flow for nws_patch."""
from __future__ import annotations

from typing import Any

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResult


class NWSPatchConfigFlow(config_entries.ConfigFlow, domain="nws_patch"):
    """Provide super basic config flow."""

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Run user step, registering our entity automatically."""
        del user_input  # user_input is not used

        await self.async_set_unique_id("nws_patch")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(title="Patched NWS Forecast", data={})
