from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    BIN_COUNT_PREFIX,
    BIN_FULL_PREFIX,
    BIN_MATERIAL_PREFIX,
    CONF_MACHINES,
    DOMAIN,
    REJECT_KEYS,
    STATUS_LAST_REPORT_KEY,
    STATUS_STATE_KEY,
)
from .coordinator import EnvipcoCoordinator


@dataclass
class MachineDef:
    name: str
    id: str


# ---------- Helpers ----------

MATERIAL_MAP: dict[str, str] = {
    "ALU": "CAN",
    "CAN": "CAN",
    "CANS": "CAN",
    "PET": "PET",
    "GLASS": "GLASS",
    "GLS": "GLASS",
}


def _norm_material(raw: str | None) -> str | None:
    if not raw:
        return None
    key = raw.strip().upper()
    if not key:
        return None
    return MATERIAL_MAP.get(key, key)


# ---------- Setup ----------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: EnvipcoCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    machines_cfg = entry.options.get(CONF_MACHINES, entry.data.get(CONF_MACHINES, [])) or []
    machines = [MachineDef(name=m.get("name") or m.get("id"), id=m.get("id")) for m in machines_cfg if m.get("id")]

    entities: list[SensorEntity] = []

    for m in machines:
        entities.append(StatusSensor(coordinator, entry, m))
        entities.append(LastReportSensor(coordinator, entry, m))

        entities.append(AcceptedTotalSensor(coordinator, entry, m))
        entities.append(AcceptedCansSensor(coordinator, entry, m))
        entities.append(AcceptedPetSensor(coordinator, entry, m))

        entities.append(RejectTotalSensor(coordinator, entry, m))
        entities.append(RejectRateSensor(coordinator, entry, m))

        entities.append(RevenueTodaySensor(coordinator, entry, m))
        entities.append(RevenueCanTodaySensor(coordinator, entry, m))
        entities.append(RevenuePetTodaySensor(coordinator, entry, m))

        for key in REJECT_KEYS:
            entities.append(RejectTypeSensor(coordinator, entry, m, key))

        # ePortal levert vaak 12 bins; ongebruikte bins hebben geen BinInfoMaterialBinX.
        for bin_no in range(1, 13):
            entities.append(BinCountSensor(coordinator, entry, m, bin_no))

    async_add_entities(entities)


# ---------- Base ----------

class Base(CoordinatorEntity[EnvipcoCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: EnvipcoCoordinator, entry: ConfigEntry, machine: MachineDef) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.machine = machine

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.machine.id)},
            "name": self.machine.name,
            "manufacturer": "Envipco",
            "model": "RVM",
        }


# ---------- Status ----------

class StatusSensor(Base):
    _attr_icon = "mdi:robot"
    _attr_translation_key = "status"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_status"
        self._attr_name = "Status"

    @property
    def native_value(self) -> Any:
        rvm = (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}
        return rvm.get(STATUS_STATE_KEY)


class LastReportSensor(Base):
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_report"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_last_report"
        self._attr_name = "Last report"

    @property
    def native_value(self) -> Any:
        rvm = (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}
        return rvm.get(STATUS_LAST_REPORT_KEY)


# ---------- Accepted ----------

class AcceptedTotalSensor(Base):
    _attr_icon = "mdi:check-circle-outline"
    _attr_native_unit_of_measurement = "stuks"
    _attr_translation_key = "accepted_total"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_accepted_total"
        self._attr_name = "Accepted total"

    @property
    def native_value(self) -> Any:
        t = (self.coordinator.data.get("totals", {}) or {}).get(self.machine.id, {}) or {}
        return t.get("accepted_total")


class AcceptedCansSensor(Base):
    _attr_icon = "mdi:soda-can"
    _attr_native_unit_of_measurement = "stuks"
    _attr_translation_key = "accepted_cans"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_accepted_cans"
        self._attr_name = "Accepted cans"

    @property
    def native_value(self) -> Any:
        t = (self.coordinator.data.get("totals", {}) or {}).get(self.machine.id, {}) or {}
        return t.get("accepted_cans")


class AcceptedPetSensor(Base):
    _attr_icon = "mdi:bottle-soda"
    _attr_native_unit_of_measurement = "stuks"
    _attr_translation_key = "accepted_pet"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_accepted_pet"
        self._attr_name = "Accepted PET"

    @property
    def native_value(self) -> Any:
        t = (self.coordinator.data.get("totals", {}) or {}).get(self.machine.id, {}) or {}
        return t.get("accepted_pet")


# ---------- Rejects ----------

class RejectTotalSensor(Base):
    _attr_icon = "mdi:close-octagon-outline"
    _attr_native_unit_of_measurement = "stuks"
    _attr_translation_key = "reject_total"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_reject_total"
        self._attr_name = "Rejected total"

    @property
    def native_value(self) -> Any:
        t = (self.coordinator.data.get("totals", {}) or {}).get(self.machine.id, {}) or {}
        return t.get("rejects_total")


