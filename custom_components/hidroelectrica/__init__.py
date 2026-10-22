"""Inițializarea integrării Hidroelectrica România."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.components import persistent_notification
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later

from .api import HidroelectricaApiClient, HidroelectricaApiError, HidroelectricaAuthError
from .const import (
    CONF_ACCOUNT_METADATA,
    CONF_PASSWORD,
    CONF_SELECTED_ACCOUNTS,
    CONF_UPDATE_INTERVAL,
    CONF_USERNAME,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    DOMAIN_TOKEN_STORE,
    LICENSE_DATA_KEY,
    LICENSE_PURCHASE_URL,
    PLATFORMS,
)
from .coordinator import HidroelectricaCoordinator
from .helpers import build_account_metadata, extract_all_accounts
from .license import LicenseManager

_LOGGER = logging.getLogger(__name__)

# Stările în care o intrare încă folosește managerul de licențe
_STARI_ACTIVE = (
    ConfigEntryState.LOADED,
    ConfigEntryState.SETUP_IN_PROGRESS,
    ConfigEntryState.SETUP_RETRY,
    ConfigEntryState.UNLOAD_IN_PROGRESS,
)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class HidroelectricaRuntimeData:
    """Structură tipizată pentru datele runtime ale integrării."""

    coordinators: dict[str, HidroelectricaCoordinator] = field(default_factory=dict)
    api_client: HidroelectricaApiClient | None = None
    # Configurația (fără token-ul SEW) la momentul setup-ului — vezi _async_update_options
    config_signature: str = ""


def _config_signature(entry: ConfigEntry) -> str:
    """Amprenta configurației care contează pentru reload.

    `token_data` e exclus: coordinatorul salvează token-ul SEW în entry.data
    după fiecare re-login, iar asta NU trebuie să reîncarce integrarea.
    """
    data = {k: v for k, v in entry.data.items() if k != "token_data"}
    return json.dumps([data, dict(entry.options)], sort_keys=True, default=str)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Configurează integrarea globală Hidroelectrica România."""
    _LOGGER.debug("Inițializare globală integrare: %s", DOMAIN)
    return True



def _update_license_notifications(hass: HomeAssistant, mgr: LicenseManager) -> None:
    """Creează sau șterge notificările de expirare licență/trial."""
    if mgr.is_valid:
        ir.async_delete_issue(hass, DOMAIN, "trial_expired")
        ir.async_delete_issue(hass, DOMAIN, "license_expired")
        persistent_notification.async_dismiss(hass, "hidroelectrica_license_expired")
        return

    if mgr.has_license:
        issue_id = "license_expired"
        notif_title = "Hidroelectrica România — Licența a expirat"
        notif_message = (
            "Licența pentru integrarea **Hidroelectrica România** a expirat.\n\n"
            "Senzorii sunt dezactivați până la reînnoirea licenței.\n\n"
            f"[Reînnoiește licența]({LICENSE_PURCHASE_URL})"
        )
    else:
        issue_id = "trial_expired"
        notif_title = "Hidroelectrica România — Licența de probă a expirat"
        notif_message = (
            "Perioada de evaluare gratuită pentru integrarea **Hidroelectrica România** s-a încheiat.\n\n"
            "Senzorii sunt dezactivați până la obținerea unei licențe.\n\n"
            f"[Obține o licență acum]({LICENSE_PURCHASE_URL})"
        )

    other_id = "license_expired" if issue_id == "trial_expired" else "trial_expired"
    ir.async_delete_issue(hass, DOMAIN, other_id)

    ir.async_create_issue(
        hass,
        DOMAIN,
        issue_id,
        is_fixable=False,
        is_persistent=True,
        learn_more_url=LICENSE_PURCHASE_URL,
        severity=ir.IssueSeverity.WARNING,
        translation_key=issue_id,
        translation_placeholders={"learn_more_url": LICENSE_PURCHASE_URL},
    )

    persistent_notification.async_create(
        hass,
        notif_message,
        title=notif_title,
        notification_id="hidroelectrica_license_expired",
    )

    _LOGGER.debug("[Hidroelectrica] Notificare expirare creată: %s", issue_id)


def _cleanup_domain(hass: HomeAssistant) -> None:
    """Oprește verificarea licenței și eliberează datele domeniului."""
    domain_data = hass.data.pop(DOMAIN, None) or {}
    cancel_check = domain_data.pop("_cancel_license_check", None)
    if cancel_check:
        cancel_check()


