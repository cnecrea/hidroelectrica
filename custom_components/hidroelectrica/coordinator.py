"""DataUpdateCoordinator pentru integrarea Hidroelectrica România.

Strategia de actualizare:
- Refresh ușor (light):  endpoint-uri esențiale — bill, multi_meter, window_dates
- Refresh greu (heavy, la fiecare al 4-lea): + usage, billing_history, meter_read_history
- Datele grele se reutilizează între refresh-urile ușoare
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)

from .api import HidroelectricaApiClient, HidroelectricaApiError

_LOGGER = logging.getLogger(__name__)

# La fiecare al N-lea refresh se face „heavy" (include istorice)
HEAVY_REFRESH_EVERY = 4


class HidroelectricaCoordinator(DataUpdateCoordinator):
    """Coordinator pentru datele Hidroelectrica — per cont (UAN)."""

    def __init__(
        self,
        hass: HomeAssistant,
        api_client: HidroelectricaApiClient,
        uan: str,
        account_number: str,
        update_interval: int,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"HidroelectricaCoordinator_{uan}",
            update_interval=timedelta(seconds=update_interval),
        )

        self.api_client = api_client
        self.uan = uan
        self.account_number = account_number
        self._config_entry = config_entry
        self._refresh_counter: int = 0
        # Salvăm generația token-ului la creare — dacă alt coordinator
        # a făcut deja login proaspăt, nu invalidăm din nou.
        self._startup_gen: int = api_client.token_generation

    @property
    def _is_heavy_refresh(self) -> bool:
        """Determină dacă refresh-ul curent este „greu"."""
        return self._refresh_counter % HEAVY_REFRESH_EVERY == 0

    async def _async_update_data(self) -> dict:
        """Obține date de la API cu strategie light/heavy."""
        uan = self.uan
        acc = self.account_number
        is_heavy = self._is_heavy_refresh

        _LOGGER.debug(
            "Actualizare Hidroelectrica (UAN=%s, AccountNumber='%s', "
            "refresh=#%s, tip=%s).",
            uan,
            acc,
            self._refresh_counter,
            "HEAVY" if is_heavy else "light",
        )

        if not acc:
            _LOGGER.warning(
                "AccountNumber GOL pentru UAN=%s! "
                "Se încearcă obținerea din GetUserSetting...",
                uan,
            )
            try:
                await self.api_client.async_ensure_authenticated()
                fresh_accounts = await self.api_client.async_fetch_utility_accounts()
                for fa in fresh_accounts:
                    if fa.get("contractAccountID", "").strip() == uan:
                        acc = fa.get("accountNumber", "").strip()
                        if acc:
                            self.account_number = acc
                            _LOGGER.info(
                                "AccountNumber obținut din API: '%s' (UAN=%s).",
                                acc, uan,
                            )
                        break
                if not acc:
                    _LOGGER.error(
                        "AccountNumber nu a putut fi obținut nici din API (UAN=%s)!",
                        uan,
                    )
            except Exception as err:
                _LOGGER.error(
                    "Eroare la obținerea AccountNumber din API (UAN=%s): %s",
                    uan, err,
                )

        try:
            # La primul refresh (startup), token-ul din storage e aproape
            # sigur expirat server-side → forțăm re-login proaspăt.
            # Altfel, toate request-urile paralele primesc 401 simultan.
            # Verificăm _login_generation pentru a evita invalidarea
            # token-ului proaspăt obținut de alt coordinator.
            if self._refresh_counter == 0 and self._startup_gen == self.api_client.token_generation:
                _LOGGER.debug(
                    "Primul refresh — forțez login proaspăt (UAN=%s).", uan
                )
                self.api_client.invalidate_session()
                await self.api_client.async_ensure_authenticated()
            elif not self.api_client.has_token:
                _LOGGER.debug(
                    "Token absent. Se autentifică (UAN=%s).", uan
                )
                await self.api_client.async_ensure_authenticated()

            # ──────────────────────────────────────────
            # Endpoint-uri ESENȚIALE — Faza 1: paralel (fără dependențe)
            # ──────────────────────────────────────────
            essential_phase1 = [
                self.api_client.async_fetch_multi_meter(uan, acc),
                self.api_client.async_fetch_bill(uan, acc),
                self.api_client.async_fetch_window_dates_enc(uan, acc),
                self.api_client.async_fetch_window_dates(uan, acc),
                self.api_client.async_fetch_pods(uan, acc),
            ]

            (
                multi_meter,
                bill,
                window_dates_enc,
                window_dates,
                pods,
            ) = await asyncio.gather(*essential_phase1)

            # ──────────────────────────────────────────
            # Extragere InstallationNumber / podValue din GetPods
            # (necesare pentru GetPreviousMeterRead, CounterSeries, ReadHistory)
            # ──────────────────────────────────────────
            installation_number = ""
            pod_value = ""
            customer_number = ""

            if pods and isinstance(pods, dict):
                pods_data = pods.get("result", {})
                if isinstance(pods_data, dict):
                    pods_data = pods_data.get("Data", [])
                if isinstance(pods_data, list) and pods_data:
                    first_pod = pods_data[0]
                    installation_number = str(
                        first_pod.get("installation",
                                      first_pod.get("InstallationNumber", ""))
                    )
                    pod_value = str(
                        first_pod.get("pod",
                                      first_pod.get("podValue", ""))
                    )
                    customer_number = str(
                        first_pod.get("accountID", "")
                    )

            _LOGGER.debug(
                "Pods extras (UAN=%s): installation='%s', pod='%s', "
                "customerNumber='%s'.",
                uan, installation_number, pod_value, customer_number,
            )

            # ──────────────────────────────────────────
            # Faza 2: GetPreviousMeterRead (depinde de Pods)
            # ──────────────────────────────────────────
            previous_meter_read = await self.api_client.async_fetch_previous_meter_read(
                uan,
                installation_number=installation_number,
                pod_value=pod_value,
                customer_number=customer_number,
            )

            _LOGGER.debug(
                "Date esențiale (UAN=%s): multi_meter=%s, bill=%s, "
                "window_dates=%s, pods=%s, prev_read=%s.",
                uan,
                type(multi_meter).__name__ if multi_meter else None,
                type(bill).__name__ if bill else None,
                type(window_dates).__name__ if window_dates else None,
                type(pods).__name__ if pods else None,
                type(previous_meter_read).__name__ if previous_meter_read else None,
            )

            # ──────────────────────────────────────────
            # Endpoint-uri GRELE (doar la heavy refresh)
            # ──────────────────────────────────────────
            prev = self.data or {}

            if is_heavy:
                # Calculăm intervalul de date
                end_date = datetime.now()
                start_date = end_date - timedelta(days=2 * 365)
                from_date = start_date.strftime("%Y-%m-%d")
                to_date = end_date.strftime("%Y-%m-%d")

                if not installation_number or not pod_value:
                    _LOGGER.error(
                        "InstallationNumber/podValue GOALE (UAN=%s)! "
                        "GetMeterCounterSeries/GetMeterReadHistory vor eșua.",
                        uan,
                    )

                # Usage și BillingHistory nu depind de pods
                # MeterCounterSeries și MeterReadHistory NU mai pot rula în paralel:
                # MeterReadHistory are nevoie de SerialNumber din CounterSeries
                # Dar din testare, SerialNumber poate fi [] deci le rulăm în paralel

                heavy_tasks = [
                    self.api_client.async_fetch_usage(uan, acc),
                    self.api_client.async_fetch_billing_history(
                        uan, acc, from_date, to_date
                    ),
                    self.api_client.async_fetch_meter_counter_series(
                        uan, installation_number, pod_value,
                    ),
                    self.api_client.async_fetch_meter_read_history(
                        uan, installation_number, pod_value,
                    ),
                ]

                (
                    usage,
                    billing_history,
                    meter_counter_series,
                    meter_read_history,
                ) = await asyncio.gather(*heavy_tasks)

                _LOGGER.debug(
                    "Date grele (UAN=%s): usage=%s, billing=%s, "
                    "counter_series=%s, read_history=%s.",
                    uan,
                    "OK" if usage else "None",
                    "OK" if billing_history else "None",
                    "OK" if meter_counter_series else "None",
                    "OK" if meter_read_history else "None",
                )
            else:
                # Light refresh: reutilizăm datele grele anterioare
                usage = prev.get("usage")
                billing_history = prev.get("billing_history")
                meter_counter_series = prev.get("meter_counter_series")
                meter_read_history = prev.get("meter_read_history")

        except HidroelectricaApiError as err:
            _LOGGER.error(
                "Eroare API la actualizarea datelor (UAN=%s): %s", uan, err
            )
            raise UpdateFailed(
                f"Eroare API Hidroelectrica: {err}"
            ) from err

        except asyncio.TimeoutError as err:
            _LOGGER.error(
                "Timeout la actualizarea datelor (UAN=%s): %s", uan, err
            )
            raise UpdateFailed(
                "Depășire de timp la actualizarea datelor Hidroelectrica."
            ) from err

        except Exception as err:
            _LOGGER.exception(
                "Eroare neașteptată la actualizarea datelor (UAN=%s): %s",
                uan,
                err,
            )
            raise UpdateFailed(
                "Eroare neașteptată la actualizarea datelor Hidroelectrica."
            ) from err

        # Verificăm datele esențiale — avertizăm dar nu picăm
        # (unele endpoint-uri returnează 400 pe anumite conturi)
        available_count = sum(
            1 for v in (multi_meter, bill, window_dates_enc, window_dates, pods)
            if v is not None
        )
        if available_count == 0 and self._refresh_counter == 0:
            _LOGGER.error(
                "Niciun endpoint esențial nu a returnat date (UAN=%s, acc=%s). "
                "Verificați dacă AccountNumber este corect.",
                uan, acc,
            )
            raise UpdateFailed(
                "Nu s-au putut obține datele esențiale de la Hidroelectrica."
            )
        elif available_count < 3:
            _LOGGER.warning(
                "Doar %s din 5 endpoint-uri esențiale au returnat date (UAN=%s).",
                available_count, uan,
            )

        # Persistăm token-ul
        self._persist_token()

        # Incrementăm contorul
        self._refresh_counter += 1

        _LOGGER.debug(
            "Actualizare Hidroelectrica finalizată (UAN=%s, refresh=#%s).",
            uan,
            self._refresh_counter - 1,
        )

        return {
            # Contor
            "multi_meter": multi_meter,
            # Factură
            "bill": bill,
            # Fereastra autocitire
            "window_dates_enc": window_dates_enc,
            "window_dates": window_dates,
            # Autocitire
            "pods": pods,
            "previous_meter_read": previous_meter_read,
            # Istorice (heavy)
            "usage": usage,
            "billing_history": billing_history,
            "meter_counter_series": meter_counter_series,
            "meter_read_history": meter_read_history,
        }

    def _persist_token(self) -> None:
        """Persistă token-ul curent în config_entry.data (pentru restart HA)."""
        if self._config_entry is None:
            return
        token_data = self.api_client.export_token_data()
        if token_data is None:
            return

        current_data = dict(self._config_entry.data)
        old_token = current_data.get("token_data", {})

        # Actualizăm doar dacă s-a schimbat
        if (
            old_token.get("session_token") == token_data.get("session_token")
            and old_token.get("user_id") == token_data.get("user_id")
        ):
            return

        current_data["token_data"] = token_data
        self.hass.config_entries.async_update_entry(
            self._config_entry, data=current_data
        )
        _LOGGER.debug(
            "Token persistat în config_entry (UAN=%s, user_id=%s).",
            self.uan,
            token_data.get("user_id", "?"),
        )
