from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EnvipcoEPortalApiClient
from .const import (
    BIN_LIMIT_PREFIX,
    BIN_MATERIAL_PREFIX,
    CONF_MACHINE_BIN_LIMITS,
    CONF_MACHINE_RATES,
    CONF_MACHINES,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_BIN_LIMIT_CAN,
    DEFAULT_BIN_LIMIT_GLASS,
    DEFAULT_BIN_LIMIT_PET,
    DEFAULT_BIN_LIMIT_UNKNOWN,
    DEFAULT_RATE_CAN,
    DEFAULT_RATE_PET,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_BINS,
)


def _norm_material(raw: str | None) -> str | None:
    if not raw:
        return None
    value = str(raw).strip().upper()
    if value in ("ALU", "CAN", "CANS"):
        return "CAN"
    if value == "PET":
        return "PET"
    if value in ("GLASS", "GLS"):
        return "GLASS"
    return value or None


def _default_bin_limit_for_material(material: str | None) -> int:
    material = _norm_material(material)
    if material == "CAN":
        return DEFAULT_BIN_LIMIT_CAN
    if material == "PET":
        return DEFAULT_BIN_LIMIT_PET
    if material == "GLASS":
        return DEFAULT_BIN_LIMIT_GLASS
    return DEFAULT_BIN_LIMIT_UNKNOWN


class EnvipcoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        if user_input is None:
            schema = vol.Schema(
                {
                    vol.Required(CONF_USERNAME): str,
                    vol.Required(CONF_PASSWORD): str,
                    vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): vol.All(
                        int, vol.Range(min=60, max=3600)
                    ),
                }
            )
            return self.async_show_form(step_id="user", data_schema=schema)

        await self.async_set_unique_id(f"{DOMAIN}_{user_input[CONF_USERNAME]}")
        self._abort_if_unique_id_configured()

        session = async_get_clientsession(self.hass)
        client = EnvipcoEPortalApiClient(
            session=session,
            username=user_input[CONF_USERNAME],
            password=user_input[CONF_PASSWORD],
        )

        try:
            rvms = await client.rvms()
            stats = await client.rvm_stats(rvms=rvms, for_date=__import__("datetime").date.today())
        except Exception:
            rvms = []
            stats = {}

        machines = [{"id": rid, "name": rid} for rid in rvms]
        machine_rates = {rid: {"can": DEFAULT_RATE_CAN, "pet": DEFAULT_RATE_PET} for rid in rvms}

        machine_bin_limits: dict[str, dict[str, int]] = {}
        for rid in rvms:
            rvm = (stats or {}).get(rid, {}) or {}
            machine_bin_limits[rid] = {}
            for bin_no in range(1, MAX_BINS + 1):
                api_limit = rvm.get(f"{BIN_LIMIT_PREFIX}{bin_no}")
                if api_limit not in (None, ""):
                    try:
                        machine_bin_limits[rid][str(bin_no)] = int(float(api_limit))
                        continue
                    except (TypeError, ValueError):
                        pass
                material = rvm.get(f"{BIN_MATERIAL_PREFIX}{bin_no}")
                machine_bin_limits[rid][str(bin_no)] = _default_bin_limit_for_material(material)

        data = {
            CONF_USERNAME: user_input[CONF_USERNAME],
            CONF_PASSWORD: user_input[CONF_PASSWORD],
            CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            CONF_MACHINES: machines,
            CONF_MACHINE_RATES: machine_rates,
            CONF_MACHINE_BIN_LIMITS: machine_bin_limits,
        }

        return self.async_create_entry(title="Envipco ePortal", data=data)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return EnvipcoOptionsFlow(config_entry)


