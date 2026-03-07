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
from homeassistant.util import slugify

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
    """Maak een vaste, menselijke weergave in lokale tijd."""
    if dt_value is None:
        return None
    local = dt_util.as_local(dt_value)
    return local.strftime("%Y-%m-%d %H:%M:%S")


def _get_last_report_raw(rvm: dict[str, Any]) -> Any:
    raw = rvm.get(STATUS_LAST_REPORT_PRIMARY_KEY)
    if raw is None:
        for key in STATUS_LAST_REPORT_FALLBACK_KEYS:
            raw = rvm.get(key)
            if raw is not None:
                break
    return raw


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

    for machine in machines:
        entities.append(StatusSensor(coordinator, entry, machine))
        entities.append(LastReportSensor(coordinator, entry, machine))
        entities.append(LastReportTextSensor(coordinator, entry, machine))
        entities.append(AcceptedTotalSensor(coordinator, entry, machine))
        entities.append(AcceptedCansSensor(coordinator, entry, machine))
        entities.append(AcceptedPetSensor(coordinator, entry, machine))
        entities.append(RejectTotalSensor(coordinator, entry, machine))
        entities.append(RejectRateSensor(coordinator, entry, machine))
        entities.append(RevenueTodaySensor(coordinator, entry, machine))
        entities.append(RevenueCanTodaySensor(coordinator, entry, machine))
        entities.append(RevenuePetTodaySensor(coordinator, entry, machine))

        for key in REJECT_KEYS:
            entities.append(RejectTypeSensor(coordinator, entry, machine, key))

        for bin_no in range(1, 13):
            entities.append(BinCountSensor(coordinator, entry, machine, bin_no))

    async_add_entities(entities)


class Base(CoordinatorEntity[EnvipcoCoordinator], SensorEntity):
    _attr_has_entity_name = False

    def __init__(self, coordinator: EnvipcoCoordinator, entry: ConfigEntry, machine: MachineDef) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.machine = machine
        self._machine_slug = slugify(machine.name or machine.id)

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self.machine.id)},
            "name": self.machine.name,
            "manufacturer": "Envipco",
            "model": "RVM",
        }

    def _build_name(self, suffix: str) -> str:
        return f"{self.machine.name} {suffix}"

    def _set_object_id(self, suffix: str) -> None:
        self._attr_suggested_object_id = slugify(f"{self.machine.name}_{suffix}")

    def _get_rvm(self) -> dict[str, Any]:
        return (self.coordinator.data.get("stats", {}) or {}).get(self.machine.id, {}) or {}


class StatusSensor(Base):
    _attr_icon = "mdi:robot"
    _attr_translation_key = "status"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_status"
        self._attr_name = self._build_name("Status")
        self._set_object_id("status")

    @property
    def native_value(self) -> Any:
        return self._get_rvm().get(STATUS_STATE_KEY)


class LastReportSensor(Base):
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_report"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_last_report"
        self._attr_name = self._build_name("Laatste rapport")
        self._set_object_id("laatste_rapport")

    @property
    def native_value(self) -> datetime | None:
        raw = _get_last_report_raw(self._get_rvm())
        return _parse_timestamp(raw)


class LastReportTextSensor(Base):
    _attr_icon = "mdi:calendar-clock"
    _attr_translation_key = "last_report_text"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_last_report_text"
        self._attr_name = self._build_name("Laatste rapport tekst")
        self._set_object_id("laatste_rapport_tekst")

    @property
    def native_value(self) -> str | None:
        raw = _get_last_report_raw(self._get_rvm())
        dt = _parse_timestamp(raw)
        return _format_local(dt)


class AcceptedTotalSensor(Base):
    _attr_icon = "mdi:counter"
    _attr_translation_key = "accepted_total"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_accepted_total"
        self._attr_name = self._build_name("Accepted totaal")
        self._set_object_id("accepted_totaal")

    @property
    def native_value(self) -> Any:
        return self._get_rvm().get("acceptedTotal")


class AcceptedCansSensor(Base):
    _attr_icon = "mdi:beer"
    _attr_translation_key = "accepted_cans"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_accepted_cans"
        self._attr_name = self._build_name("Accepted blik")
        self._set_object_id("accepted_blik")

    @property
    def native_value(self) -> Any:
        return self._get_rvm().get("acceptedCans")


