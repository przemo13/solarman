"""Initialization of the Solarman Cloud integration."""
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import SolarmanDataUpdateCoordinator
from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the integration when added via the UI or on HA start."""
    _LOGGER.info("Starting Solarman integration for device: %s", entry.data.get("device_name"))

    # Create the coordinator instance that manages token caching and data
    coordinator = SolarmanDataUpdateCoordinator(hass, entry)

    # First data fetch on startup (uses the stored token or fetches a new one)
    await coordinator.async_config_entry_first_refresh()

    # Store the coordinator in HA's shared data
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    # Forward the config to the sensor platform
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Handle a clean shutdown or removal of the integration by the user."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)

    return unload_ok
