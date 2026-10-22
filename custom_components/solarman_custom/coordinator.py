"""Data coordinator and token lifecycle for Solarman."""
import datetime
from datetime import timedelta
import logging
from typing import Any

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import PV_INPUT_KEYS, SCAN_INTERVAL_MINUTES, ZERO_WHEN_PV_IDLE_KEYS

_LOGGER = logging.getLogger(__name__)

# Typed config entry: entry.runtime_data holds the coordinator (HA 2024.x+ pattern).
type SolarmanConfigEntry = ConfigEntry[SolarmanDataUpdateCoordinator]

# Shared timeout for all Solarman HTTP calls.
_TIMEOUT = aiohttp.ClientTimeout(total=10)


class SolarmanDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator managing data fetching and the token lifecycle."""

    def __init__(self, hass: HomeAssistant, entry: SolarmanConfigEntry) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Solarman API Coordinator",
            config_entry=entry,
            update_interval=timedelta(minutes=SCAN_INTERVAL_MINUTES),
        )
        self.entry = entry
        self.device_sn = entry.data.get("device_sn")
        self.device_name = entry.data.get("device_name", "Solarman Inverter")

        # READ FROM CACHE: try to load the token saved before the HA restart
        self._token = entry.data.get("access_token")

        expires_ts = entry.data.get("access_token_expires_at")
        if expires_ts:
            try:
                self._token_expires_at = datetime.datetime.fromisoformat(expires_ts)
            except ValueError:
                self._token_expires_at = None
        else:
            self._token_expires_at = None

        if self._token and self._token_expires_at:
            _LOGGER.info(
                "Loaded token from cache. Valid until (UTC): %s",
                self._token_expires_at
            )

    async def _async_get_token(self) -> str:
        """Return the cached token; fetch from the API ONLY after it expires (every ~60 days)."""
        now = datetime.datetime.now(datetime.timezone.utc)

        if self._token and self._token_expires_at and now < self._token_expires_at:
            _LOGGER.debug("Token is still valid. Skipping the login request.")
            return self._token

        _LOGGER.warning("Token expired, missing, or cache is empty. Fetching from the API...")
        appId = self.entry.data.get("app_id")

        url = f"https://globalapi.solarmanpv.com/account/v1.0/token?appId={appId}"

        # entry.data["password"] already holds the SHA256 hash generated in config_flow.py
        payload = {
            "appSecret": self.entry.data.get("app_secret"),
            "email": self.entry.data.get("username"),
            "password": self.entry.data.get("password")
        }

        # Reuse Home Assistant's shared aiohttp session (HA best practice).
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(url, json=payload, timeout=_TIMEOUT) as response:
                if response.status != 200:
                    raise UpdateFailed(f"API login error: status {response.status}")

                res_json = await response.json()

                if not res_json.get("success"):
                    raise UpdateFailed(f"Solarman API denied access: {res_json.get('msg')}")

                self._token = res_json.get("access_token")

                # Convert Solarman's textual "5183999" to int
                expires_in_seconds = int(res_json.get("expires_in", 5183999))

                # Safety buffer: refresh the token 1 day before the 60 days run out
                safety_buffer = 86400
                self._token_expires_at = now + timedelta(seconds=expires_in_seconds - safety_buffer)

                # PERSIST: update the on-disk config file (.storage)
                new_data = {
                    **self.entry.data,
                    "access_token": self._token,
                    "access_token_expires_at": self._token_expires_at.isoformat()
                }
                self.hass.config_entries.async_update_entry(self.entry, data=new_data)

                _LOGGER.info("New token fetched and successfully persisted to disk in HA.")
                return self._token

        except Exception as err:
            if self._token:
                _LOGGER.warning("Token refresh error (%s). Falling back to the cached token.", err)
                return self._token
            raise UpdateFailed(f"Critical Solarman authorization error: {err}")

    async def _async_update_data(self) -> dict[str, Any]:
        """Main data-fetching method run periodically on the polling interval."""
        token = await self._async_get_token()
        app_id = self.entry.data.get("app_id")
        _LOGGER.debug("Fetching current data for device SN %s", self.device_sn)

        # TARGET URL: exactly the one you pointed out in your note
        url = f"https://globalapi.solarmanpv.com/device/v1.0/currentData?appId={app_id}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                url, headers=headers, json={"deviceSn": self.device_sn}, timeout=_TIMEOUT
            ) as response:

                # If the server rejected the token (401), force fetching a new one right away
                if response.status == 401:
                    _LOGGER.warning("Token rejected by the server (401). Clearing cache and retrying...")
                    self._token = None
                    self._token_expires_at = None
                    token = await self._async_get_token()

                    headers = {"Authorization": f"Bearer {token}"}
                    async with session.post(
                        url, headers=headers, json={"deviceSn": self.device_sn}, timeout=_TIMEOUT
                    ) as retry_resp:
                        if retry_resp.status != 200:
                            raise UpdateFailed(f"Error after forced refresh: {retry_resp.status}")
                        result = await retry_resp.json()
                        # Same shape contract as the normal path: sensors expect
                        # {key: {value, unit}}, not the raw API envelope.
                        return self._parse_solarman_data(result)

                if response.status != 200:
                    raise UpdateFailed(f"Error reading data from Solarman: status {response.status}")

                result = await response.json()
                return self._parse_solarman_data(result)

        except UpdateFailed:
            # Already a well-formed coordinator error — don't double-wrap it.
            raise
        except Exception as err:
            raise UpdateFailed(f"Error communicating with the Solarman API: {err}")

    def _parse_solarman_data(self, result: dict) -> dict[str, Any]:
        """Convert the 'dataList' list from the Solarman API into a dict the sensors understand."""
        if not result or "dataList" not in result:
            _LOGGER.warning("No dataList section in the Solarman API response")
            return {}

        raw_list = result.get("dataList", [])

        # Mapping: turn [ {"key": "DV1", "value": "230"}, ... ]
        # into the format: { "DV1": {"value": "230", "unit": "V"}, ... }
        mapped_dict = {}
        for item in raw_list:
            if "key" in item:
                mapped_dict[item["key"]] = {
                    "value": item.get("value"),
                    "unit": item.get("unit")
                }

        self._zero_readings_when_pv_idle(mapped_dict)

        _LOGGER.debug("Successfully parsed Solarman data: %s", mapped_dict)
        return mapped_dict

    @staticmethod
    def _zero_readings_when_pv_idle(data: dict[str, Any]) -> None:
        """Zero the AC output and PV voltage readings when every PV input reports zero.

        After dusk the inverter shuts down and the Solarman cloud keeps serving
        its last snapshot until morning, so AC output and PV voltages would show
        stale non-zero values all night. With no PV power and no PV current those
        readings are forced to 0. Grid voltage, frequency, temperature and energy
        counters are left untouched.
        """
        pv_values = [data[key]["value"] for key in PV_INPUT_KEYS if key in data]
        if not pv_values:
            return
        try:
            if any(float(value) != 0 for value in pv_values):
                return
        except (TypeError, ValueError):
            return

        for key in ZERO_WHEN_PV_IDLE_KEYS:
            if key in data:
                data[key]["value"] = "0"
