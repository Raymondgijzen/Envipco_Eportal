from __future__ import annotations

DOMAIN = "envipco_eportal"

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_SCAN_INTERVAL = "scan_interval"

# machines stored in entry.options
CONF_MACHINES = "machines"  # list[{"id": "...", "name": "..."}]

# per machine rates stored in entry.options
CONF_MACHINE_RATES = "machine_rates"  # dict[rvm_id] = {"can": float, "pet": float}

# per machine configured bin limits stored in entry.options
# dict[rvm_id] = {"1": int, "2": int, ...}
CONF_MACHINE_BIN_LIMITS = "machine_bin_limits"

DEFAULT_RATE_CAN = 0.0107
DEFAULT_RATE_PET = 0.0331

DEFAULT_SCAN_INTERVAL = 300  # seconds
DEFAULT_BIN_LIMIT_CAN = 1200
DEFAULT_BIN_LIMIT_PET = 600
DEFAULT_BIN_LIMIT_GLASS = 400
DEFAULT_BIN_LIMIT_UNKNOWN = 1000
MAX_BINS = 12

EP_BASE = "https://ePortal.envipco.com/api"

PLATFORMS = ["sensor", "number"]

# rvmStats keys (examples from docs / praktijk)
STATUS_STATE_KEY = "StatusInfoState"

# Jij wil deze zien in HA:
STATUS_LAST_REPORT_PRIMARY_KEY = "RVMStatusLastTime"

# Fallback voor oudere/andere responses:
STATUS_LAST_REPORT_FALLBACK_KEYS: list[str] = [
    "StatusInfoLastReport",
]

# Bin info keys/prefixes
BIN_MATERIAL_PREFIX = "BinInfoMaterialBin"
BIN_FULL_PREFIX = "BinInfoFullBin"
BIN_COUNT_PREFIX = "BinInfoCountBin"
BIN_LIMIT_PREFIX = "BinInfoLimitBin"

# Accepted keys
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
