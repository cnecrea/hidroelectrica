import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN
from .coordinator import HidroelectricaCoordinator

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    _LOGGER.debug("Executăm async_setup pentru Hidroelectrica: nimic special de făcut aici.")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug("Inițiem integrarea Hidroelectrica pentru entry: %s", entry.title)

    # Asigurăm un dict global
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}

    # 1. Creăm coordinator
    coordinator = HidroelectricaCoordinator(hass, entry)

    # 2. Salvăm coordinatorul
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator
    }

    # 3. Facem primul refresh (blocant până când datele se obțin sau apare eroare)
    await coordinator.async_config_entry_first_refresh()

    # 4. Forward la platforma sensor
    await hass.config_entries.async_forward_entry_setups(entry, ["sensor"])

    _LOGGER.debug("Hidroelectrica - Setup entry finalizat cu succes.")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.debug("Descărcăm entry-ul Hidroelectrica pentru entry_id: %s", entry.entry_id)
    unload_ok = await hass.config_entries.async_unload_platforms(entry, ["sensor"])
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok
