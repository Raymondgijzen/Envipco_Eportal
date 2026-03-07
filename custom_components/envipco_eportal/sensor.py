from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.helpers.entity import EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import (
    BIN_COUNT_PREFIX,
    BIN_LIMIT_PREFIX,
    BIN_FULL_PREFIX,
    BIN_MATERIAL_PREFIX,
    CONF_MACHINE_BIN_LIMITS,
    CONF_MACHINES,
    DEFAULT_BIN_LIMIT_CAN,
    DEFAULT_BIN_LIMIT_GLASS,
    DEFAULT_BIN_LIMIT_PET,
    DEFAULT_BIN_LIMIT_UNKNOWN,
    DOMAIN,
    MAX_BINS,
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


def _location_label(rvm: dict[str, Any]) -> str | None:
    address = str(rvm.get("SiteInfoAddress") or "").strip()
    city = str(rvm.get("SiteInfoCity") or "").strip()
    postal = str(rvm.get("SiteInfoPostalCode") or "").strip()

    parts: list[str] = []
    if address:
        parts.append(address)

    city_line = " ".join(p for p in [postal, city] if p).strip()
    if city_line:
        parts.append(city_line)

    return ", ".join(parts) if parts else None


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
        entities.append(LocationInfoSensor(coordinator, entry, machine))

        for key in REJECT_KEYS:
            entities.append(RejectTypeSensor(coordinator, entry, machine, key))

        for bin_no in range(1, MAX_BINS + 1):
            entities.append(BinCountSensor(coordinator, entry, machine, bin_no))
            entities.append(BinLimitSensor(coordinator, entry, machine, bin_no))
            entities.append(BinPercentageSensor(coordinator, entry, machine, bin_no))

    async_add_entities(entities)


class Base(CoordinatorEntity[EnvipcoCoordinator], SensorEntity):
    _attr_has_entity_name = False

    def __init__(self, coordinator: EnvipcoCoordinator, entry: ConfigEntry, machine: MachineDef) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self.machine = machine

    @property
    def _display_name(self) -> str:
        return _machine_display_name(self.machine, self._get_rvm())

    @property
    def _machine_slug(self) -> str:
        return slugify(self._display_name)

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

    def _build_name(self, suffix: str) -> str:
        return suffix

    def _set_object_id(self, suffix: str) -> None:
        self._attr_suggested_object_id = slugify(f"{self._display_name}_{suffix}")

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
        return (self.coordinator.data.get("totals", {}) or {}).get(self.machine.id, {}).get("accepted_total")


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
        return (self.coordinator.data.get("totals", {}) or {}).get(self.machine.id, {}).get("accepted_cans")


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
        return (self.coordinator.data.get("totals", {}) or {}).get(self.machine.id, {}).get("accepted_pet")


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
        return (self.coordinator.data.get("totals", {}) or {}).get(self.machine.id, {}).get("rejects_total")


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
        return (self.coordinator.data.get("totals", {}) or {}).get(self.machine.id, {}).get("reject_rate")


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
        return (self.coordinator.data.get("totals", {}) or {}).get(self.machine.id, {}).get("revenue_today")


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
        return (self.coordinator.data.get("totals", {}) or {}).get(self.machine.id, {}).get("revenue_can_today")


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
        return (self.coordinator.data.get("totals", {}) or {}).get(self.machine.id, {}).get("revenue_pet_today")


class LocationInfoSensor(Base):
    _attr_icon = "mdi:map-marker"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, machine):
        super().__init__(coordinator, entry, machine)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_location_info"
        self._attr_name = "Locatie info"
        self._set_object_id("locatie_info")

    @property
    def native_value(self) -> str | None:
        return _location_label(self._get_rvm())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rvm = self._get_rvm()
        return {
            "machine_naam": self._display_name,
            "machine_id": self.machine.id,
            "site_account": rvm.get("SiteInfoAccount"),
            "site_location_id": rvm.get("SiteInfoLocationID"),
            "adres": rvm.get("SiteInfoAddress"),
            "postcode": rvm.get("SiteInfoPostalCode"),
            "plaats": rvm.get("SiteInfoCity"),
            "land": rvm.get("SiteInfoCountry"),
        }


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
        rejects = (self.coordinator.data.get("rejects", {}) or {}).get(self.machine.id, {}) or {}
        return rejects.get(self.reject_key)


