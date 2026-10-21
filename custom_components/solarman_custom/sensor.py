"""Sensor platform for the Solarman integration."""
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SolarmanConfigEntry

async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarmanConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform based on the mapped JSON keys."""
    coordinator = entry.runtime_data

    # Sensor list defined using the official 'key' values from the JSON response
    sensor_definitions = [
        ("DV1", SensorDeviceClass.VOLTAGE),
        ("DV2", SensorDeviceClass.VOLTAGE),
        ("DC1", SensorDeviceClass.CURRENT),
        ("DP1", SensorDeviceClass.POWER),
        ("AV1", SensorDeviceClass.VOLTAGE),
        ("AC1", SensorDeviceClass.CURRENT),
        ("A_Fo1", SensorDeviceClass.FREQUENCY),
        ("APo_t1", SensorDeviceClass.POWER),
        ("Et_ge0", SensorDeviceClass.ENERGY),
        ("Etdy_ge1", SensorDeviceClass.ENERGY),
        ("E_Puse_t1", SensorDeviceClass.POWER),
        ("INV_T0", SensorDeviceClass.TEMPERATURE),
    ]

    sensors = [
        SolarmanSensor(coordinator, json_key, device_class)
        for json_key, device_class in sensor_definitions
    ]

    async_add_entities(sensors)


class SolarmanSensor(CoordinatorEntity, SensorEntity):
    """Representation of a single Solarman reading within the shared device."""

    def __init__(self, coordinator, json_key: str, device_class):
        """Initialize the sensor and bind it to the coordinator."""
        super().__init__(coordinator)
        self._json_key = json_key

        self._attr_has_entity_name = True
        # self._attr_name = name_suffix
        self._attr_device_class = device_class
        self._attr_unique_id = f"{coordinator.device_sn}_{json_key}"

        # TRANSLATION KEY: HA looks up this key (lowercase) in translations/*.json
        self._attr_translation_key = json_key.lower()

        # Dynamically assign the state class for proper charts and long-term statistics
        if device_class in (SensorDeviceClass.ENERGY,):
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        else:
            self._attr_state_class = SensorStateClass.MEASUREMENT

        # GROUPING: merge all entries into one readable device in the HA Devices tab
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.device_sn)},
            name=coordinator.device_name,
            manufacturer="Solarman",
            model="Inverter Cloud Connection",
        )

    @property
    def native_value(self):
        """Safely extract the value from the data dict provided by the coordinator."""
        if not self.coordinator.data or self._json_key not in self.coordinator.data:
            return None

        raw_value = self.coordinator.data[self._json_key].get("value")

        # Convert the textual numeric value from JSON into a plain float/int for HA statistics
        try:
            if "." in str(raw_value):
                return round(float(raw_value), 2)
            return int(raw_value)
        except (ValueError, TypeError):
            return raw_value  # If it's text (e.g. a status), return it unchanged as a text status

    @property
    def native_unit_of_measurement(self):
        """Dynamically assign the unit of measurement straight from the coordinator data."""
        if not self.coordinator.data or self._json_key not in self.coordinator.data:
            return None
        raw_unit = self.coordinator.data[self._json_key].get("unit")

        # Convert the ℃ notation to the official Home Assistant display standard
        if raw_unit == "℃":
            return "°C"
        return raw_unit
