"""ConfigFlow și OptionsFlow pentru integrarea Hidroelectrica România."""

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_USERNAME, CONF_PASSWORD
from .const import DOMAIN, DEFAULT_UPDATE_INTERVAL, CONF_UPDATE_INTERVAL
from .api_manager import ApiManager
import homeassistant.helpers.config_validation as cv


class HidroelectricaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """ConfigFlow pentru integrarea Hidroelectrica."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Primul pas al ConfigFlow: cerem datele utilizatorului."""
        errors = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]

            # Validăm autentificarea
            valid = await self._validate_auth(username, password)
            if valid:
                return self.async_create_entry(
                    title=f"Hidroelectrica  România ({username})",
                    data={
                        CONF_USERNAME: username,
                        CONF_PASSWORD: password,
                        CONF_UPDATE_INTERVAL: user_input.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                        ),
                    },
                )
            errors["base"] = "auth_failed"

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(
                    CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
                ): cv.positive_int,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def _validate_auth(self, username, password):
        """Funcție pentru validarea autentificării."""
        try:
            # AICI e diferența: treci self.hass
            api_manager = ApiManager(self.hass, username, password)
            await api_manager.async_login()
            return True
        except Exception:
            return False

    async def async_step_import(self, import_config):
        """Permite configurarea prin YAML (opțional)."""
        return await self.async_step_user(user_input=import_config)


class HidroelectricaOptionsFlow(config_entries.OptionsFlow):
    """OptionsFlow pentru actualizarea intervalului sau a altor setări."""

    def __init__(self, config_entry):
        """Inițializarea cu valorile existente."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Primul pas al OptionsFlow."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_UPDATE_INTERVAL,
                    default=self.config_entry.options.get(
                        CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
                    ),
                ): cv.positive_int,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
