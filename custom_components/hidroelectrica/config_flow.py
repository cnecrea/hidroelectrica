"""
Flux de configurare pentru integrarea Hidroelectrica România.
"""

import logging
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

# Importăm constantele noastre
from .const import (
    DOMAIN,
    CONF_USERNAME,
    CONF_PASSWORD,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    MAX_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class HidroelectricaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """
    Clasa principală de flux de configurare pentru Hidroelectrica.
    Aceasta este punctul de intrare când utilizatorul adaugă integrarea din UI.
    """

    VERSION = 1  # Versiunea fluxului de configurare

    def __init__(self):
        """
        Constructor simplu. Dacă avem nevoie de variabile temporare,
        le definim aici.
        """
        self._errors = {}

    async def async_step_user(self, user_input=None):
        """
        Primul pas din config flow. Solicită user și parola, precum și update interval.
        
        :param user_input: Datele introduse de utilizator (dicționar)
        :return: Un dicționar care descrie ce afișează Home Assistant (form, create entry etc.)
        """
        self._errors = {}

        # Dacă avem user_input, înseamnă că user-ul a completat formularul
        if user_input is not None:
            # Validăm datele introduse (extrem de simplu aici, doar logăm)
            username = user_input.get(CONF_USERNAME)
            password = user_input.get(CONF_PASSWORD)
            update_interval = user_input.get(CONF_UPDATE_INTERVAL)

            _LOGGER.debug(
                "Utilizator a introdus: user=%s, parola=(ascuns), update_interval=%s",
                username,
                update_interval,
            )

            # Exemplu de pseudo-verificare (în mod real, am putea chema direct API-ul)
            if not username or not password:
                self._errors["base"] = "invalid_auth"
            else:
                # Totul pare OK, creăm intrarea
                return self.async_create_entry(
                    title=f"Hidroelectrica ({username})",
                    data=user_input
                )

        # Dacă nu avem user_input, sau avem erori de validare,
        # construim schema de formular
        return self._show_config_form(user_input)

    def _show_config_form(self, user_input):
        """
        Afișează formularul inițial de configurare.

        :param user_input: Datele reintroduse de utilizator (dacă există erori)
        :return: Configurația ecranului de form
        """
        if not user_input:
            user_input = {
                CONF_USERNAME: "",
                CONF_PASSWORD: "",
                CONF_UPDATE_INTERVAL: DEFAULT_UPDATE_INTERVAL
            }

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=user_input[CONF_USERNAME]): str,
                vol.Required(CONF_PASSWORD, default=user_input[CONF_PASSWORD]): str,
                vol.Required(
                    CONF_UPDATE_INTERVAL,
                    default=user_input[CONF_UPDATE_INTERVAL],
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL),
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=self._errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """
        Metodă statică ce leagă acest config flow de un flux de opțiuni 
        (pentru a modifica setările ulterior).
        """
        return HidroelectricaOptionsFlow(config_entry)


class HidroelectricaOptionsFlow(config_entries.OptionsFlow):
    """
    Clasa care definește fluxul de opțiuni. 
    Aici, utilizatorul poate schimba update_interval după prima configurare.
    """

    def __init__(self, config_entry):
        """
        Constructor ce primește config_entry, pentru a ști ce date avem deja.
        """
        self.config_entry = config_entry
        self._errors = {}

    async def async_step_init(self, user_input=None):
        """
        Pasul inițial pentru opțiuni. Ar putea exista mai mulți pași, 
        dar aici avem doar unul simplu.
        """
        self._errors = {}

        if user_input is not None:
            # Validăm datele
            update_interval = user_input.get(CONF_UPDATE_INTERVAL)
            _LOGGER.debug("Utilizator a modificat update_interval la: %s", update_interval)

            # Putem adăuga validări suplimentare dacă dorim
            return self.async_create_entry(title="", data=user_input)

        # Preluăm datele curente din config_entry, dacă există
        current_interval = self.config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
        
        # Construim schema
        # Folosim "selector" pentru a oferi o experiență mai modernă de selectare a intervalului
        # în UI, dar se poate folosi și vol.Schema la fel ca mai sus.
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=current_interval
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL),
                    )
                }
            ),
            errors=self._errors
        )
