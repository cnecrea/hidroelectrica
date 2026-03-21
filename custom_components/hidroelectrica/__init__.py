"""Inițializarea integrării Hidroelectrica România."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import UpdateFailed

from .api import HidroelectricaApiClient
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
    PLATFORMS,
)
from .coordinator import HidroelectricaCoordinator
from .license import LicenseManager

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


@dataclass
class HidroelectricaRuntimeData:
    """Structură tipizată pentru datele runtime ale integrării."""

    coordinators: dict[str, HidroelectricaCoordinator] = field(default_factory=dict)
    api_client: HidroelectricaApiClient | None = None


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Configurează integrarea globală Hidroelectrica România."""
    _LOGGER.debug("Inițializare globală integrare: %s", DOMAIN)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configurează integrarea pentru o intrare specifică (config entry)."""
    _LOGGER.info(
        "Se configurează integrarea %s (entry_id=%s).",
        DOMAIN,
        entry.entry_id,
    )

    hass.data.setdefault(DOMAIN, {})

    # ── Inițializare License Manager (o singură instanță per domeniu) ──
    if LICENSE_DATA_KEY not in hass.data.get(DOMAIN, {}):
        _LOGGER.debug("[Hidroelectrica] Inițializez LicenseManager (prima entry)")
        license_mgr = LicenseManager(hass)
        await license_mgr.async_load()
        hass.data[DOMAIN][LICENSE_DATA_KEY] = license_mgr
        _LOGGER.debug(
            "[Hidroelectrica] LicenseManager: status=%s, valid=%s, fingerprint=%s...",
            license_mgr.status,
            license_mgr.is_valid,
            license_mgr.fingerprint[:16],
        )

        # Heartbeat periodic — intervalul vine de la server (via valid_until)
        from datetime import timedelta

        interval_sec = license_mgr.check_interval_seconds
        _LOGGER.debug(
            "[Hidroelectrica] Programez heartbeat periodic la fiecare %d secunde (%d ore)",
            interval_sec,
            interval_sec // 3600,
        )

        async def _heartbeat_periodic(_now: Any) -> None:
            """Verifică statusul la server dacă cache-ul a expirat."""
            mgr: LicenseManager | None = hass.data.get(DOMAIN, {}).get(
                LICENSE_DATA_KEY
            )
            if not mgr:
                _LOGGER.debug("[Hidroelectrica] Heartbeat: LicenseManager nu există, skip")
                return
            if mgr.needs_heartbeat:
                _LOGGER.debug("[Hidroelectrica] Heartbeat: cache expirat, verific la server")
                await mgr.async_heartbeat()
            else:
                _LOGGER.debug("[Hidroelectrica] Heartbeat: cache valid, nu e nevoie de verificare")

        # Stocăm cancel-ul heartbeat-ului la nivel de domeniu,
        # NU pe entry (ca să nu dispară când se șterge prima entry)
        cancel_heartbeat = async_track_time_interval(
            hass,
            _heartbeat_periodic,
            timedelta(seconds=interval_sec),
        )
        hass.data[DOMAIN]["_cancel_heartbeat"] = cancel_heartbeat
        _LOGGER.debug("[Hidroelectrica] Heartbeat programat și stocat în hass.data")

        # ── Notificare re-enable (dacă a fost dezactivată anterior) ──
        was_disabled = hass.data.pop(f"{DOMAIN}_was_disabled", False)
        if was_disabled:
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
    else:
        _LOGGER.debug(
            "[Hidroelectrica] LicenseManager există deja (entry suplimentară: %s)",
            entry.entry_id,
        )

    session = async_get_clientsession(hass, verify_ssl=False)
    username = entry.data[CONF_USERNAME]
    password = entry.data[CONF_PASSWORD]
    update_interval = entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)

    # Conturi selectate
    selected_accounts = entry.data.get(CONF_SELECTED_ACCOUNTS, [])
    if not selected_accounts:
        _LOGGER.error(
            "Nu există conturi selectate pentru %s (entry_id=%s).",
            DOMAIN,
            entry.entry_id,
        )
        return False

    _LOGGER.debug(
        "Conturi selectate pentru %s (entry_id=%s): %s, interval=%ss.",
        DOMAIN,
        entry.entry_id,
        selected_accounts,
        update_interval,
    )

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
        except UpdateFailed as err:
            _LOGGER.error(
                "Prima actualizare eșuată (entry_id=%s, UAN=%s): %s",
                entry.entry_id,
                uan,
                err,
            )
            continue
        except Exception as err:
            _LOGGER.exception(
                "Eroare neașteptată la prima actualizare (entry_id=%s, UAN=%s): %s",
                entry.entry_id,
                uan,
                err,
            )
            continue

        coordinators[uan] = coordinator

    if not coordinators:
        _LOGGER.error(
            "Niciun coordinator inițializat cu succes pentru %s (entry_id=%s).",
            DOMAIN,
            entry.entry_id,
        )
        return False

    _LOGGER.info(
        "%s coordinatoare active din %s conturi selectate (entry_id=%s).",
        len(coordinators),
        len(selected_accounts),
        entry.entry_id,
    )

    # Salvăm datele runtime + entry_id
    hass.data[DOMAIN][entry.entry_id] = entry
    entry.runtime_data = HidroelectricaRuntimeData(
        coordinators=coordinators,
        api_client=api_client,
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
    """Reîncarcă integrarea când opțiunile se schimbă."""
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
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        _LOGGER.debug("[Hidroelectrica] Entry %s eliminat din hass.data", entry.entry_id)

        # Verifică dacă mai sunt entry-uri active (sursa de adevăr: config_entries)
        entry_ids_ramase = [
            e.entry_id
            for e in hass.config_entries.async_entries(DOMAIN)
            if e.entry_id != entry.entry_id
        ]

        _LOGGER.debug(
            "[Hidroelectrica] Entry-uri rămase după unload: %d (%s)",
            len(entry_ids_ramase),
            entry_ids_ramase or "niciuna",
        )

        if not entry_ids_ramase:
            _LOGGER.info("[Hidroelectrica] Ultima entry descărcată — curăț domeniul complet")

            # ── Notificare lifecycle (înainte de cleanup!) ──
            mgr = hass.data[DOMAIN].get(LICENSE_DATA_KEY)
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
                    _LOGGER.debug(
                        "[Hidroelectrica] Fingerprint salvat pentru async_remove_entry"
                    )

            # Oprește heartbeat-ul
            cancel_hb = hass.data[DOMAIN].pop("_cancel_heartbeat", None)
            if cancel_hb:
                cancel_hb()
                _LOGGER.debug("[Hidroelectrica] Heartbeat periodic oprit")

            # Elimină LicenseManager
            hass.data[DOMAIN].pop(LICENSE_DATA_KEY, None)
            _LOGGER.debug("[Hidroelectrica] LicenseManager eliminat")

            # Elimină domeniul
            hass.data.pop(DOMAIN, None)
            _LOGGER.debug("[Hidroelectrica] hass.data[%s] eliminat complet", DOMAIN)

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

    from .license import INTEGRATION, LICENSE_API_URL

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
                "User-Agent": "Hidroelectrica-HA-Integration/3.0",
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
