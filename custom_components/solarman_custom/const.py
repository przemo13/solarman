DOMAIN = "solarman_custom"
# DEFAULT_SCAN_INTERVAL = 1200  # The Solarman cloud usually updates about every 20 min
# Refresh interval for pulling sensor data from the Solarman cloud (in minutes)
SCAN_INTERVAL_MINUTES = 15

# PV input readings (power and current per string); keys missing from the API response are skipped
PV_INPUT_KEYS = ("DP1", "DP2", "DC1", "DC2")
# Readings forced to 0 when every PV input above reports 0: the AC output and the PV string voltages
ZERO_WHEN_PV_IDLE_KEYS = ("APo_t1", "AC1", "DV1", "DV2")
