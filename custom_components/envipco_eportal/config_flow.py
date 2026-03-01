from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import EnvipcoEPortalApiClient
from .const import (
    CONF_MACHINE_RATES,
    CONF_MACHINES,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
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

        data = {
            CONF_USERNAME: user_input[CONF_USERNAME],
            CONF_PASSWORD: user_input[CONF_PASSWORD],
            CONF_SCAN_INTERVAL: user_input.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL),
            CONF_MACHINES: machines,
            CONF_MACHINE_RATES: machine_rates,
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
        return self._pending_opts.get(CONF_MACHINES, self.entry.data.get(CONF_MACHINES, [])) or []

    def _rates(self) -> dict:
        return self._pending_opts.get(CONF_MACHINE_RATES, self.entry.data.get(CONF_MACHINE_RATES, {})) or {}

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

        for rid in self._selected_new:
            name = (user_input.get(f"name_{rid}", rid) or rid).strip() or rid
            machines.append({"id": rid, "name": name})
            rates.setdefault(rid, {"can": DEFAULT_RATE_CAN, "pet": DEFAULT_RATE_PET})

        self._pending_opts[CONF_MACHINES] = machines
        self._pending_opts[CONF_MACHINE_RATES] = rates

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
        return self.async_create_entry(title="", data=self._pending_opts)