class RejectRateSensor(Base):
    _attr_icon = "mdi:percent"
    _attr_native_unit_of_measurement = "%"
    _attr_translation_key = "reject_rate"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_reject_rate"
        self._attr_name = "Reject rate"

    @property
    def native_value(self) -> Any:
        t = (self.coordinator.data.get("totals", {}) or {}).get(self.machine.id, {}) or {}
        val = t.get("reject_rate")
        return None if val is None else round(float(val), 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        t = (self.coordinator.data.get("totals", {}) or {}).get(self.machine.id, {}) or {}
        return {
            "formule": "rejects / (accepted + rejects) * 100",
            "accepted_total": t.get("accepted_total"),
            "rejects_total": t.get("rejects_total"),
            "datum": self.coordinator.data.get("date"),
        }


class RejectTypeSensor(Base):
    _attr_icon = "mdi:close-octagon-outline"
    _attr_native_unit_of_measurement = "stuks"

    def __init__(self, coordinator, entry, machine, key: str):
        super().__init__(coordinator, entry, machine)
        self.key = key
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_reject_{key}"
        self._attr_translation_key = f"reject_{key}"
        self._attr_name = f"Reject - {key}"

    @property
    def native_value(self) -> Any:
        rejects = self.coordinator.data.get("rejects", {}) or {}
        return (rejects.get(self.machine.id, {}) or {}).get(self.key)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"datum": self.coordinator.data.get("date")}


# ---------- Revenue ----------

class RevenueTodaySensor(Base):
    _attr_icon = "mdi:currency-eur"
    _attr_native_unit_of_measurement = "EUR"
    _attr_translation_key = "revenue_today"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_revenue_today"
        self._attr_name = "Revenue today"

    @property
    def native_value(self) -> Any:
        t = (self.coordinator.data.get("totals", {}) or {}).get(self.machine.id, {}) or {}
        val = t.get("revenue_today")
        return None if val is None else round(float(val), 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        t = (self.coordinator.data.get("totals", {}) or {}).get(self.machine.id, {}) or {}
        return {
            "tarief_can": t.get("rate_can"),
            "tarief_pet": t.get("rate_pet"),
            "accepted_cans": t.get("accepted_cans"),
            "accepted_pet": t.get("accepted_pet"),
            "datum": self.coordinator.data.get("date"),
        }


class RevenueCanTodaySensor(Base):
    _attr_icon = "mdi:currency-eur"
    _attr_native_unit_of_measurement = "EUR"
    _attr_translation_key = "revenue_can_today"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_revenue_can_today"
        self._attr_name = "Revenue cans today"

    @property
    def native_value(self) -> Any:
        t = (self.coordinator.data.get("totals", {}) or {}).get(self.machine.id, {}) or {}
        val = t.get("revenue_can_today")
        return None if val is None else round(float(val), 2)


class RevenuePetTodaySensor(Base):
    _attr_icon = "mdi:currency-eur"
    _attr_native_unit_of_measurement = "EUR"
    _attr_translation_key = "revenue_pet_today"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_revenue_pet_today"
        self._attr_name = "Revenue PET today"

    @property
    def native_value(self) -> Any:
        t = (self.coordinator.data.get("totals", {}) or {}).get(self.machine.id, {}) or {}
        val = t.get("revenue_pet_today")
        return None if val is None else round(float(val), 2)


# ---------- Bins ----------

class BinCountSensor(Base):
    # Entity_id/unique_id blijft hetzelfde als eerdere versies: ..._binX_full (ivm historie).
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "stuks"
    _attr_translation_key = "bin_count"

    def __init__(self, coordinator, entry, machine, bin_no: int):
        super().__init__(coordinator, entry, machine)
        self.bin_no = bin_no
        self._material: str | None = None
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_bin{bin_no}_full"
        # Dynamisch: HA vertalingen ondersteunen geen placeholders, dus dit deel blijft in code.
        self._attr_name = f"Bak {bin_no} aantal"

        # Ongebruikte bins hebben geen materiaal -> standaard verbergen
        rvm = (coordinator.data.get("stats", {}) or {}).get(machine.id, {}) or {}
        mat_raw = (rvm.get(f"{BIN_MATERIAL_PREFIX}{bin_no}") or "").strip()
        if not mat_raw:
            self._attr_entity_registry_enabled_default = False
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    def _get_material(self) -> str | None:
        rvm = (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}
        return _norm_material(rvm.get(f"{BIN_MATERIAL_PREFIX}{self.bin_no}"))

    @property
    def native_value(self) -> Any:
        rvm = (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}
        mat_raw = (rvm.get(f"{BIN_MATERIAL_PREFIX}{self.bin_no}") or "").strip()
        if not mat_raw:
            return None

        raw_count = rvm.get(f"{BIN_COUNT_PREFIX}{self.bin_no}")
        raw_full = rvm.get(f"{BIN_FULL_PREFIX}{self.bin_no}")
        raw_val = raw_count if raw_count not in (None, "") else raw_full

        try:
            val_i = int(float(raw_val))
        except Exception:
            val_i = None

        if val_i is None or val_i < 0:
            return None
        return val_i

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rvm = (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}
        return {
            "materiaal": self._get_material(),
            "reset": "waarde kan lager worden na legen",
            "raw_count": rvm.get(f"{BIN_COUNT_PREFIX}{self.bin_no}"),
            "raw_full": rvm.get(f"{BIN_FULL_PREFIX}{self.bin_no}"),
        }

    def _handle_coordinator_update(self) -> None:
        mat = self._get_material()
        if mat and mat != self._material:
            self._material = mat
            self._attr_name = f"Bak {self.bin_no} {mat} aantal"
        super()._handle_coordinator_update()