def _schedule_license_check(hass: HomeAssistant, mgr: LicenseManager) -> None:
    """Programează următoarea verificare a licenței (un singur timer, reprogramat mereu).

    Momentul vine de la server: imediat după `valid_until`, sau cu backoff
    (60s → 1h) cât timp serverul nu răspunde. La fiecare verificare: /check
    (+ /validate pentru licențe); dacă validitatea s-a schimbat → notificări
    actualizate + reload.
    """
    if hass.is_stopping:
        return  # la oprire sesiunea HTTP se închide — nu mai verificăm
    domain_data = hass.data.get(DOMAIN)
    if domain_data is None or domain_data.get(LICENSE_DATA_KEY) is not mgr:
        return
    cancel_prev = domain_data.pop("_cancel_license_check", None)
    if cancel_prev:
        cancel_prev()

    delay = mgr.check_interval_seconds + (2 if not mgr.needs_heartbeat else 0)

    async def _async_check() -> None:
        try:
            was_valid = mgr.is_valid
            if mgr.needs_heartbeat:
                await mgr.async_heartbeat()
            now_valid = mgr.is_valid
            if hass.data.get(DOMAIN, {}).get(LICENSE_DATA_KEY) is not mgr:
                return  # integrarea a fost descărcată în timpul verificării
            if was_valid != now_valid:
                if now_valid:
                    _LOGGER.info("[Hidroelectrica] Licența a redevenit validă — reîncarc")
                else:
                    _LOGGER.warning("[Hidroelectrica] Licența a devenit invalidă — reîncarc")
                _update_license_notifications(hass, mgr)
                await mgr._async_reload_entries()
        except Exception:  # noqa: BLE001 — timer-ul nu trebuie să se oprească
            _LOGGER.exception("[Hidroelectrica] Eroare la verificarea periodică a licenței")
        finally:
            _schedule_license_check(hass, mgr)

    @callback
    def _on_timer(_now) -> None:
        domain_now = hass.data.get(DOMAIN, {})
        domain_now.pop("_cancel_license_check", None)
        if hass.is_stopping or domain_now.get(LICENSE_DATA_KEY) is not mgr:
            return
        if not any(
            e.state in _STARI_ACTIVE for e in hass.config_entries.async_entries(DOMAIN)
        ):
            # Ex: intrare dezactivată cât era în „setup retry" (HA nu apelează unload)
            _cleanup_domain(hass)
            return
        # Task de fundal: pornirea/oprirea Home Assistant nu așteaptă
        # niciodată serverul de licențe (issue #329).
        hass.async_create_background_task(
            _async_check(), f"{DOMAIN}_license_check"
        )

    domain_data["_cancel_license_check"] = async_call_later(hass, delay, _on_timer)


async def _async_discover_accounts(
    hass: HomeAssistant, entry: ConfigEntry, api_client: HidroelectricaApiClient
) -> list[str]:
    """Descoperă conturile (UAN) pentru o intrare fără selecție și le salvează."""
    try:
        await api_client.async_ensure_authenticated()
        accounts = await api_client.async_fetch_utility_accounts()
    except HidroelectricaAuthError as err:
        raise ConfigEntryNotReady(f"Autentificare Hidroelectrica eșuată: {err}") from err
    except HidroelectricaApiError as err:
        raise ConfigEntryNotReady(f"Conturile Hidroelectrica nu pot fi obținute: {err}") from err

    selected = extract_all_accounts(accounts)
    if not selected:
        raise ConfigEntryNotReady("Hidroelectrica nu a returnat niciun cont.")

    _LOGGER.warning(
        "Intrarea %s nu avea conturi selectate — se monitorizează toate cele %d "
        "conturi găsite (se pot modifica din Opțiuni → Setări cont).",
        entry.entry_id,
        len(selected),
    )
    hass.config_entries.async_update_entry(
        entry,
        data={
            **entry.data,
            "select_all": True,
            CONF_SELECTED_ACCOUNTS: selected,
            CONF_ACCOUNT_METADATA: build_account_metadata(accounts),
        },
    )
    return selected


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configurează integrarea pentru o intrare specifică (config entry)."""
    _LOGGER.info(
        "Se configurează integrarea %s (entry_id=%s).",
        DOMAIN,
        entry.entry_id,
    )

    hass.data.setdefault(DOMAIN, {})

    # ── Inițializare License Manager (o singură instanță per domeniu) ──
    if LICENSE_DATA_KEY not in hass.data[DOMAIN]:
        license_mgr = LicenseManager(hass)
        # Referința se setează ÎNAINTE de async_load(): async_load() face await HTTP,
        # iar intrările configurate în paralel nu trebuie să creeze manageri duplicați.
        hass.data[DOMAIN][LICENSE_DATA_KEY] = license_mgr
        try:
            await license_mgr.async_load()
        except Exception:
            hass.data[DOMAIN].pop(LICENSE_DATA_KEY, None)
            raise
        _LOGGER.debug(
            "[Hidroelectrica] LicenseManager: status=%s, valid=%s, fingerprint=%s...",
            license_mgr.status,
            license_mgr.is_valid,
            license_mgr.fingerprint[:16],
        )
        _schedule_license_check(hass, license_mgr)

        # ── Notificare re-enable (dacă a fost dezactivată anterior) ──
        if hass.data.pop(f"{DOMAIN}_was_disabled", False):
            await license_mgr.async_notify_event("integration_enabled")

        if not license_mgr.is_valid:
            _LOGGER.warning(
                "[Hidroelectrica] Integrarea nu are licență validă. "
                "Senzorii vor afișa 'Licență necesară'."
            )
        elif license_mgr.is_trial_valid:
            _LOGGER.info(
                "[Hidroelectrica] Perioadă de evaluare — %d zile rămase",
                license_mgr.trial_days_remaining,
            )
        else:
            _LOGGER.info(
                "[Hidroelectrica] Licență activă — tip: %s",
                license_mgr.license_type,
            )

    license_mgr = hass.data[DOMAIN][LICENSE_DATA_KEY]
    # La FIECARE setup — după activare, reload-ul intrărilor șterge notificările
    # chiar dacă managerul de licențe rămâne același (mai multe conturi).
    _update_license_notifications(hass, license_mgr)

    session = async_get_clientsession(hass)
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    update_interval = entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)

    # Un singur client API partajat (un singur cont, un singur token)
    api_client = HidroelectricaApiClient(session, username, password)

    # Injectăm token-ul salvat:
    # 1. hass.data (proaspăt, de la config_flow)
    # 2. config_entry.data (persistent, pentru restart HA)
    token_store = hass.data.get(DOMAIN_TOKEN_STORE, {})
    stored_token = token_store.pop(username.lower(), None)
    if stored_token:
        api_client.inject_token(stored_token)
        _LOGGER.debug(
            "Token injectat din config_flow pentru %s.", username
        )
    elif entry.data.get("token_data"):
        api_client.inject_token(entry.data["token_data"])
        _LOGGER.debug(
            "Token injectat din config_entry.data pentru %s.", username
        )
    else:
        _LOGGER.debug(
            "Niciun token salvat. Se va face login la primul refresh (%s).",
            username,
        )

    # Curățăm store-ul dacă e gol
    if DOMAIN_TOKEN_STORE in hass.data and not hass.data[DOMAIN_TOKEN_STORE]:
        hass.data.pop(DOMAIN_TOKEN_STORE, None)

    # Conturi selectate
    selected_accounts = entry.data.get(CONF_SELECTED_ACCOUNTS, [])
    if not selected_accounts:
        # Intrare migrată de la v1/v2 (fără selecție) — înainte rămânea picată
        # definitiv; acum se descoperă conturile și se monitorizează toate.
        selected_accounts = await _async_discover_accounts(hass, entry, api_client)

    _LOGGER.debug(
        "Conturi selectate pentru %s (entry_id=%s): %s, interval=%ss.",
        DOMAIN,
        entry.entry_id,
        selected_accounts,
        update_interval,
    )

    # Metadatele conturilor
    account_metadata = entry.data.get(CONF_ACCOUNT_METADATA, {})

    _LOGGER.debug(
        "account_metadata pentru entry_id=%s: %s",
        entry.entry_id,
        {k: {mk: mv for mk, mv in v.items() if mk in ("accountNumber", "pod")}
         for k, v in account_metadata.items()} if account_metadata else "GOL",
    )

    # Fallback: dacă metadata nu conține accountNumber (config entry vechi),
    # obținem conturile din API pentru a completa
    acc_number_map: dict[str, str] = {}
    for uan_key, meta_val in account_metadata.items():
        if meta_val.get("accountNumber"):
            acc_number_map[uan_key] = meta_val["accountNumber"]

    if selected_accounts and not acc_number_map:
        _LOGGER.debug(
            "Metadata nu conține accountNumber. Se obțin conturile din API."
        )
        try:
            await api_client.async_ensure_authenticated()
            fresh_accounts = await api_client.async_fetch_utility_accounts()
            for fa in fresh_accounts:
                fa_uan = fa.get("contractAccountID", "").strip()
                fa_acc = fa.get("accountNumber", "").strip()
                if fa_uan and fa_acc:
                    acc_number_map[fa_uan] = fa_acc
        except Exception as err:
            _LOGGER.warning(
                "Nu s-au putut obține conturile din API pentru fallback: %s", err
            )

    # Creăm câte un coordinator per cont selectat
    coordinators: dict[str, HidroelectricaCoordinator] = {}
    first_error: Exception | None = None

    for uan in selected_accounts:
        meta = account_metadata.get(uan, {})
        acc_number = meta.get("accountNumber", "") or acc_number_map.get(uan, "")

        _LOGGER.info(
            "Coordinator UAN=%s: AccountNumber='%s' "
            "(sursa=%s).",
            uan,
            acc_number,
            "metadata" if meta.get("accountNumber") else
            ("api_fallback" if acc_number_map.get(uan) else "GOL!"),
        )

        coordinator = HidroelectricaCoordinator(
            hass,
            api_client=api_client,
            uan=uan,
            account_number=acc_number,
            update_interval=update_interval,
            config_entry=entry,
        )

        try:
            await coordinator.async_config_entry_first_refresh()
        except ConfigEntryNotReady as err:
            # Un cont cu probleme nu blochează celelalte conturi
            _LOGGER.error(
                "Prima actualizare eșuată (entry_id=%s, UAN=%s): %s",
                entry.entry_id,
                uan,
                err,
            )
            first_error = first_error or err
            continue

        coordinators[uan] = coordinator

    if not coordinators:
        # Serverul Hidroelectrica nu răspunde (sau nu răspundea la pornire):
        # HA reîncearcă automat (înainte: return False = integrare picată
        # până la reload manual).
        raise ConfigEntryNotReady(
            f"Niciun cont Hidroelectrica nu a putut fi actualizat: {first_error}"
        ) from first_error

    _LOGGER.info(
        "%s coordinatoare active din %s conturi selectate (entry_id=%s).",
        len(coordinators),
        len(selected_accounts),
        entry.entry_id,
    )

    # Salvăm datele runtime
    entry.runtime_data = HidroelectricaRuntimeData(
        coordinators=coordinators,
        api_client=api_client,
        config_signature=_config_signature(entry),
    )

    # Încărcăm platformele (sensor + button)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Listener pentru modificarea opțiunilor
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    _LOGGER.info(
        "Integrarea %s configurată (entry_id=%s, conturi=%s).",
        DOMAIN,
        entry.entry_id,
        list(coordinators.keys()),
    )
    return True


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reîncarcă integrarea când configurația s-a schimbat efectiv.

    Listener-ul e apelat la ORICE actualizare a intrării — inclusiv când
    coordinatorul salvează token-ul SEW după un re-login. Acelea sunt ignorate
    (înainte: fiecare re-login reîncărca integrarea și refăcea toate cererile).
    """
    runtime = getattr(entry, "runtime_data", None)
    if runtime is not None and runtime.config_signature == _config_signature(entry):
        return
    _LOGGER.info(
        "Opțiunile integrării %s s-au schimbat (entry_id=%s). Se reîncarcă...",
        DOMAIN,
        entry.entry_id,
    )
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Descărcarea integrării."""
    _LOGGER.info(
        "Se descarcă integrarea %s (entry_id=%s).", DOMAIN, entry.entry_id
    )

    ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if ok:
        # Doar intrările ACTIVE contează (cele dezactivate / descărcate nu folosesc
        # managerul de licențe — altfel acesta și timer-ul nu s-ar opri niciodată).
        entry_ids_ramase = [
            e.entry_id
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id and e.state in _STARI_ACTIVE
        ]

        _LOGGER.debug(
            "[Hidroelectrica] Entry-uri active rămase după unload: %d (%s)",
            len(entry_ids_ramase),
            entry_ids_ramase or "niciuna",
        )

        if not entry_ids_ramase:
            _LOGGER.info("[Hidroelectrica] Ultima entry descărcată — curăț domeniul complet")

            # ── Notificare lifecycle (înainte de cleanup!) ──
            mgr = hass.data.get(DOMAIN, {}).get(LICENSE_DATA_KEY)
            if mgr and not hass.is_stopping:
                if entry.disabled_by:
                    await mgr.async_notify_event("integration_disabled")
                    # Flag pentru async_setup_entry: la re-enable, trimitem "enabled"
                    hass.data[f"{DOMAIN}_was_disabled"] = True
                else:
                    # Salvăm fingerprint-ul pentru async_remove_entry
                    # (care se apelează DUPĂ ce LicenseManager e distrus)
                    hass.data.setdefault(f"{DOMAIN}_notify", {}).update({
                        "fingerprint": mgr.fingerprint,
                        "license_key": mgr._data.get("license_key", ""),
                    })

            _cleanup_domain(hass)
            _LOGGER.info("[Hidroelectrica] Cleanup complet — domeniul %s descărcat", DOMAIN)
    else:
        _LOGGER.warning(
            "Integrarea %s nu a putut fi descărcată complet (entry_id=%s).",
            DOMAIN,
            entry.entry_id,
        )
    return ok


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Curăță complet la ștergerea integrării.

    Notifică serverul cu 'integration_removed' dacă e ultima entry.
    """
    _LOGGER.debug(
        "[Hidroelectrica] ── async_remove_entry ── entry_id=%s",
        entry.entry_id,
    )

    # ── Notificare „integration_removed" dacă e ultima intrare ──
    # LicenseManager nu mai există (distrus în async_unload_entry),
    # dar fingerprint-ul a fost salvat în hass.data[f"{DOMAIN}_notify"].
    remaining = hass.config_entries.async_entries(DOMAIN)
    if not remaining:
        # O intrare ștearsă cât era în „setup retry" nu trece prin async_unload_entry
        if DOMAIN in hass.data:
            mgr = hass.data[DOMAIN].get(LICENSE_DATA_KEY)
            if mgr is not None and f"{DOMAIN}_notify" not in hass.data:
                hass.data[f"{DOMAIN}_notify"] = {
                    "fingerprint": mgr.fingerprint,
                    "license_key": mgr._data.get("license_key", ""),
                }
            _cleanup_domain(hass)
        notify_data = hass.data.pop(f"{DOMAIN}_notify", None)
        if notify_data and notify_data.get("fingerprint"):
            await _send_lifecycle_event(
                hass,
                notify_data["fingerprint"],
                notify_data.get("license_key", ""),
                "integration_removed",
            )


