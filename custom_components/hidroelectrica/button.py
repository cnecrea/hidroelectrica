"""Platforma Button pentru Hidroelectrica România — Trimitere autocitire."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
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
        """Execută trimiterea autocitiri.

        Fluxul (conform APK w0.java):
        1. Citește valoarea din input_number
        2. Obține POD + installation din datele coordinator
        3. Construiește UsageSelfMeterReadEntity din GetPreviousMeterRead
        4. Apelează GetMeterValue (validare)
        5. Apelează SubmitSelfMeterRead (trimitere efectivă)
        """
        try:
            # 1. Citește valoarea indexului din input_number
            input_state = self.hass.states.get(self._input_number_entity)
            if not input_state:
                _LOGGER.error(
                    "Nu există entitatea %s. Creați un input_number cu ID-ul "
                    "'%s' pentru a putea trimite indexul (UAN=%s).",
                    self._input_number_entity,
                    self._input_number_entity,
                    self._uan,
                )
                return

            try:
                index_value = str(int(float(input_state.state)))
            except (TypeError, ValueError):
                _LOGGER.error(
                    "Valoare invalidă pentru %s: '%s' (UAN=%s).",
                    self._input_number_entity,
                    input_state.state,
                    self._uan,
                )
                return

            # 2. Extrage POD și installation din pods/previous_meter_read
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
                _LOGGER.error(
                    "Nu s-a găsit POD-ul. Trimiterea nu este posibilă (UAN=%s).",
                    self._uan,
                )
                return

            # 3. Construiește UsageSelfMeterReadEntity
            prev_read = data.get("previous_meter_read") or {}
            prev_data = safe_get(prev_read, "result", "Data", default={})
            read_list = _extract_list(prev_data, "objPreviousMeterReadData")

            if not read_list:
                _LOGGER.error(
                    "Nu există date anterioare ale contorului (UAN=%s). "
                    "Verificați dacă fereastra de autocitire este deschisă.",
                    self._uan,
                )
                return

            # Data curentă pentru NewMeterReadDate
            now_str = datetime.now().strftime("%m/%d/%Y %H:%M:%S")

            # Construim entitățile de consum (una per registru)
            usage_entities = []
            for reading in read_list:
                entity = build_usage_entity(
                    previous_read=reading,
                    new_meter_read=index_value,
                    new_meter_read_date=now_str,
                )
                usage_entities.append(entity)

            user_id = self.coordinator.api_client.user_id or ""
            account_number = self.coordinator.account_number

            _LOGGER.debug(
                "Trimitere autocitire: index=%s, POD=%s, installation=%s (UAN=%s).",
                index_value,
                pod_value,
                installation_number,
                self._uan,
            )

            # 4. Validare: GetMeterValue
            validate_result = await self.coordinator.api_client.async_get_meter_value(
                user_id=user_id,
                pod_value=pod_value,
                installation_number=installation_number,
                account_number=account_number,
                usage_entity=usage_entities,
            )

            if validate_result is None:
                _LOGGER.error(
                    "Validarea indexului a eșuat (UAN=%s).", self._uan
                )
                return

            # 5. Submit: SubmitSelfMeterRead
            submit_result = await self.coordinator.api_client.async_submit_self_meter_read(
                user_id=user_id,
                pod_value=pod_value,
                installation_number=installation_number,
                account_number=account_number,
                usage_entity=usage_entities,
            )

            if submit_result is None:
                _LOGGER.error(
                    "Trimiterea autocitiri a eșuat (UAN=%s).", self._uan
                )
                return

            # 6. Refresh date
            await self.coordinator.async_request_refresh()

            _LOGGER.info(
                "Autocitire trimisă cu succes: index=%s (UAN=%s).",
                index_value,
                self._uan,
            )

        except Exception:
            _LOGGER.exception(
                "Eroare neașteptată la trimiterea autocitiri (UAN=%s).",
                self._uan,
            )
