"""Platforma Button pentru Hidroelectrica România — Trimitere autocitire."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    EVENT_AUTOCITIRE_ERROR,
    EVENT_AUTOCITIRE_SUCCESS,
    LICENSE_DATA_KEY,
)
from .api import HidroelectricaApiError
from .coordinator import HidroelectricaCoordinator
from .helpers import build_usage_entity, safe_get

def _extract_list(data: Any, list_key: str) -> list:
    """Extrage o listă dintr-un răspuns API care poate fi dict sau list."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get(list_key, []) or []
    return []

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Configurează butoanele pentru Hidroelectrica România."""
    _LOGGER.debug(
        "Se inițializează platforma button pentru %s (entry_id=%s).",
        DOMAIN,
        config_entry.entry_id,
    )

    # Fără licență validă, nu creăm butoane
    mgr = hass.data.get(DOMAIN, {}).get(LICENSE_DATA_KEY)
    if not mgr or not mgr.is_valid:
        _LOGGER.info(
            "Licență invalidă: nu se creează butoane (entry_id=%s).",
            config_entry.entry_id,
        )
        # Butoanele create anterior ar rămâne în registry ca entități orfane
        # „indisponibile" (senzorii sunt deja curățați în sensor.py).
        registru = er.async_get(hass)
        for entry_reg in er.async_entries_for_config_entry(
            registru, config_entry.entry_id
        ):
            if entry_reg.domain == "button":
                registru.async_remove(entry_reg.entity_id)
        return

    entities: list[ButtonEntity] = []

    for uan, coordinator in config_entry.runtime_data.coordinators.items():
        # Prosumatorii (registru 1.8.0_P) nu trimit index — distribuitorul citește automat
        data = coordinator.data or {}
        mrh = data.get("meter_read_history")
        is_prosumer = False
        if mrh and isinstance(mrh, dict):
            mrh_data = safe_get(mrh, "result", "Data", default=[])
            if isinstance(mrh_data, list):
                is_prosumer = any(
                    r.get("Registers") == "1.8.0_P" for r in mrh_data
                )

        if is_prosumer:
            _LOGGER.info(
                "Prosumator detectat (UAN=%s): butonul 'Trimite index' NU se creează "
                "(distribuitorul citește contorul automat).",
                uan,
            )
            continue

        entities.append(
            TrimiteIndexButton(
                coordinator=coordinator,
                config_entry=config_entry,
            )
        )

    if entities:
        async_add_entities(entities)
        _LOGGER.debug(
            "Platforma button: %s butoane create (entry_id=%s).",
            len(entities),
            config_entry.entry_id,
        )


class TrimiteIndexButton(
    CoordinatorEntity[HidroelectricaCoordinator], ButtonEntity
):
    """Buton pentru trimiterea autocitiri (self-meter read) la Hidroelectrica."""

    _attr_has_entity_name = False

    def __init__(
        self,
        coordinator: HidroelectricaCoordinator,
        config_entry: ConfigEntry,
    ) -> None:
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._uan = coordinator.uan

        self._attr_name = "Trimite index energie electrică"
        self._attr_icon = "mdi:send-circle"
        self._attr_translation_key = "trimite_index_energie_electrica"
        self._attr_unique_id = f"{DOMAIN}_trimite_index_{self._uan}"
        self._custom_entity_id = f"button.{DOMAIN}_{self._uan}_trimite_index_energie_electrica"

        # Entitatea input_number din care citim valoarea indexului
        self._input_number_entity = f"input_number.{DOMAIN}_{self._uan}_index_energie_electrica"

    @property
    def entity_id(self) -> str | None:
        return self._custom_entity_id

    @entity_id.setter
    def entity_id(self, value: str) -> None:
        self._custom_entity_id = value

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._uan)},
            name=f"Hidroelectrica România ({self._uan})",
            manufacturer="Ciprian Nicolae (cnecrea)",
            model="Hidroelectrica România",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_press(self) -> None:
        """Trimite autocitirea și anunță rezultatul prin evenimente HA.

        Evenimente (pentru automatizări, ex. notificări):
        - `hidroelectrica_autocitire_success` — {uan, index}
        - `hidroelectrica_autocitire_error` — {uan, index, error}
        """
        index: int | None = None
        try:
            index = self._citeste_index()
            await self._async_trimite_index(index)
        except HomeAssistantError as err:
            self._anunta_eroare(index, err)
            raise
        except Exception as err:
            _LOGGER.exception(
                "Eroare neașteptată la trimiterea autocitirii (UAN=%s).", self._uan
            )
            ha_err = HomeAssistantError(
                f"Eroare neașteptată la trimiterea autocitirii: {err}"
            )
            self._anunta_eroare(index, ha_err)
            raise ha_err from err

        self.hass.bus.async_fire(
            EVENT_AUTOCITIRE_SUCCESS, {"uan": self._uan, "index": index}
        )
        await self.coordinator.async_request_refresh()

    def _anunta_eroare(self, index: int | None, err: HomeAssistantError) -> None:
        self.hass.bus.async_fire(
            EVENT_AUTOCITIRE_ERROR,
            {"uan": self._uan, "index": index, "error": str(err)},
        )

    def _citeste_index(self) -> int:
        """Indexul de trimis, din input_number (partea întreagă, ca pe contor)."""
        input_state = self.hass.states.get(self._input_number_entity)
        if not input_state:
            raise HomeAssistantError(
                f"Nu există entitatea {self._input_number_entity}. Creați un "
                f"input_number cu acest ID pentru a putea trimite indexul."
            )
        try:
            return int(float(input_state.state))
        except (TypeError, ValueError) as err:
            raise HomeAssistantError(
                f"Valoare invalidă pentru {self._input_number_entity}: "
                f"'{input_state.state}'."
            ) from err

    async def _async_trimite_index(self, index: int) -> None:
        """Execută trimiterea autocitirii.

        Fluxul (conform APK w0.java):
        1. Obține POD + installation din datele coordinator
        2. Construiește UsageSelfMeterReadEntity din GetPreviousMeterRead
        3. Apelează GetMeterValue (validare)
        4. Apelează SubmitSelfMeterRead (trimitere efectivă)
        """
        index_value = str(index)

        # 1. Extrage POD și installation din pods/previous_meter_read
        data = self.coordinator.data or {}

        pods = data.get("pods") or {}
        pods_data = safe_get(pods, "result", "Data", default={})
        pods_list = _extract_list(pods_data, "objPodData")

        pod_value = ""
        installation_number = ""
        if pods_list:
            pod_info = pods_list[0]
            pod_value = pod_info.get("pod", "")
            installation_number = pod_info.get("installation", "")

        if not pod_value:
            raise HomeAssistantError(
                f"Nu s-a găsit POD-ul contului {self._uan} — trimiterea indexului "
                f"nu este posibilă."
            )

        # 2. Construiește UsageSelfMeterReadEntity
        prev_read = data.get("previous_meter_read") or {}
        prev_data = safe_get(prev_read, "result", "Data", default={})
        read_list = _extract_list(prev_data, "objPreviousMeterReadData")

        if not read_list:
            raise HomeAssistantError(
                f"Nu există date anterioare ale contorului (UAN={self._uan}). "
                f"Verificați dacă fereastra de autocitire este deschisă."
            )

        # Data curentă pentru NewMeterReadDate
        # Format DD/MM/YYYY — confirmat prin debug (SubmitSelfMeterRead 200 OK)
        now_str = datetime.now().strftime("%d/%m/%Y")

        # Construim entitățile de consum (una per registru)
        usage_entities = [
            build_usage_entity(
                previous_read=reading,
                new_meter_read=index_value,
                new_meter_read_date=now_str,
            )
            for reading in read_list
        ]

        user_id = self.coordinator.api_client.user_id or ""
        account_number = self.coordinator.account_number

        _LOGGER.debug(
            "Trimitere autocitire: index=%s, POD=%s, installation=%s (UAN=%s).",
            index_value,
            pod_value,
            installation_number,
            self._uan,
        )

        try:
            # 3. Validare: GetMeterValue
            validate_result = await self.coordinator.api_client.async_get_meter_value(
                user_id=user_id,
                pod_value=pod_value,
                installation_number=installation_number,
                account_number=account_number,
                usage_entity=usage_entities,
            )
            if validate_result is None:
                raise HomeAssistantError(
                    f"Hidroelectrica a respins validarea indexului {index_value} "
                    f"(UAN={self._uan})."
                )

            # 4. Submit: SubmitSelfMeterRead
            submit_result = await self.coordinator.api_client.async_submit_self_meter_read(
                user_id=user_id,
                pod_value=pod_value,
                installation_number=installation_number,
                account_number=account_number,
                usage_entity=usage_entities,
            )
            if submit_result is None:
                raise HomeAssistantError(
                    f"Trimiterea autocitirii a eșuat (UAN={self._uan})."
                )
        except HidroelectricaApiError as err:
            raise HomeAssistantError(
                f"Eroare la comunicarea cu Hidroelectrica: {err}"
            ) from err

        _LOGGER.info(
            "Autocitire trimisă cu succes: index=%s (UAN=%s).",
            index_value,
            self._uan,
        )