async def _send_lifecycle_event(
    hass: HomeAssistant, fingerprint: str, license_key: str, action: str
) -> None:
    """Trimite un eveniment lifecycle direct (fără LicenseManager).

    Folosit în async_remove_entry când LicenseManager nu mai există.
    """
    import hashlib
    import hmac as hmac_lib
    import json
    import time

    import aiohttp

    from .license import INTEGRATION, LICENSE_API_URL, USER_AGENT

    timestamp = int(time.time())
    payload = {
        "fingerprint": fingerprint,
        "timestamp": timestamp,
        "action": action,
        "license_key": license_key,
        "integration": INTEGRATION,
    }
    # HMAC cu fingerprint ca cheie (identic cu LicenseManager._compute_request_hmac)
    data = {k: v for k, v in payload.items() if k != "hmac"}
    msg = json.dumps(data, sort_keys=True).encode()
    payload["hmac"] = hmac_lib.new(
        fingerprint.encode(), msg, hashlib.sha256
    ).hexdigest()

    try:
        session = async_get_clientsession(hass)
        async with session.post(
            f"{LICENSE_API_URL}/notify",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=10),
            headers={
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
        ) as resp:
            if resp.status == 200:
                result = await resp.json()
                if not result.get("success"):
                    _LOGGER.warning(
                        "[Hidroelectrica] Server a refuzat '%s': %s",
                        action, result.get("error"),
                    )
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("[Hidroelectrica] Nu s-a putut raporta '%s': %s", action, err)


