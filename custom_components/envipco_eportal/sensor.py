from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    BIN_COUNT_PREFIX,
    BIN_FULL_PREFIX,
    BIN_MATERIAL_PREFIX,
    CONF_MACHINES,
    DOMAIN,
    REJECT_KEYS,
    STATUS_LAST_REPORT_FALLBACK_KEYS,
    STATUS_LAST_REPORT_PRIMARY_KEY,
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


def _parse_timestamp(value: Any) -> datetime | None:
    """Zet API timestamp om naar een HA-veilige datetime (UTC)."""
    if value is None:
        return None

    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=dt_util.UTC)
        return dt_util.as_utc(value)

    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None

        dt = dt_util.parse_datetime(s)
        if dt is None:
            return None

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=dt_util.UTC)

        return dt_util.as_utc(dt)

    return None


def _format_local(dt_value: datetime | None) -> str | None:
    """Maak een vaste, menselijke weergave in lokale tijd (Europe/Amsterdam via HA)."""
    if dt_value is None:
        return None
    local = dt_util.as_local(dt_value)
    return local.strftime("%Y-%m-%d %H:%M:%S")


def _get_last_report_raw(rvm: dict[str, Any]) -> Any:
    raw = rvm.get(STATUS_LAST_REPORT_PRIMARY_KEY)
    if raw is None:
        for k in STATUS_LAST_REPORT_FALLBACK_KEYS:
            raw = rvm.get(k)
            if raw is not None:
                break
    return raw


# ---------- Setup ----------
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

    entities: list[SensorEntity] = []

    for m in machines:
        entities.append(StatusSensor(coordinator, entry, m))
        entities.append(LastReportSensor(coordinator, entry, m))
        entities.append(LastReportTextSensor(coordinator, entry, m))

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
        self._attr_name = "Laatste rapport"

    @property
    def native_value(self) -> datetime | None:
        rvm = (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}
        raw = _get_last_report_raw(rvm)
        return _parse_timestamp(raw)


class LastReportTextSensor(Base):
    _attr_icon = "mdi:calendar-clock"
    _attr_translation_key = "last_report_text"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_last_report_text"
        self._attr_name = "Laatste rapport (tekst)"

    @property
    def native_value(self) -> str | None:
        rvm = (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}
        raw = _get_last_report_raw(rvm)
        dt = _parse_timestamp(raw)
        return _format_local(dt)


# ---------- Accepted / Reject / Revenue (placeholders voor jouw bestaande logica) ----------
class AcceptedTotalSensor(Base):
    _attr_icon = "mdi:counter"
    _attr_translation_key = "accepted_total"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_accepted_total"
        self._attr_name = "Accepted totaal"

    @property
    def native_value(self) -> Any:
        rvm = (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}
        return rvm.get("acceptedTotal")


class AcceptedCansSensor(Base):
    _attr_icon = "mdi:beer"
    _attr_translation_key = "accepted_cans"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_accepted_cans"
        self._attr_name = "Accepted blik"

    @property
    def native_value(self) -> Any:
        rvm = (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}
        return rvm.get("acceptedCans")


class AcceptedPetSensor(Base):
    _attr_icon = "mdi:bottle-soda"
    _attr_translation_key = "accepted_pet"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_accepted_pet"
        self._attr_name = "Accepted PET"

    @property
    def native_value(self) -> Any:
        rvm = (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}
        return rvm.get("acceptedPET")


class RejectTotalSensor(Base):
    _attr_icon = "mdi:close-circle-outline"
    _attr_translation_key = "reject_total"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_reject_total"
        self._attr_name = "Reject totaal"

    @property
    def native_value(self) -> Any:
        rvm = (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}
        return rvm.get("rejectTotal")


class RejectRateSensor(Base):
    _attr_icon = "mdi:percent"
    _attr_translation_key = "reject_rate"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_reject_rate"
        self._attr_name = "Reject rate"

    @property
    def native_value(self) -> Any:
        rvm = (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}
        return rvm.get("rejectRate")


class RevenueTodaySensor(Base):
    _attr_icon = "mdi:currency-eur"
    _attr_translation_key = "revenue_today"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_revenue_today"
        self._attr_name = "Opbrengst vandaag"

    @property
    def native_value(self) -> Any:
        rvm = (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}
        return rvm.get("revenueToday")


class RevenueCanTodaySensor(Base):
    _attr_icon = "mdi:currency-eur"
    _attr_translation_key = "revenue_can_today"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_revenue_can_today"
        self._attr_name = "Opbrengst blik vandaag"

    @property
    def native_value(self) -> Any:
        rvm = (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}
        return rvm.get("revenueCanToday")


class RevenuePetTodaySensor(Base):
    _attr_icon = "mdi:currency-eur"
    _attr_translation_key = "revenue_pet_today"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_revenue_pet_today"
        self._attr_name = "Opbrengst PET vandaag"

    @property
    def native_value(self) -> Any:
        rvm = (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}
        return rvm.get("revenuePetToday")


class RejectTypeSensor(Base):
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator, entry, machine, reject_key: str):
        super().__init__(coordinator, entry, machine)
        self.reject_key = reject_key
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_reject_{reject_key}"
        self._attr_name = f"Reject {reject_key}"

    @property
    def native_value(self) -> Any:
        rvm = (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}
        rejects = rvm.get("rejects", {}) or {}
        return rejects.get(self.reject_key)


# ---------- BIN COUNT (hier zit jouw wens) ----------
class BinCountSensor(Base):
    """
    Laat Bin X count zien, maar met entity-naam op basis van materiaal:
    - "Bin 1 CAN"
    - "Bin 2 PET"
    En ZONDER dat Home Assistant de apparaatnaam ervoor zet.
    """
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator, entry, machine: MachineDef, bin_no: int) -> None:
        super().__init__(coordinator, entry, machine)

        self.bin_no = bin_no

        # Dit is de truc: als dit False is, plakt HA niet "Quantum 01" ervoor.
        self._attr_has_entity_name = False

        # Unieke ID voor count
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_bin_{bin_no}_count"

        # Zet alvast een basisnaam; we updaten 'm dynamisch in native_value/extra attrs.
        self._attr_name = f"Bin {bin_no}"

    @property
    def _bin_key_count(self) -> str:
        return f"{BIN_COUNT_PREFIX}{self.bin_no}"

    @property
    def _bin_key_material(self) -> str:
        return f"{BIN_MATERIAL_PREFIX}{self.bin_no}"

    @property
    def _bin_key_full(self) -> str:
        return f"{BIN_FULL_PREFIX}{self.bin_no}"

    def _get_rvm(self) -> dict[str, Any]:
        return (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}

    @property
    def native_value(self) -> Any:
        rvm = self._get_rvm()
        count = rvm.get(self._bin_key_count)

        material_raw = rvm.get(self._bin_key_material)
        material = _norm_material(material_raw) or "UNKNOWN"

        # Naam dynamisch op materiaal (zonder device prefix)
        self._attr_name = f"Bin {self.bin_no} {material}"

        return count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rvm = self._get_rvm()

        material_raw = rvm.get(self._bin_key_material)
        material = _norm_material(material_raw)

        full = rvm.get(self._bin_key_full)

        attrs: dict[str, Any] = {
            "materiaal": material,
            "bin_full": full,
        }
        return attrs
