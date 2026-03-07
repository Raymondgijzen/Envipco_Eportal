from __future__ import annotations

from collections import defaultdict
from datetime import date

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import EnvipcoApiError, EnvipcoEPortalApiClient
from .const import (
    ACCEPT_FIELDS_PREFIX,
    CONF_MACHINE_BIN_CAPACITY,
    CONF_MACHINES,
    CONF_MACHINE_RATES,
    DEFAULT_BIN_CAPACITY_CAN,
    DEFAULT_BIN_CAPACITY_GLASS,
    DEFAULT_BIN_CAPACITY_PET,
    DEFAULT_RATE_CAN,
    DEFAULT_RATE_PET,
    KEY_ACCEPTED_CANS,
    KEY_ACCEPTED_GLASS,
    KEY_ACCEPTED_PET,
    REJECT_KEYS,
)


class EnvipcoCoordinator(DataUpdateCoordinator[dict]):
    def __init__(
        self,
        hass: HomeAssistant,
        client: EnvipcoEPortalApiClient,
        entry: ConfigEntry,
        update_interval,
    ) -> None:
        super().__init__(
            hass,
            logger=__import__("logging").getLogger(__name__),
            name="Envipco ePortal",
            update_interval=update_interval,
        )
        self.client = client
        self.entry = entry

    def _machines(self) -> list[dict]:
        return self.entry.options.get(CONF_MACHINES, self.entry.data.get(CONF_MACHINES, [])) or []

    def _rvm_ids(self) -> list[str]:
        return [m.get("id") for m in self._machines() if m.get("id")]

    def machine_name(self, rvm_id: str) -> str:
        for m in self._machines():
            if m.get("id") == rvm_id:
                return m.get("name") or rvm_id
        return rvm_id

    def _rates(self, rvm_id: str) -> tuple[float, float]:
        rates = self.entry.options.get(CONF_MACHINE_RATES, {}) or {}
        r = rates.get(rvm_id, {}) or {}
        can = float(r.get("can", DEFAULT_RATE_CAN))
        pet = float(r.get("pet", DEFAULT_RATE_PET))
        return can, pet

    def bin_capacities(self, rvm_id: str) -> dict[str, int]:
        all_caps = self.entry.options.get(CONF_MACHINE_BIN_CAPACITY, {}) or {}
        caps = all_caps.get(rvm_id, {}) or {}
        return {
            "can": int(caps.get("can", DEFAULT_BIN_CAPACITY_CAN)),
            "pet": int(caps.get("pet", DEFAULT_BIN_CAPACITY_PET)),
            "glass": int(caps.get("glass", DEFAULT_BIN_CAPACITY_GLASS)),
        }

    @staticmethod
    def _safe_int(v) -> int:
        try:
            return int(float(str(v).strip()))
        except Exception:
            return 0

    @staticmethod
    def _accepted_from_rejects_row(row: dict[str, str]) -> int:
        total = 0
        for k, v in row.items():
            if isinstance(k, str) and k.startswith(ACCEPT_FIELDS_PREFIX):
                total += EnvipcoCoordinator._safe_int(v)
        return total

    async def _async_update_data(self) -> dict:
        rvms = self._rvm_ids()
        today = date.today()

        if not rvms:
            return {"stats": {}, "rejects": {}, "totals": {}, "date": today.isoformat()}

        try:
            stats = await self.client.rvm_stats(rvms=rvms, for_date=today)
            reject_rows = await self.client.rejects(rvms=rvms, start=today, end=today, include_acceptance=True)

            rejects_by_rvm = defaultdict(lambda: {k: 0 for k in REJECT_KEYS})
            accepted_by_rvm_from_rejects = defaultdict(int)

            for row in reject_rows or []:
                rvm = (row.get("rvm") or "").strip()
                if not rvm:
                    continue
                for k in REJECT_KEYS:
                    rejects_by_rvm[rvm][k] += self._safe_int(row.get(k))
                accepted_by_rvm_from_rejects[rvm] += self._accepted_from_rejects_row(row)

            totals: dict[str, dict] = {}

            for rvm_id in rvms:
                r_stats = (stats or {}).get(rvm_id, {}) or {}

                cans = self._safe_int(r_stats.get(KEY_ACCEPTED_CANS))
                pet = self._safe_int(r_stats.get(KEY_ACCEPTED_PET))
                glass = self._safe_int(r_stats.get(KEY_ACCEPTED_GLASS))

                accepted_total = cans + pet + glass
                if accepted_total <= 0:
                    accepted_total = accepted_by_rvm_from_rejects.get(rvm_id, 0)

                rej_map = rejects_by_rvm.get(rvm_id, {k: 0 for k in REJECT_KEYS})
                rejects_total = sum(int(rej_map.get(k, 0) or 0) for k in REJECT_KEYS)

                denom = accepted_total + rejects_total
                reject_rate = (rejects_total / denom) * 100.0 if denom > 0 else None

                rate_can, rate_pet = self._rates(rvm_id)
                revenue_can_today = cans * rate_can
                revenue_pet_today = pet * rate_pet
                revenue_today = revenue_can_today + revenue_pet_today

                totals[rvm_id] = {
                    "accepted_cans": cans,
                    "accepted_pet": pet,
                    "accepted_glass": glass,
                    "accepted_total": accepted_total,
                    "rejects_total": rejects_total,
                    "reject_rate": reject_rate,
                    "rate_can": rate_can,
                    "rate_pet": rate_pet,
                    "revenue_today": revenue_today,
                    "revenue_can_today": revenue_can_today,
                    "revenue_pet_today": revenue_pet_today,
                }

            return {
                "stats": stats or {},
                "rejects": dict(rejects_by_rvm),
                "totals": totals,
                "date": today.isoformat(),
            }

        except EnvipcoApiError as err:
            # Voorkom 'niet beschikbaar' flapping: bij tijdelijke API-fout houden we de laatste data vast.
            if self.data:
                self.logger.warning("Envipco update mislukt, laatste data blijft staan: %s", err)
                return self.data
            raise UpdateFailed(str(err)) from err

        except Exception as err:
            if self.data:
                self.logger.warning("Envipco update mislukt, laatste data blijft staan: %s", err)
                return self.data
            raise UpdateFailed(str(err)) from err