class BinBaseSensor(Base):
    def __init__(self, coordinator, entry, machine: MachineDef, bin_no: int) -> None:
        super().__init__(coordinator, entry, machine)
        self.bin_no = bin_no
        self._attr_entity_registry_enabled_default = _bin_has_data(self._get_rvm(), self.bin_no)

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
    def _bin_key_limit(self) -> str:
        return f"{BIN_LIMIT_PREFIX}{self.bin_no}"

    def _material(self) -> str | None:
        return _norm_material(self._get_rvm().get(self._bin_key_material))

    def _count(self) -> int | float | None:
        value = self._get_rvm().get(self._bin_key_count)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

    def _full(self) -> Any:
        return self._get_rvm().get(self._bin_key_full)

    def _api_limit(self) -> int | float | None:
        value = self._get_rvm().get(self._bin_key_limit)
        if value in (None, ""):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

    def _configured_limit(self) -> int | None:
        all_limits = self.entry.options.get(
            CONF_MACHINE_BIN_LIMITS,
            self.entry.data.get(CONF_MACHINE_BIN_LIMITS, {}),
        ) or {}
        machine_limits = all_limits.get(self.machine.id, {}) or {}
        value = machine_limits.get(str(self.bin_no))
        if value in (None, ""):
            return None
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return None

    def _effective_limit(self) -> int | float | None:
        configured = self._configured_limit()
        if configured not in (None, 0):
            return configured

        api_limit = self._api_limit()
        if api_limit not in (None, 0):
            return api_limit

        material = self._material()
        if material:
            return _capacity_for_material(material)

        return DEFAULT_BIN_LIMIT_UNKNOWN

    def _bin_label(self) -> str:
        material = self._material()
        if material:
            return f"Bin {self.bin_no} {material}"
        return f"Bin {self.bin_no}"

    @property
    def available(self) -> bool:
        return _bin_has_data(self._get_rvm(), self.bin_no)


class BinCountSensor(BinBaseSensor):
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator, entry, machine: MachineDef, bin_no: int) -> None:
        super().__init__(coordinator, entry, machine, bin_no)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_bin_{bin_no}_count"
        self._attr_name = self._build_name(f"Bin {bin_no}")
        self._set_object_id(f"bin_{bin_no}_count")

    @property
    def native_value(self) -> Any:
        self._attr_name = self._build_name(self._bin_label())
        return self._count()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        material = self._material()
        return {
            "materiaal": material,
            "bin_full": self._full(),
            "bin_limit_api": self._api_limit(),
            "bin_limit_config": self._configured_limit(),
            "bin_limit_actief": self._effective_limit(),
        }


class BinLimitSensor(BinBaseSensor):
    _attr_icon = "mdi:tune-vertical"

    def __init__(self, coordinator, entry, machine: MachineDef, bin_no: int) -> None:
        super().__init__(coordinator, entry, machine, bin_no)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_bin_{bin_no}_limit"
        self._attr_name = self._build_name(f"Bin {bin_no} limiet")
        self._set_object_id(f"bin_{bin_no}_limit")

    @property
    def native_value(self) -> Any:
        self._attr_name = self._build_name(f"{self._bin_label()} limiet")
        return self._effective_limit()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "materiaal": self._material(),
            "bin_full": self._full(),
            "aantal": self._count(),
            "bin_limit_api": self._api_limit(),
            "bin_limit_config": self._configured_limit(),
            "uitleg": "Actieve waarde gebruikt eerst de ingestelde limiet uit opties, daarna de API-waarde.",
        }


class BinPercentageSensor(BinBaseSensor):
    _attr_icon = "mdi:percent"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator, entry, machine: MachineDef, bin_no: int) -> None:
        super().__init__(coordinator, entry, machine, bin_no)
        self._attr_unique_id = f"{entry.entry_id}_{machine.id}_bin_{bin_no}_percentage"
        self._attr_name = self._build_name(f"Bin {bin_no} percentage")
        self._set_object_id(f"bin_{bin_no}_percentage")

    @property
    def native_value(self) -> float | None:
        count = self._count()
        capacity = self._effective_limit()

        self._attr_name = self._build_name(f"{self._bin_label()} percentage")

        if count is None or capacity in (None, 0):
            return None

        percentage = (float(count) / float(capacity)) * 100.0
        return round(min(100.0, max(0.0, percentage)), 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "materiaal": self._material(),
            "aantal": self._count(),
            "bin_limit_api": self._api_limit(),
            "bin_limit_config": self._configured_limit(),
            "bin_limit_actief": self._effective_limit(),
            "uitleg": "Percentage is berekend op basis van count / actieve limiet.",
        }