async def async_migrate_entry(
    hass: HomeAssistant, config_entry: ConfigEntry
) -> bool:
    """Migrare de la versiuni vechi la versiunea curentă (v3)."""
    _LOGGER.debug(
        "Migrare config entry %s de la versiunea %s.",
        config_entry.entry_id,
        config_entry.version,
    )

    if config_entry.version < 3:
        old_data = dict(config_entry.data)

        new_data = {
            CONF_USERNAME: old_data.get(CONF_USERNAME, old_data.get("username", "")),
            CONF_PASSWORD: old_data.get(CONF_PASSWORD, old_data.get("password", "")),
            CONF_UPDATE_INTERVAL: old_data.get(
                CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL
            ),
            "select_all": False,
            CONF_SELECTED_ACCOUNTS: [],
        }

        # Preservă token-ul de autentificare (dacă există)
        if old_data.get("token_data"):
            new_data["token_data"] = old_data["token_data"]

        _LOGGER.info(
            "Migrare entry %s: v%s → v3.",
            config_entry.entry_id,
            config_entry.version,
        )

        hass.config_entries.async_update_entry(
            config_entry, data=new_data, options={}, version=3
        )
        return True

    _LOGGER.error(
        "Versiune necunoscută pentru migrare: %s (entry_id=%s).",
        config_entry.version,
        config_entry.entry_id,
    )
    return False
