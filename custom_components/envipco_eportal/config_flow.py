from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EnvipcoEPortalApiClient
from .const import (
    CONF_MACHINE_BIN_CAPACITY,
    CONF_MACHINE_RATES,
    CONF_MACHINES,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
    DEFAULT_BIN_CAPACITY_CAN,
    DEFAULT_BIN_CAPACITY_GLASS,
    DEFAULT_BIN_CAPACITY_PET,
    DEFAULT_RATE_CAN,
    DEFAULT_RATE_PET,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
)


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
        except Exception:
            rvms = []

        machines = [{"id": rid, "name": rid} for rid in rvms]
        machine_rates = {rid: {"can": DEFAULT_RATE_CAN, "pet": DEFAULT_RATE_PET} for rid in rvms}
        machine_bin_capacity = {
            rid: {
                "can": DEFAULT_BIN_CAPACITY_CAN,
                "pet": DEFAULT_BIN_CAPACITY_PET,
                "glass": DEFAULT_BIN_CAPACITY_GLASS,
            }
            for rid in rvms
        }

        data = {
            CONF_USERNAME: user_input[CONF_USERNAME],
            CONF_PASSWORD: user_input[CONF_PASSWORD],
            CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            CONF_MACHINES: machines,
            CONF_MACHINE_RATES: machine_rates,
            CONF_MACHINE_BIN_CAPACITY: machine_bin_capacity,
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

    def _machines(self) -> list[dict]:
        return self._pending_opts.get(CONF_MACHINES, self.entry.options.get(CONF_MACHINES, self.entry.data.get(CONF_MACHINES, [])) or [])

    def _rates(self) -> dict:
        return self._pending_opts.get(
            CONF_MACHINE_RATES,
            self.entry.options.get(CONF_MACHINE_RATES, self.entry.data.get(CONF_MACHINE_RATES, {})) or {},
        )

    def _bin_caps(self) -> dict:
        return self._pending_opts.get(
            CONF_MACHINE_BIN_CAPACITY,
            self.entry.options.get(CONF_MACHINE_BIN_CAPACITY, self.entry.data.get(CONF_MACHINE_BIN_CAPACITY, {})) or {},
        )

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
            CONF_SCAN_INTERVAL, self._pending_opts.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
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
        bin_caps = dict(self._bin_caps())

        for rid in self._selected_new:
            name = (user_input.get(f"name_{rid}", rid) or rid).strip() or rid
            machines.append({"id": rid, "name": name})
            rates.setdefault(rid, {"can": DEFAULT_RATE_CAN, "pet": DEFAULT_RATE_PET})
            bin_caps.setdefault(
                rid,
                {
                    "can": DEFAULT_BIN_CAPACITY_CAN,
                    "pet": DEFAULT_BIN_CAPACITY_PET,
                    "glass": DEFAULT_BIN_CAPACITY_GLASS,
                },
            )

        self._pending_opts[CONF_MACHINES] = machines
        self._pending_opts[CONF_MACHINE_RATES] = rates
        self._pending_opts[CONF_MACHINE_BIN_CAPACITY] = bin_caps

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
                r = rates.get(rid, {}) or {}
                schema_dict[vol.Optional(f"can_{rid}", default=float(r.get("can", DEFAULT_RATE_CAN)))] = vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=5)
                )
                schema_dict[vol.Optional(f"pet_{rid}", default=float(r.get("pet", DEFAULT_RATE_PET)))] = vol.All(
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
        return await self.async_step_bin_capacity()

    async def async_step_bin_capacity(self, user_input=None):
        machines = self._machines()
        bin_caps = self._bin_caps()

        if user_input is None:
            schema_dict = {}
            for m in machines:
                rid = m.get("id")
                name = m.get("name") or rid
                if not rid:
                    continue
                caps = bin_caps.get(rid, {}) or {}
                schema_dict[vol.Optional(f"can_cap_{rid}", default=int(caps.get("can", DEFAULT_BIN_CAPACITY_CAN)))] = vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=1000000)
                )
                schema_dict[vol.Optional(f"pet_cap_{rid}", default=int(caps.get("pet", DEFAULT_BIN_CAPACITY_PET)))] = vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=1000000)
                )
                schema_dict[vol.Optional(f"glass_cap_{rid}", default=int(caps.get("glass", DEFAULT_BIN_CAPACITY_GLASS)))] = vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=1000000)
                )
            return self.async_show_form(step_id="bin_capacity", data_schema=vol.Schema(schema_dict))

        new_caps = dict(bin_caps)
        for m in machines:
            rid = m.get("id")
            if not rid:
                continue
            new_caps[rid] = {
                "can": int(user_input.get(f"can_cap_{rid}", DEFAULT_BIN_CAPACITY_CAN)),
                "pet": int(user_input.get(f"pet_cap_{rid}", DEFAULT_BIN_CAPACITY_PET)),
                "glass": int(user_input.get(f"glass_cap_{rid}", DEFAULT_BIN_CAPACITY_GLASS)),
            }

        self._pending_opts[CONF_MACHINE_BIN_CAPACITY] = new_caps
        return self.async_create_entry(title="", data=self._pending_opts)
