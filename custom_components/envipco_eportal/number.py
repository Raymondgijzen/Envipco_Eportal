from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import (
    BIN_COUNT_PREFIX,
    BIN_FULL_PREFIX,
    BIN_LIMIT_PREFIX,
    BIN_MATERIAL_PREFIX,
    CONF_MACHINE_BIN_LIMITS,
    CONF_MACHINES,
    DEFAULT_BIN_LIMIT_CAN,
    DEFAULT_BIN_LIMIT_GLASS,
    DEFAULT_BIN_LIMIT_PET,
    DEFAULT_BIN_LIMIT_UNKNOWN,
    DOMAIN,
    MAX_BINS,
)
from .coordinator import EnvipcoCoordinator


@dataclass
class MachineDef:
    name: str
    id: str


MATERIAL_MAP: dict[str, str] = {
    "ALU": "CAN",
    "CAN": "CAN",
    "CANS": "CAN",
    "PET": "PET",
    "GLASS": "GLASS",
    "GLS": "GLASS",
}

BIN_CAPACITY_BY_MATERIAL: dict[str, int] = {
    "CAN": DEFAULT_BIN_LIMIT_CAN,
    "PET": DEFAULT_BIN_LIMIT_PET,
    "GLASS": DEFAULT_BIN_LIMIT_GLASS,
}


def _norm_material(raw: str | None) -> str | None:
    if not raw:
        return None
    key = raw.strip().upper()
    if not key:
        return None
    return MATERIAL_MAP.get(key, key)


def _bin_has_data(rvm: dict[str, Any], bin_no: int) -> bool:
    """Bepaal of een bin echt in gebruik is.

    We behandelen een bin alleen als actief wanneer er duidelijke aanwijzingen zijn
    dat die bin gebruikt wordt. Een kale limit-waarde of een bool False bij
    BinInfoFullBinX telt dus niet mee, omdat de API zulke waarden ook kan
    teruggeven voor bins die fysiek niet in gebruik zijn.
    """
    material = _norm_material(rvm.get(f"{BIN_MATERIAL_PREFIX}{bin_no}"))
    if material:
        return True

    count = rvm.get(f"{BIN_COUNT_PREFIX}{bin_no}")
    full = rvm.get(f"{BIN_FULL_PREFIX}{bin_no}")

    if count not in (None, "", 0, "0", 0.0, "0.0"):
        return True

    if full is True:
        return True

    if isinstance(full, str) and full.strip().lower() not in ("", "0", "false", "no"):
        return True

    if isinstance(full, (int, float)) and full not in (0, 0.0):
        return True

    return False


def _capacity_for_material(material: str | None) -> int | None:
    if not material:
        return None
    return BIN_CAPACITY_BY_MATERIAL.get(material)


def _machine_display_name(machine: MachineDef, rvm: dict[str, Any]) -> str:
    configured = (machine.name or "").strip()
    if configured and configured != machine.id:
        return configured

    account = str(rvm.get("SiteInfoAccount") or "").strip()
    if account:
        return account

    location = str(rvm.get("SiteInfoLocationID") or "").strip()
    if location:
        return location

    return machine.id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EnvipcoCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    machines_cfg = entry.options.get(CONF_MACHINES, entry.data.get(CONF_MACHINES, [])) or []
    machines = [
        MachineDef(name=m.get("name") or m.get("id"), id=m.get("id"))
        for m in machines_cfg
        if m.get("id")
    ]

    entities: list[NumberEntity] = []
    for machine in machines:
        for bin_no in range(1, MAX_BINS + 1):
            entities.append(BinLimitConfigNumber(coordinator, entry, machine, bin_no))

    async_add_entities(entities)


class BaseNumber(CoordinatorEntity[EnvipcoCoordinator], NumberEntity):
    _attr_has_entity_name = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = "box"
    _attr_native_min_value = 0
    _attr_native_max_value = 100000
    _attr_native_step = 1

    def __init__(self, coordinator: EnvipcoCoordinator, entry: ConfigEntry, machine: MachineDef) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.machine = machine

    @property
    def _display_name(self) -> str:
        return _machine_display_name(self.machine, self._get_rvm())

    @property
    def device_info(self):
        rvm = self._get_rvm()
        return {
            "identifiers": {(DOMAIN, self.machine.id)},
            "name": self._display_name,
            "manufacturer": "Envipco",
            "model": "RVM",
            "serial_number": self.machine.id,
            "sw_version": str(rvm.get("VersionREL") or "").strip() or None,
            "hw_version": str(rvm.get("VersionMCX") or "").strip() or None,
            "configuration_url": None,
            "suggested_area": self._display_name,
        }

    def _set_object_id(self, suffix: str) -> None:
        self._attr_suggested_object_id = slugify(f"{self._display_name}_{suffix}")

    def _get_rvm(self) -> dict[str, Any]:
        return (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}


class BinLimitConfigNumber(BaseNumber):
    _attr_icon = "mdi:tune-vertical"

    def __init__(self, coordinator: EnvipcoCoordinator, entry: ConfigEntry, machine: MachineDef, bin_no: int) -> None:
        super().__init__(coordinator, entry, machine)
        self.bin_no = bin_no
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_bin_{bin_no}_limit_config"
        self._attr_name = f"Bin {bin_no} limiet"
        self._set_object_id(f"bin_{bin_no}_limiet_config")
        self._attr_entity_registry_enabled_default = _bin_has_data(self._get_rvm(), self.bin_no)

    def _material(self) -> str | None:
        return _norm_material(self._get_rvm().get(f"{BIN_MATERIAL_PREFIX}{self.bin_no}"))

    def _api_limit(self) -> int | None:
        value = self._get_rvm().get(f"{BIN_LIMIT_PREFIX}{self.bin_no}")
        if value in (None, ""):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _default_limit(self) -> int:
        api_limit = self._api_limit()
        if api_limit not in (None, 0):
            return api_limit

        material = self._material()
        by_material = _capacity_for_material(material)
        if by_material not in (None, 0):
            return by_material

        return DEFAULT_BIN_LIMIT_UNKNOWN

    def _configured_limit(self) -> int:
        all_limits = self.entry.options.get(
            CONF_MACHINE_BIN_LIMITS,
            self.entry.data.get(CONF_MACHINE_BIN_LIMITS, {}),
        ) or {}
        machine_limits = all_limits.get(self.machine.id, {}) or {}
        value = machine_limits.get(str(self.bin_no))
        if value in (None, ""):
            return self._default_limit()
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return self._default_limit()

    @property
    def native_value(self) -> float:
        return float(self._configured_limit())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "materiaal": self._material(),
            "bin_limit_api": self._api_limit(),
            "bin_limit_actief": self._configured_limit(),
            "bin_in_gebruik": _bin_has_data(self._get_rvm(), self.bin_no),
        }

    async def async_set_native_value(self, value: float) -> None:
        all_limits = dict(
            self.entry.options.get(
                CONF_MACHINE_BIN_LIMITS,
                self.entry.data.get(CONF_MACHINE_BIN_LIMITS, {}),
            )
            or {}
        )
        machine_limits = dict(all_limits.get(self.machine.id, {}) or {})
        machine_limits[str(self.bin_no)] = int(value)
        all_limits[self.machine.id] = machine_limits

        new_options = dict(self.entry.options)
        new_options[CONF_MACHINE_BIN_LIMITS] = all_limits
        self.hass.config_entries.async_update_entry(self.entry, options=new_options)

        await self.coordinator.async_request_refresh()
        self.async_write_ha_state()
