"""ConfigFlow și OptionsFlow pentru integrarea Hidroelectrica România.

Fluxul de configurare:
  1. Utilizatorul introduce email + parolă  (+ update interval)
  2. Se validează credențialele prin API (login real)
  3. Se descoperă automat conturile (GetUserSetting)
  4. Utilizatorul selectează conturile dorite

OptionsFlow:
  - Meniu principal cu: Setări cont / Licență
  - Setări: modificare credențiale + interval + selecție conturi
  - Licență: activare / vizualizare licență (1:1 cu fleet)
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import selector
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import HidroelectricaApiClient, HidroelectricaAuthError
from .const import (
    CONF_ACCOUNT_METADATA,
    CONF_LICENSE_KEY,
    CONF_PASSWORD,
    CONF_SELECTED_ACCOUNTS,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    DOMAIN_TOKEN_STORE,
    LICENSE_DATA_KEY,
    LICENSE_PURCHASE_URL,
    MIN_UPDATE_INTERVAL,
    MAX_UPDATE_INTERVAL,
)
from .helpers import (
    build_account_metadata,
    build_account_options,
    resolve_selection,
)

_LOGGER = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Helpers comune
# ──────────────────────────────────────────────

async def _fetch_accounts_after_login(
    api: HidroelectricaApiClient,
) -> list[dict] | None:
    """Obține lista de conturi după autentificare reușită."""
    accounts = await api.async_fetch_utility_accounts()
    if accounts and isinstance(accounts, list) and len(accounts) > 0:
        return accounts
    return None


def _store_token(hass, username: str, api: HidroelectricaApiClient) -> None:
    """Salvează token-ul API în hass.data (per username)."""
    token_data = api.export_token_data()
    if token_data is None:
        return
    store = hass.data.setdefault(DOMAIN_TOKEN_STORE, {})
    store[username.lower()] = token_data
    _LOGGER.debug(
        "Token salvat în hass.data pentru %s.",
        username,
    )


# ──────────────────────────────────────────────
# ConfigFlow
# ──────────────────────────────────────────────

class HidroelectricaConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """ConfigFlow — autentificare + selecție conturi."""

    VERSION = 3

    def __init__(self) -> None:
        self._username: str = ""
        self._password: str = ""
        self._update_interval: int = DEFAULT_UPDATE_INTERVAL
        self._accounts_raw: list[dict] = []
        self._api: HidroelectricaApiClient | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pasul 1: Autentificare."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._username = user_input[CONF_USERNAME]
            self._password = user_input[CONF_PASSWORD]
            self._update_interval = user_input.get(
                CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
            )

            # Unicitate per username
            await self.async_set_unique_id(self._username.lower())
            self._abort_if_unique_id_configured()

            session = async_get_clientsession(self.hass, verify_ssl=False)
            self._api = HidroelectricaApiClient(
                session, self._username, self._password
            )

            try:
                await self._api.async_login()
                # Login reușit — salvăm token-ul
                _store_token(self.hass, self._username, self._api)

                accounts = await _fetch_accounts_after_login(self._api)
                if accounts:
                    self._accounts_raw = accounts
                    return await self.async_step_select_accounts()

                errors["base"] = "no_data"
                _LOGGER.warning(
                    "Login reușit dar nu s-au găsit conturi (%s).",
                    self._username,
                )

            except HidroelectricaAuthError:
                errors["base"] = "auth_failed"
            except Exception:
                _LOGGER.exception("Eroare neașteptată la autentificare.")
                errors["base"] = "unknown"

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(
                    CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL),
                ),
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    async def async_step_select_accounts(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pasul 2: Selectare conturi din lista descoperită."""
        errors: dict[str, str] = {}

        if user_input is not None:
            select_all = user_input.get("select_all", False)
            selected = user_input.get(CONF_SELECTED_ACCOUNTS, [])

            if not select_all and not selected:
                errors["base"] = "no_account_selected"
            else:
                final_selection = resolve_selection(
                    select_all, selected, self._accounts_raw
                )

                return self.async_create_entry(
                    title=f"Hidroelectrica ({self._username})",
                    data={
                        CONF_USERNAME: self._username,
                        CONF_PASSWORD: self._password,
                        CONF_UPDATE_INTERVAL: self._update_interval,
                        "select_all": select_all,
                        CONF_SELECTED_ACCOUNTS: final_selection,
                        CONF_ACCOUNT_METADATA: build_account_metadata(
                            self._accounts_raw
                        ),
                    },
                )

        account_options = build_account_options(self._accounts_raw)

        schema = vol.Schema(
            {
                vol.Optional("select_all", default=False): bool,
                vol.Required(
                    CONF_SELECTED_ACCOUNTS, default=[]
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=account_options,
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="select_accounts",
            data_schema=schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HidroelectricaOptionsFlow:
        return HidroelectricaOptionsFlow()


# ──────────────────────────────────────────────
# OptionsFlow
# ──────────────────────────────────────────────

class HidroelectricaOptionsFlow(config_entries.OptionsFlow):
    """OptionsFlow — meniu cu setări cont și licențiere."""

    def __init__(self) -> None:
        self._username: str = ""
        self._password: str = ""
        self._update_interval: int = DEFAULT_UPDATE_INTERVAL
        self._accounts_raw: list[dict] = []
        self._api: HidroelectricaApiClient | None = None

    # ─────────────────────────────────────────
    # Meniu principal
    # ─────────────────────────────────────────
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Afișează meniul principal cu opțiunile disponibile."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "setari",
                "licenta",
            ],
        )

    # ─────────────────────────────────────────
    # Setări cont (credențiale + interval + conturi)
    # ─────────────────────────────────────────
    async def async_step_setari(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Modificare credențiale și interval de actualizare."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME]
            password = user_input[CONF_PASSWORD]
            update_interval = user_input.get(
                CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
            )

            session = async_get_clientsession(self.hass, verify_ssl=False)
            self._api = HidroelectricaApiClient(session, username, password)

            try:
                await self._api.async_login()
                _store_token(self.hass, username, self._api)

                accounts = await _fetch_accounts_after_login(self._api)
                if accounts:
                    self._accounts_raw = accounts
                    self._username = username
                    self._password = password
                    self._update_interval = update_interval
                    return await self.async_step_select_accounts()
                errors["base"] = "no_data"

            except HidroelectricaAuthError:
                errors["base"] = "auth_failed"
            except Exception:
                _LOGGER.exception("Eroare neașteptată la autentificare.")
                errors["base"] = "unknown"

        current = self.config_entry.data

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_USERNAME, default=current.get(CONF_USERNAME, "")
                ): str,
                vol.Required(
                    CONF_PASSWORD, default=current.get(CONF_PASSWORD, "")
                ): str,
                vol.Required(
                    CONF_UPDATE_INTERVAL,
                    default=current.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
                ): vol.All(
                    vol.Coerce(int),
                    vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL),
                ),
            }
        )

        return self.async_show_form(
            step_id="setari", data_schema=schema, errors=errors
        )

    async def async_step_select_accounts(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Modificare selecție conturi."""
        errors: dict[str, str] = {}

        if user_input is not None:
            select_all = user_input.get("select_all", False)
            selected = user_input.get(CONF_SELECTED_ACCOUNTS, [])

            if not select_all and not selected:
                errors["base"] = "no_account_selected"
            else:
                final_selection = resolve_selection(
                    select_all, selected, self._accounts_raw
                )

                self.hass.config_entries.async_update_entry(
                    self.config_entry,
                    data={
                        CONF_USERNAME: self._username,
                        CONF_PASSWORD: self._password,
                        CONF_UPDATE_INTERVAL: self._update_interval,
                        "select_all": select_all,
                        CONF_SELECTED_ACCOUNTS: final_selection,
                        CONF_ACCOUNT_METADATA: build_account_metadata(
                            self._accounts_raw
                        ),
                    },
                )

                await self.hass.config_entries.async_reload(
                    self.config_entry.entry_id
                )

                return self.async_create_entry(data={})

        current = self.config_entry.data

        schema = vol.Schema(
            {
                vol.Optional(
                    "select_all",
                    default=current.get("select_all", False),
                ): bool,
                vol.Required(
                    CONF_SELECTED_ACCOUNTS,
                    default=current.get(CONF_SELECTED_ACCOUNTS, []),
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=build_account_options(self._accounts_raw),
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="select_accounts",
            data_schema=schema,
            errors=errors,
        )

    # ─────────────────────────────────────────
    # Licențiere
    # ─────────────────────────────────────────
    async def async_step_licenta(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Formular pentru activarea / vizualizarea licenței Hidroelectrica."""
        from .license import LicenseManager

        errors: dict[str, str] = {}
        description_placeholders: dict[str, str] = {}

        is_ro = self.hass.config.language == "ro"

        # Obține LicenseManager
        mgr: LicenseManager | None = self.hass.data.get(DOMAIN, {}).get(
            LICENSE_DATA_KEY
        )
        if mgr is None:
            mgr = LicenseManager(self.hass)
            await mgr.async_load()

        # Informații pentru descrierea formularului
        server_status = mgr.status  # 'licensed', 'trial', 'expired', 'unlicensed'

        if server_status == "licensed":
            from datetime import datetime

            tip = mgr.license_type or "necunoscut"
            status_lines = [f"✅ Licență activă ({tip})"]

            if mgr.license_key_masked:
                status_lines[0] += f" — {mgr.license_key_masked}"

            # Data activării
            if mgr.activated_at:
                act_date = datetime.fromtimestamp(
                    mgr.activated_at
                ).strftime("%d.%m.%Y %H:%M")
                status_lines.append(f"Activată la: {act_date}")

            # Data expirării
            if mgr.license_expires_at:
                exp_date = datetime.fromtimestamp(
                    mgr.license_expires_at
                ).strftime("%d.%m.%Y %H:%M")
                status_lines.append(f"📅 Expiră la: {exp_date}")
            elif tip == "perpetual":
                status_lines.append("Valabilitate: nelimitată (perpetuă)")

            description_placeholders["license_status"] = "\n".join(
                status_lines
            )

        elif server_status == "trial":
            days = mgr.trial_days_remaining
            if is_ro:
                status_lines = [
                    f"⏳ Evaluare — {days} zile rămase",
                    "",
                    f"🛒 Obține licență: {LICENSE_PURCHASE_URL}",
                ]
            else:
                status_lines = [
                    f"⏳ Trial — {days} days remaining",
                    "",
                    f"🛒 Get a license: {LICENSE_PURCHASE_URL}",
                ]
            description_placeholders["license_status"] = "\n".join(status_lines)
        elif server_status == "expired":
            from datetime import datetime

            status_lines = ["❌ Licență expirată"]

            if mgr.activated_at:
                act_date = datetime.fromtimestamp(
                    mgr.activated_at
                ).strftime("%d.%m.%Y")
                status_lines.append(f"Activată la: {act_date}")
            if mgr.license_expires_at:
                exp_date = datetime.fromtimestamp(
                    mgr.license_expires_at
                ).strftime("%d.%m.%Y")
                status_lines.append(f"Expirată la: {exp_date}")

            status_lines.append("")
            if is_ro:
                status_lines.append(
                    f"🛒 Obține licență: {LICENSE_PURCHASE_URL}"
                )
            else:
                status_lines.append(
                    f"🛒 Get a license: {LICENSE_PURCHASE_URL}"
                )

            description_placeholders["license_status"] = "\n".join(
                status_lines
            )
        else:
            if is_ro:
                status_lines = [
                    "❌ Fără licență — funcționalitate blocată",
                    "",
                    f"🛒 Obține licență: {LICENSE_PURCHASE_URL}",
                ]
            else:
                status_lines = [
                    "❌ No license — functionality blocked",
                    "",
                    f"🛒 Get a license: {LICENSE_PURCHASE_URL}",
                ]
            description_placeholders["license_status"] = "\n".join(status_lines)

        if user_input is not None:
            cheie = user_input.get(CONF_LICENSE_KEY, "").strip()

            if not cheie:
                errors["base"] = "license_key_empty"
            elif len(cheie) < 10:
                errors["base"] = "license_key_invalid"
            else:
                # Activare prin API
                result = await mgr.async_activate(cheie)

                if result.get("success"):
                    # Notificare de succes
                    from homeassistant.components import (
                        persistent_notification,
                    )

                    persistent_notification.async_create(
                        self.hass,
                        f"Licența Hidroelectrica a fost activată cu succes! "
                        f"Tip: {mgr.license_type or 'necunoscut'}.",
                        title="Licență activată",
                        notification_id="hidroelectrica_license_activated",
                    )
                    return self.async_create_entry(
                        data=self.config_entry.options
                    )

                # Mapare erori API
                api_error = result.get("error", "unknown_error")
                error_map = {
                    "invalid_key": "license_key_invalid",
                    "already_used": "license_already_used",
                    "expired_key": "license_key_expired",
                    "fingerprint_mismatch": "license_fingerprint_mismatch",
                    "invalid_signature": "license_server_error",
                    "network_error": "license_network_error",
                    "server_error": "license_server_error",
                }
                errors["base"] = error_map.get(api_error, "license_server_error")

        schema = vol.Schema(
            {
                vol.Optional(CONF_LICENSE_KEY): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.TEXT,
                        suffix="HDEL-XXXX-XXXX-XXXX",
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="licenta",
            data_schema=schema,
            errors=errors,
            description_placeholders=description_placeholders,
        )