class EnvipcoOptionsFlow(config_entries.OptionsFlow):
    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry
        self._new_ids: list[str] = []
        self._selected_new: list[str] = []
        self._pending_opts: dict = {}
        self._machine_order: list[str] = []
        self._machine_index: int = 0
        self._latest_stats: dict[str, dict] = {}

    def _machines(self) -> list[dict]:
        return self._pending_opts.get(CONF_MACHINES, self.entry.options.get(CONF_MACHINES, self.entry.data.get(CONF_MACHINES, []))) or []

    def _rates(self) -> dict:
        return self._pending_opts.get(
            CONF_MACHINE_RATES,
            self.entry.options.get(CONF_MACHINE_RATES, self.entry.data.get(CONF_MACHINE_RATES, {})),
        ) or {}

    def _bin_limits(self) -> dict:
        return self._pending_opts.get(
            CONF_MACHINE_BIN_LIMITS,
            self.entry.options.get(CONF_MACHINE_BIN_LIMITS, self.entry.data.get(CONF_MACHINE_BIN_LIMITS, {})),
        ) or {}

    def _machine_name(self, rid: str) -> str:
        for machine in self._machines():
            if machine.get("id") == rid:
                return machine.get("name") or rid
        return rid

    def _default_limit_for_machine_bin(self, rid: str, bin_no: int) -> int:
        existing = ((self._bin_limits().get(rid) or {}).get(str(bin_no)))
        if existing not in (None, ""):
            try:
                return int(float(existing))
            except (TypeError, ValueError):
                pass

        rvm = (self._latest_stats or {}).get(rid, {}) or {}
        api_limit = rvm.get(f"{BIN_LIMIT_PREFIX}{bin_no}")
        if api_limit not in (None, ""):
            try:
                return int(float(api_limit))
            except (TypeError, ValueError):
                pass

        material = rvm.get(f"{BIN_MATERIAL_PREFIX}{bin_no}")
        return _default_bin_limit_for_material(material)

    async def _refresh_stats(self) -> None:
        session = async_get_clientsession(self.hass)
        client = EnvipcoEPortalApiClient(
            session=session,
            username=self.entry.data[CONF_USERNAME],
            password=self.entry.data[CONF_PASSWORD],
        )
        try:
            ids = [m.get("id") for m in self._machines() if m.get("id")]
            if ids:
                self._latest_stats = await client.rvm_stats(rvms=ids, for_date=__import__("datetime").date.today())
            else:
                self._latest_stats = {}
        except Exception:
            self._latest_stats = {}

    async def async_step_init(self, user_input=None):
        if user_input is None:
            schema = vol.Schema(
                {
                    vol.Optional(
                        CONF_SCAN_INTERVAL,
                        default=self.entry.options.get(
                            CONF_SCAN_INTERVAL,
                            self.entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                        ),
                    ): vol.All(int, vol.Range(min=60, max=3600)),
                    vol.Optional("scan_for_new", default=False): bool,
                }
            )
            return self.async_show_form(step_id="init", data_schema=schema)

        self._pending_opts = dict(self.entry.options)
        self._pending_opts[CONF_SCAN_INTERVAL] = user_input.get(
            CONF_SCAN_INTERVAL,
            self.entry.options.get(CONF_SCAN_INTERVAL, self.entry.data.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)),
        )
        self._pending_opts.setdefault(CONF_MACHINES, self.entry.options.get(CONF_MACHINES, self.entry.data.get(CONF_MACHINES, [])))
        self._pending_opts.setdefault(
            CONF_MACHINE_RATES,
            self.entry.options.get(CONF_MACHINE_RATES, self.entry.data.get(CONF_MACHINE_RATES, {})),
        )
        self._pending_opts.setdefault(
            CONF_MACHINE_BIN_LIMITS,
            self.entry.options.get(CONF_MACHINE_BIN_LIMITS, self.entry.data.get(CONF_MACHINE_BIN_LIMITS, {})),
        )

        if user_input.get("scan_for_new", False):
            session = async_get_clientsession(self.hass)
            client = EnvipcoEPortalApiClient(
                session=session,
                username=self.entry.data[CONF_USERNAME],
                password=self.entry.data[CONF_PASSWORD],
            )
            try:
                all_ids = await client.rvms()
            except Exception:
                return self.async_show_form(
                    step_id="init",
                    data_schema=vol.Schema(
                        {
                            vol.Optional(
                                CONF_SCAN_INTERVAL,
                                default=self._pending_opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
                            ): vol.All(int, vol.Range(min=60, max=3600)),
                            vol.Optional("scan_for_new", default=True): bool,
                        }
                    ),
                    errors={"base": "cannot_connect"},
                )

            existing = {m.get("id") for m in self._machines() if m.get("id")}
            self._new_ids = [rid for rid in (all_ids or []) if rid not in existing]

            if self._new_ids:
                return await self.async_step_select_new()

        return await self.async_step_rates()

    async def async_step_select_new(self, user_input=None):
        if user_input is None:
            schema = vol.Schema(
                {
                    vol.Optional("new_machines", default=[]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=self._new_ids,
                            multiple=True,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            )
            return self.async_show_form(step_id="select_new", data_schema=schema)

        self._selected_new = user_input.get("new_machines", []) or []
        if not self._selected_new:
            return await self.async_step_rates()

        return await self.async_step_name_new()

    async def async_step_name_new(self, user_input=None):
        if user_input is None:
            schema_dict = {}
            for rid in self._selected_new:
                schema_dict[vol.Optional(f"name_{rid}", default=rid)] = str
            return self.async_show_form(step_id="name_new", data_schema=vol.Schema(schema_dict))

        machines = list(self._machines())
        rates = dict(self._rates())
        bin_limits = dict(self._bin_limits())

        for rid in self._selected_new:
            name = (user_input.get(f"name_{rid}", rid) or rid).strip() or rid
            machines.append({"id": rid, "name": name})
            rates.setdefault(rid, {"can": DEFAULT_RATE_CAN, "pet": DEFAULT_RATE_PET})
            bin_limits.setdefault(
                rid,
                {str(bin_no): _default_bin_limit_for_material(None) for bin_no in range(1, MAX_BINS + 1)},
            )

        self._pending_opts[CONF_MACHINES] = machines
        self._pending_opts[CONF_MACHINE_RATES] = rates
        self._pending_opts[CONF_MACHINE_BIN_LIMITS] = bin_limits

        return await self.async_step_rates()

    async def async_step_rates(self, user_input=None):
        machines = self._machines()
        rates = self._rates()

        if user_input is None:
            schema_dict = {}
            for m in machines:
                rid = m.get("id")
                if not rid:
                    continue
                name = m.get("name") or rid
                r = rates.get(rid, {}) or {}
                schema_dict[vol.Optional(f"can_{rid}", default=float(r.get("can", DEFAULT_RATE_CAN)), description={"suggested_value": f"{name} - CAN"})] = vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=5)
                )
                schema_dict[vol.Optional(f"pet_{rid}", default=float(r.get("pet", DEFAULT_RATE_PET)), description={"suggested_value": f"{name} - PET"})] = vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=5)
                )
            return self.async_show_form(step_id="rates", data_schema=vol.Schema(schema_dict))

        new_rates = dict(rates)
        for m in machines:
            rid = m.get("id")
            if not rid:
                continue
            can = user_input.get(f"can_{rid}", DEFAULT_RATE_CAN)
            pet = user_input.get(f"pet_{rid}", DEFAULT_RATE_PET)
            new_rates[rid] = {"can": round(float(can), 4), "pet": round(float(pet), 4)}

        self._pending_opts[CONF_MACHINE_RATES] = new_rates
        await self._refresh_stats()
        self._machine_order = [m.get("id") for m in machines if m.get("id")]
        self._machine_index = 0

        if not self._machine_order:
            return self.async_create_entry(title="", data=self._pending_opts)

        return await self.async_step_bin_limits()

    async def async_step_bin_limits(self, user_input=None):
        if self._machine_index >= len(self._machine_order):
            return self.async_create_entry(title="", data=self._pending_opts)

        rid = self._machine_order[self._machine_index]
        machine_name = self._machine_name(rid)
        current = dict(self._bin_limits())

        if user_input is None:
            schema_dict = {}
            for bin_no in range(1, MAX_BINS + 1):
                default_limit = self._default_limit_for_machine_bin(rid, bin_no)
                schema_dict[vol.Optional(f"bin_{bin_no}", default=default_limit)] = vol.All(
                    vol.Coerce(int), vol.Range(min=0, max=100000)
                )

            return self.async_show_form(
                step_id="bin_limits",
                data_schema=vol.Schema(schema_dict),
                description_placeholders={
                    "machine_name": machine_name,
                    "machine_id": rid,
                },
            )

        per_machine = dict(current.get(rid, {}) or {})
        for bin_no in range(1, MAX_BINS + 1):
            per_machine[str(bin_no)] = int(user_input.get(f"bin_{bin_no}", self._default_limit_for_machine_bin(rid, bin_no)))
        current[rid] = per_machine
        self._pending_opts[CONF_MACHINE_BIN_LIMITS] = current

        self._machine_index += 1
        if self._machine_index >= len(self._machine_order):
            return self.async_create_entry(title="", data=self._pending_opts)

        return await self.async_step_bin_limits()