class AcceptedPetSensor(Base):
    _attr_icon = "mdi:bottle-soda"
    _attr_translation_key = "accepted_pet"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_accepted_pet"
        self._attr_name = self._build_name("Accepted PET")
        self._set_object_id("accepted_pet")

    @property
    def native_value(self) -> Any:
        return self._get_rvm().get("acceptedPET")


class RejectTotalSensor(Base):
    _attr_icon = "mdi:close-circle-outline"
    _attr_translation_key = "reject_total"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_reject_total"
        self._attr_name = self._build_name("Reject totaal")
        self._set_object_id("reject_totaal")

    @property
    def native_value(self) -> Any:
        return self._get_rvm().get("rejectTotal")


class RejectRateSensor(Base):
    _attr_icon = "mdi:percent"
    _attr_translation_key = "reject_rate"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_reject_rate"
        self._attr_name = self._build_name("Reject rate")
        self._set_object_id("reject_rate")

    @property
    def native_value(self) -> Any:
        return self._get_rvm().get("rejectRate")


class RevenueTodaySensor(Base):
    _attr_icon = "mdi:currency-eur"
    _attr_translation_key = "revenue_today"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_revenue_today"
        self._attr_name = self._build_name("Opbrengst vandaag")
        self._set_object_id("opbrengst_vandaag")

    @property
    def native_value(self) -> Any:
        return self._get_rvm().get("revenueToday")


class RevenueCanTodaySensor(Base):
    _attr_icon = "mdi:currency-eur"
    _attr_translation_key = "revenue_can_today"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_revenue_can_today"
        self._attr_name = self._build_name("Opbrengst blik vandaag")
        self._set_object_id("opbrengst_blik_vandaag")

    @property
    def native_value(self) -> Any:
        return self._get_rvm().get("revenueCanToday")


class RevenuePetTodaySensor(Base):
    _attr_icon = "mdi:currency-eur"
    _attr_translation_key = "revenue_pet_today"

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_revenue_pet_today"
        self._attr_name = self._build_name("Opbrengst PET vandaag")
        self._set_object_id("opbrengst_pet_vandaag")

    @property
    def native_value(self) -> Any:
        return self._get_rvm().get("revenuePetToday")


class RejectTypeSensor(Base):
    _attr_icon = "mdi:alert-circle-outline"

    def __init__(self, coordinator, entry, machine, reject_key: str):
        super().__init__(coordinator, entry, machine)
        self.reject_key = reject_key
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_reject_{reject_key}"
        self._attr_name = self._build_name(f"Reject {reject_key}")
        self._set_object_id(f"reject_{reject_key}")

    @property
    def native_value(self) -> Any:
        rejects = self._get_rvm().get("rejects", {}) or {}
        return rejects.get(self.reject_key)


class BinCountSensor(Base):
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator, entry, machine: MachineDef, bin_no: int) -> None:
        super().__init__(coordinator, entry, machine)
        self.bin_no = bin_no
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_bin_{bin_no}_count"
        self._attr_name = self._build_name(f"Bin {bin_no}")
        self._set_object_id(f"bin_{bin_no}_count")

    @property
    def _bin_key_count(self) -> str:
        return f"{BIN_COUNT_PREFIX}{self.bin_no}"

    @property
    def _bin_key_material(self) -> str:
        return f"{BIN_MATERIAL_PREFIX}{self.bin_no}"

    @property
    def _bin_key_full(self) -> str:
        return f"{BIN_FULL_PREFIX}{self.bin_no}"

    @property
    def native_value(self) -> Any:
        rvm = self._get_rvm()
        count = rvm.get(self._bin_key_count)
        material_raw = rvm.get(self._bin_key_material)
        material = _norm_material(material_raw)

        if material:
            self._attr_name = self._build_name(f"Bin {self.bin_no} {material}")
        else:
            self._attr_name = self._build_name(f"Bin {self.bin_no}")

        return count

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rvm = self._get_rvm()
        material_raw = rvm.get(self._bin_key_material)
        material = _norm_material(material_raw)
        full = rvm.get(self._bin_key_full)
        return {
            "materiaal": material,
            "bin_full": full,
        }
