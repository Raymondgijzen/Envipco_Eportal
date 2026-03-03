from __future__ import annotations

DOMAIN = "envipco_eportal"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"

# machines stored in entry.options
CONF_MACHINES = "machines"  # list[{"id": "...", "name": "..."}]

# per machine rates stored in entry.options
CONF_MACHINE_RATES = "machine_rates"  # dict[rvm_id] = {"can": float, "pet": float}
DEFAULT_RATE_CAN = 0.0107
DEFAULT_RATE_PET = 0.0331

DEFAULT_SCAN_INTERVAL = 300  # seconds

EP_BASE = "https://ePortal.envipco.com/api"

PLATFORMS = ["sensor"]

# rvmStats keys (examples from docs)
STATUS_STATE_KEY = "StatusInfoState"
STATUS_LAST_REPORT_KEY = "StatusInfoLastReport"

BIN_MATERIAL_PREFIX = "BinInfoMaterialBin"
BIN_FULL_PREFIX = "BinInfoFullBin"
BIN_COUNT_PREFIX = "BinInfoCountBin"

KEY_ACCEPTED_CANS = "cans_accepted"
KEY_ACCEPTED_PET = "pet_accepted"
KEY_ACCEPTED_GLASS = "glass_accepted"

# Reject keys (CSV header)
REJECT_KEYS = [
    "noBarcode",
    "notInDb",
    "bcMove",
    "sortingErr",
    "notAccepted",
    "shape",
    "weight",
    "collision",
    "binFull",
    "notPermitted",
    "wrongMaterial",
    "mode",
]

# Rejects API accept fields when acceptance=yes
ACCEPT_FIELDS_PREFIX = "Accept"
