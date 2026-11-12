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
from homeassistant.config_entries import ConfigEntryState, ConfigFlowResult
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

            session = async_get_clientsession(self.hass)
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

# ── Textele licenței: aceleași în toate integrările hubinteligent (standardizate pe 12.11.2026) ──

_TIP_LICENTA = {
    # Tipurile emise de WebAPI (LICENSE_DURATION)
    "perpetual": ("permanentă", "permanent"),
    "annual": ("anuală", "annual"),
    "semi_annual": ("semestrială", "semi-annual"),
    "monthly": ("lunară", "monthly"),
}


def _tip_licenta(tip: str | None, is_ro: bool) -> str:
    """Eticheta tipului de licență primit de la server."""
    if not tip:
        return "necunoscut" if is_ro else "unknown"
    ro, en = _TIP_LICENTA.get(tip, (tip, tip))
    return ro if is_ro else en


def _zile_ramase(zile: int, is_ro: bool) -> str:
    """„o zi rămasă”, „5 zile rămase”, „20 de zile rămase” — „1 day left”, „5 days left”."""
    if zile <= 0:
        return "ultima zi" if is_ro else "last day"
    if not is_ro:
        return "1 day left" if zile == 1 else f"{zile} days left"
    if zile == 1:
        return "o zi rămasă"
    return f"{zile} {'de ' if zile % 100 >= 20 or zile % 100 == 0 else ''}zile rămase"


def _status_licenta(mgr, is_ro: bool) -> str:
    """Starea licenței, afișată la pasul „Licență”, deasupra câmpului „Cheie de licență”."""
    from homeassistant.util import dt as dt_util

    def data(moment: float) -> str:
        return dt_util.as_local(dt_util.utc_from_timestamp(moment)).strftime("%d.%m.%Y")

    obtine = f"🛒 {'Obține o licență' if is_ro else 'Get a license'}: {LICENSE_PURCHASE_URL}"
    if mgr.status == "licensed":
        linii = [f"✅ {'Licență activă' if is_ro else 'Active license'} ({_tip_licenta(mgr.license_type, is_ro)})"]
        if mgr.license_key_masked:
            linii[0] += f" — {mgr.license_key_masked}"
        if mgr.activated_at:
            linii.append(f"{'Activată la' if is_ro else 'Activated on'}: {data(mgr.activated_at)}")
        if mgr.license_expires_at:
            linii.append(f"📅 {'Expiră la' if is_ro else 'Expires on'}: {data(mgr.license_expires_at)}")
        else:
            linii.append("Valabilitate: nelimitată" if is_ro else "Validity: unlimited")
        return "\n".join(linii)
    if mgr.status == "trial":
        perioada = "Perioadă de test" if is_ro else "Free trial"
        return "\n".join([f"⏳ {perioada}: {_zile_ramase(mgr.trial_days_remaining, is_ro)}", "", obtine])
    if mgr.status == "expired" and mgr.has_license:
        linii = ["❌ Licență expirată" if is_ro else "❌ License expired"]
        if mgr.license_expires_at:
            linii.append(f"{'Expirată la' if is_ro else 'Expired on'}: {data(mgr.license_expires_at)}")
        return "\n".join([*linii, "", obtine])
    if mgr.status == "expired":
        return "\n".join(["❌ Perioada de test s-a încheiat" if is_ro else "❌ The free trial has ended", "", obtine])
    stare = "❌ Fără licență: senzorii nu se actualizează." if is_ro else "❌ No license: sensors do not update."
    return "\n".join([stare, "", obtine])


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

            conflict = any(
                e.entry_id != self.config_entry.entry_id
                and e.unique_id == username.lower()
                for e in self.hass.config_entries.async_entries(DOMAIN)
            )
            if conflict:
                # Contul e deja configurat într-o altă intrare
                errors["base"] = "already_configured"
            else:
                session = async_get_clientsession(self.hass)
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

                # Listener-ul de update reîncarcă intrarea o singură dată, doar
                # dacă s-a schimbat ceva (înainte: update + reload explicit = 2 reload-uri).
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
                    title=f"Hidroelectrica ({self._username})",
                    unique_id=self._username.lower(),
                )
                if self.config_entry.state in (
                    ConfigEntryState.SETUP_RETRY,
                    ConfigEntryState.SETUP_ERROR,
                ):
                    # Intrarea nu rulează (ex: parolă greșită) → listener-ul de
                    # update nu e activ; reîncercăm imediat cu noile date.
                    self.hass.config_entries.async_schedule_reload(
                        self.config_entry.entry_id
                    )

                return self.async_create_entry(data=dict(self.config_entry.options))

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

        description_placeholders["license_status"] = _status_licenta(mgr, is_ro)

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
                        f"Licența Hidroelectrica este activă ({_tip_licenta(mgr.license_type, True)}).",
                        title="Licență activată",
                        notification_id="hidroelectrica_license_activated",
                    )
                    return self.async_create_entry(
                        data=self.config_entry.options
                    )

                # Mapare erori API (codurile WebAPI /activate + erorile locale)
                api_error = result.get("error", "unknown_error")
                error_map = {
                    "invalid_key": "license_key_invalid",
                    "already_used": "license_already_used",
                    "expired_key": "license_key_expired",
                    "fingerprint_mismatch": "license_fingerprint_mismatch",
                    "network_error": "license_network_error",
                    "http_502": "license_network_error",
                    "http_503": "license_network_error",  # server temporar ocupat
                    "http_504": "license_network_error",
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
