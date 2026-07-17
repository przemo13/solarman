"""Configuration form (Config Flow) for the Solarman integration."""
import logging
import hashlib  # NEEDED FOR SHA256
import voluptuous as vol
import aiohttp

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Definition of the form fields shown to the user in the HA interface
DATA_SCHEMA = vol.Schema(
    {
        vol.Required("device_name", default="My Solarman Inverter"): str,
        vol.Required("device_sn"): str,
        vol.Required("app_id"): str,
        vol.Required("app_secret"): str,
        vol.Required("username"): str,
        vol.Required("password"): str,
    }
)

class SolarmanCustomConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Solarman integration configuration process through the user interface."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Step invoked when the user manually adds the integration."""
        errors = {}

        if user_input is not None:
            # PASSWORD HASHING: convert the plain password into a hex SHA256 hash
            raw_password = user_input["password"]
            hashed_password = hashlib.sha256(raw_password.encode("utf-8")).hexdigest()

            # Replace the password in the user dict so we store the secure form
            user_input["password"] = hashed_password

            # SET UNIQUE ID: prevents adding the same inverter twice.
            # Done BEFORE the try/except below: _abort_if_unique_id_configured()
            # raises AbortFlow as a control-flow signal that HA's flow manager
            # must receive. Inside the broad "except Exception" it would be
            # swallowed and shown to the user as a generic "unknown" error.
            await self.async_set_unique_id(user_input["device_sn"])
            self._abort_if_unique_id_configured()

            app_id = user_input["app_id"]
            # Data validation: attempt a first API login using the hash
            url = f"https://globalapi.solarmanpv.com/account/v1.0/token?appId={app_id}"
            payload = {
                "appSecret": user_input["app_secret"],
                "email": user_input["username"],
                "password": user_input["password"]  # Send the SHA256 hash
            }

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(url, json=payload, timeout=10) as response:
                        if response.status != 200:
                            errors["base"] = "invalid_auth"
                        else:
                            res_json = await response.json()
                            if not res_json.get("success"):
                                errors["base"] = "invalid_auth"
                            else:
                                # All OK -> create the entry in Home Assistant
                                return self.async_create_entry(
                                    title=user_input["device_name"],
                                    data=user_input
                                )
            except aiohttp.ClientError:
                errors["base"] = "cannot_connect"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected error while verifying Solarman credentials")
                errors["base"] = "unknown"

        # If the user just opened the form or errors occurred, show the window again
        return self.async_show_form(
            step_id="user", data_schema=DATA_SCHEMA, errors=errors
        )
