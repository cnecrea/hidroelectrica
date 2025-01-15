"""
Coordonator de date pentru integrarea Hidroelectrica România.
"""

import logging
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
)
from .api import HidroelectricaAPI

_LOGGER = logging.getLogger(__name__)

class HidroelectricaCoordinator(DataUpdateCoordinator):
    """
    Coordonatorul principal de date pentru Hidroelectrica.
    Folosește HidroelectricaAPI (sincron) și rulează sub formă asincronă prin async_add_executor_job.
    """

    def __init__(self, hass: HomeAssistant, entry):
        """
        :param hass: Instanța principală Home Assistant
        :param entry: ConfigEntry ce conține user, parola, update_interval
        """
        self.hass = hass
        self.entry = entry

        self.username = entry.data[CONF_USERNAME]
        self.password = entry.data[CONF_PASSWORD]
        self.update_interval_seconds = entry.data.get(CONF_UPDATE_INTERVAL, 3600)

        # Instanțiem API-ul (login-ul îl facem ulterior, în _async_update_data)
        self.api = HidroelectricaAPI(self.username, self.password)

        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_coordinator",
            update_interval=timedelta(seconds=self.update_interval_seconds),
        )

        # Structură inițială goală
        self.data = {
            "utility_accounts": [],
            "accounts_data": {}
        }

    async def _async_update_data(self):
        """
        Metoda apelată de DataUpdateCoordinator la fiecare refresh.
        Aici colectăm datele de la HidroelectricaAPI pentru fiecare cont.
        Dacă aveam deja un _session_token valid, login() nu se va relansa.
        """
        try:
            _LOGGER.debug("=== HIDRO: Începem procesul de actualizare a datelor... ===")

            # 1. Login doar dacă nu avem deja session_token (metodă nouă în api.py)
            await self.hass.async_add_executor_job(self.api.login_if_needed)

            # 2. Obținem lista de conturi (coduri de încasare) => utility_accounts
            utility_accounts = self.api.get_utility_accounts() or []
            self.data["utility_accounts"] = utility_accounts

            # 2.1 Obținem datele brute din ValidateUserLogin (toate rândurile) 
            #     și din GetUserSetting (raw).
            validate_user_login_rows = self.api.get_validate_user_login_data() or []
            raw_user_setting_data = self.api.get_raw_user_setting_data() or {}

            # Mapăm sub-dicționare => UAN -> row
            user_setting_map = self._map_user_setting_rows_by_uan(raw_user_setting_data)
            validate_login_map = self._map_validate_login_rows_by_uan(validate_user_login_rows)

            accounts_data = {}

            # 3. Pentru fiecare cont, apelăm restul endpoint-urilor
            for acc_info in utility_accounts:
                uan = acc_info.get("UtilityAccountNumber")  
                acc_no = acc_info.get("AccountNumber")      

                if not uan or not acc_no:
                    _LOGGER.warning(
                        "Date cont incomplete: %s (lipsă UAN/AccountNumber?). Sărim peste...",
                        acc_info
                    )
                    continue

                _LOGGER.debug("=== HIDRO: Extragem date pt UAN=%s, AccountNumber=%s ===", uan, acc_no)

                # 3.1 ValidateUserLogin - rândul pentru acest cont
                resp_validate_login = validate_login_map.get(uan, {})

                # 3.2 GetUserSetting - rândul pentru acest cont
                resp_user_setting = user_setting_map.get(uan, {})

                # 3.3 Apele endpoint-urilor sincrone
                resp_multi_meter = await self.hass.async_add_executor_job(
                    self.api.get_multi_meter_details, uan, acc_no
                ) or {}

                resp_meter_value = await self.hass.async_add_executor_job(
                    self.api.get_current_meter_value, uan, acc_no
                ) or {}

                resp_window_dates = await self.hass.async_add_executor_job(
                    self.api.get_window_dates_enc, uan, acc_no
                ) or {}

                resp_bill = await self.hass.async_add_executor_job(
                    self.api.get_current_bill, uan, acc_no
                ) or {}

                # Calculăm intervalul de date dinamic
                end_date = datetime.now()  # Data curentă
                start_date = end_date - timedelta(days=2 * 365)  # Cu aproximativ doi ani în urmă

                start_date_str = start_date.strftime("%Y-%m-%d")  # Formatare: "YYYY-MM-DD"
                end_date_str = end_date.strftime("%Y-%m-%d")      # Formatare: "YYYY-MM-DD"

                # Istoric facturi
                resp_billing_history = await self.hass.async_add_executor_job(
                    self.api.get_bill_history, uan, acc_no, start_date_str, end_date_str
                ) or {}

                resp_usage_gen = await self.hass.async_add_executor_job(
                    self.api.get_usage_generation, uan, acc_no
                ) or {"result": {"Data": {"objUsageGenerationResultSetTwo": []}}}

                # Obținem anul curent
                current_year = datetime.now().year
                cutoff_year = current_year - 2  # ultimii doi ani

                # Navigăm în structura JSON
                gen_data = resp_usage_gen.get("result", {}).get("Data", {})
                gen_list = gen_data.get("objUsageGenerationResultSetTwo", []) or []

                # Construim o listă filtrată, reținând doar item-urile cu Year >= cutoff_year
                filtered_list = []
                for entry in gen_list:
                    entry_year = entry.get("Year", 0)
                    if entry_year >= cutoff_year:
                        filtered_list.append(entry)

                # Punem lista filtrată înapoi
                resp_usage_gen["result"]["Data"]["objUsageGenerationResultSetTwo"] = filtered_list

                # 3.4 Stocăm totul într-un sub-dicționar
                accounts_data[uan] = {
                    "validate_user_login": resp_validate_login,
                    "get_user_setting": resp_user_setting,
                    "get_multi_meter": resp_multi_meter,
                    "get_meter_value": resp_meter_value,
                    "get_window_dates_enc": resp_window_dates,
                    "get_bill": resp_bill,
                    "get_billing_history_list": resp_billing_history,
                    "get_usage_generation": resp_usage_gen,
                }

            self.data["accounts_data"] = accounts_data
            _LOGGER.debug("=== HIDRO: Actualizare finalizată cu succes. ===")

            return self.data

        except Exception as err:
            _LOGGER.error("Eroare la actualizarea datelor Hidroelectrica: %s", err)
            raise UpdateFailed(f"Update error: {err}")

    def _map_user_setting_rows_by_uan(self, raw_user_setting_data):
        """
        Transformă datele brute din GetUserSetting (Table1, Table2)
        într-un dict: { <UtilityAccountNumber>: <rând> }
        """
        if not raw_user_setting_data:
            return {}

        result_data = raw_user_setting_data.get("result", {}).get("Data", {})
        table1 = result_data.get("Table1", [])
        table2 = result_data.get("Table2", [])

        combined = table1 + table2

        user_setting_map = {}
        for row in combined:
            uan = row.get("UtilityAccountNumber")
            if uan and uan not in user_setting_map:
                user_setting_map[uan] = row
        return user_setting_map

    def _map_validate_login_rows_by_uan(self, validate_user_login_rows):
        """
        Transformă list[dict] (din ValidateUserLogin -> "Table") într-un dict:
        { <UtilityAccountNumber>: <rând> }
        """
        v_map = {}
        for row in validate_user_login_rows:
            uan = row.get("UtilityAccountNumber")
            if uan and uan not in v_map:
                v_map[uan] = row
        return v_map
