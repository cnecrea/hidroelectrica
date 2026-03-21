"""
Modul de licențiere pentru integrarea Hidroelectrica.

Arhitectură server-side (v3 — multi-integrare, MySQL):
- Fingerprint = SHA-256(HA UUID + machine-id + salt)
- TOTUL e controlat de server: trial, expirare, intervale
- Client trimite fingerprint + integration → server returnează token semnat
- Token-ul serverului conține `valid_until` — cache local expiră automat
- Câmpul `integration` identifică integrarea (fleet, hidroelectrica, etc.)
- Fără constante locale modificabile (trial_days, grace_days etc.)
- Activare: trimite {key, fingerprint, timestamp, integration, hmac} la API
- API returnează token semnat Ed25519 (cheia privată e DOAR pe server)
- Integrarea verifică semnătura cu cheia publică (embedded)
"""

from __future__ import annotations

import hashlib
import hmac as hmac_lib
import json
import logging
import time
from pathlib import Path
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Configurare — doar URL-ul serverului
# ─────────────────────────────────────────────
LICENSE_API_URL = "https://api.hubinteligent.org/license/v1"

STORAGE_KEY = "hidroelectrica_license"
STORAGE_VERSION = 1

# Salt intern pentru fingerprint (face reverse-engineering mai greu)
_FP_SALT = "hDr0_El3c$2026!zW"

# Identificator integrare — trimis la server în fiecare request
# Serverul folosește acest câmp pentru a separa licențele per integrare
INTEGRATION = "hidroelectrica"

# ─────────────────────────────────────────────
# Cheile publice Ed25519 ale serverului (SEC-03: suport key rotation)
# ─────────────────────────────────────────────
# Lista permite rotația cheilor: adaugă cheia nouă PRIMA în listă,
# iar la update-ul următor elimină cheia veche.
# Verificarea încearcă fiecare cheie în ordine — prima care validează câștigă.
# Cheia privată corespunzătoare rămâne DOAR pe server.
SERVER_PUBLIC_KEYS_PEM: list[str] = [
    # Cheia activă (primară)
    """\
-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAUAZIZ1fw+b7qpq9LA47NRbHYhN8kONMxUiJyx5RHrBg=
-----END PUBLIC KEY-----
""",
    # (adaugă aici chei vechi la rotație, șterge-le după ce TOȚI clienții s-au actualizat)
]
SERVER_PUBLIC_KEY_PEM = SERVER_PUBLIC_KEYS_PEM[0]


# ─────────────────────────────────────────────
# Manager de licențe (v2 — server-side)
# ─────────────────────────────────────────────


class LicenseManager:
    """Gestionează licența pentru integrarea Hidroelectrica.

    Toate deciziile de autorizare vin de la server:
    - Trial: serverul decide durata, zilele rămase, expirarea
    - Licență: serverul semnează token-ul de activare
    - Cache: serverul controlează `valid_until` (cât timp e valid local)
    - Heartbeat: intervalul e dictat de `valid_until`, nu de o constantă locală

    Ciclu de viață:
    1. async_load() — se apelează o singură dată la setup
    2. async_check_status() — verifică statusul la server (sau folosește cache)
    3. is_valid — verifică dacă integrarea poate funcționa
    4. async_activate(key) — activează o cheie de licență
    5. async_heartbeat() — validare periodică (intervalul vine de la server)
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """Inițializează managerul de licențe."""
        self._hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, Any] = {}
        self._fingerprint: str = ""
        self._loaded = False
        # Token de status primit de la server (cache local)
        self._status_token: dict[str, Any] = {}

    @property
    def _session(self) -> aiohttp.ClientSession:
        """Returnează sesiunea aiohttp partajată din Home Assistant."""
        return async_get_clientsession(self._hass)

    # ─── Încărcare / Salvare ───

    async def async_load(self) -> None:
        """Încarcă datele de licență din storage. Se apelează o singură dată."""
        _LOGGER.debug("[Hidroelectrica:License] Încep async_load()")
        stored = await self._store.async_load()
        self._data = dict(stored) if stored else {}
        _LOGGER.debug(
            "[Hidroelectrica:License] Date din storage: %d chei (%s)",
            len(self._data),
            ", ".join(self._data.keys()) if self._data else "gol",
        )

        self._fingerprint = await self._hass.async_add_executor_job(
            self._generate_fingerprint
        )
        _LOGGER.debug(
            "[Hidroelectrica:License] Fingerprint generat: %s...", self._fingerprint[:16]
        )

        # Restaurează status token din cache (dacă există)
        self._status_token = self._data.get("status_token", {})
        if self._status_token:
            cached_status = self._status_token.get("status", "?")
            cache_valid = self._is_status_cache_valid()
            _LOGGER.debug(
                "[Hidroelectrica:License] Cache restaurat: status=%s, cache_valid=%s",
                cached_status,
                cache_valid,
            )
        else:
            _LOGGER.debug("[Hidroelectrica:License] Niciun cache de status — prima rulare")

        # Verifică statusul la server (prima verificare la startup)
        _LOGGER.debug("[Hidroelectrica:License] Verific statusul la server (startup)...")
        await self.async_check_status()

        self._loaded = True
        _LOGGER.debug(
            "[Hidroelectrica:License] async_load() finalizat — status=%s, is_valid=%s",
            self.status,
            self.is_valid,
        )

    async def _async_save(self) -> None:
        """Salvează datele de licență."""
        _LOGGER.debug("[Hidroelectrica:License] Salvez datele în storage")
        await self._store.async_save(self._data)

    # ─── Fingerprint ───

    def _generate_fingerprint(self) -> str:
        """Generează un fingerprint unic din HA UUID + machine-id.

        Combinația asigură:
        - HA UUID: unic per instalare HA (se schimbă la reinstalare)
        - machine-id: unic per OS (se schimbă la reinstalare OS)
        - Salt: face fingerprint-ul specific integrării Hidroelectrica
        """
        componente: list[str] = []

        # HA installation UUID
        ha_uuid = ""
        try:
            uuid_path = Path(
                self._hass.config.path(".storage/core.uuid")
            )
            if uuid_path.exists():
                uuid_data = json.loads(uuid_path.read_text())
                ha_uuid = uuid_data.get("data", {}).get("uuid", "")
        except Exception:  # noqa: BLE001
            pass
        componente.append(f"ha:{ha_uuid}")

        # Machine ID
        machine_id = ""
        try:
            mid_path = Path("/etc/machine-id")
            if mid_path.exists():
                machine_id = mid_path.read_text().strip()
        except Exception:  # noqa: BLE001
            pass
        componente.append(f"mid:{machine_id}")

        raw = "|".join(componente) + f"|{_FP_SALT}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @property
    def fingerprint(self) -> str:
        """Returnează fingerprint-ul hardware."""
        return self._fingerprint

    # ─── Verificare status la server ───

    async def async_check_status(self) -> dict[str, Any]:
        """Verifică statusul la server (/license/v1/check).

        Serverul decide TOTUL: trial activ, zile rămase, interval de cache.
        Returnează token-ul de status de la server.

        Dacă există un token cached valid (valid_until > now), îl folosește.
        Altfel, face request la server.
        """
        # Verifică cache-ul local
        if self._is_status_cache_valid():
            _LOGGER.debug(
                "[Hidroelectrica:License] Cache valid — folosesc token existent "
                "(status=%s, valid_until=%.0f)",
                self._status_token.get("status"),
                self._status_token.get("valid_until", 0),
            )
            return self._status_token

        _LOGGER.debug(
            "[Hidroelectrica:License] Cache expirat sau inexistent — "
            "cer status de la server: %s/check",
            LICENSE_API_URL,
        )

        # Trebuie să cerem status de la server
        timestamp = int(time.time())
        payload = {
            "fingerprint": self._fingerprint,
            "timestamp": timestamp,
            "integration": INTEGRATION,
        }
        payload["hmac"] = self._compute_request_hmac(payload)

        try:
            session = self._session
            async with session.post(
                f"{LICENSE_API_URL}/check",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Hidroelectrica-HA-Integration/3.0",
                },
            ) as resp:
                _LOGGER.debug(
                    "[Hidroelectrica:License] Server /check răspuns: HTTP %d",
                    resp.status,
                )
                result = await resp.json()

                if resp.status == 200 and "status" in result:
                    # Verifică semnătura serverului pe token
                    if not self._verify_token_signature(result):
                        _LOGGER.warning(
                            "[Hidroelectrica:License] Semnătura token-ului de status "
                            "e invalidă — ignor răspunsul"
                        )
                        return self._status_token

                    # Salvează noul status token
                    self._status_token = result
                    self._data["status_token"] = result
                    self._data["last_server_check"] = time.time()

                    # Sincronizează license_key din răspunsul serverului
                    # (important: serverul e sursa de adevăr pentru cheie)
                    server_key = result.get("license_key")
                    if server_key and self._data.get("license_key") != server_key:
                        self._data["license_key"] = server_key
                        _LOGGER.debug(
                            "[Hidroelectrica:License] license_key sincronizat "
                            "din răspunsul /check: %s",
                            server_key,
                        )

                    # Salvează client_secret de la server (SEC-01/02)
                    # Folosit ca cheie HMAC în loc de fingerprint
                    cs = result.get("client_secret")
                    if cs:
                        self._data["client_secret"] = cs
                        # Elimină din status_token (nu trebuie cached în token)
                        result.pop("client_secret", None)

                    await self._async_save()

                    _LOGGER.debug(
                        "[Hidroelectrica:License] Status actualizat de la server — %s "
                        "(valid_until: %s)",
                        result.get("status"),
                        result.get("valid_until"),
                    )
                    return result

                _LOGGER.warning(
                    "[Hidroelectrica:License] răspuns invalid de la /check — %s",
                    result,
                )
                return self._status_token

        except aiohttp.ClientError as err:
            _LOGGER.error(
                "[Hidroelectrica:License] eroare de rețea la verificare status — %s", err
            )
            return self._status_token
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "[Hidroelectrica:License] eroare neașteptată la verificare status — %s", err
            )
            return self._status_token

    def _is_status_cache_valid(self) -> bool:
        """Verifică dacă token-ul de status cached e încă valid.

        valid_until e setat de server — controlează cât timp
        clientul poate funcționa fără o nouă verificare.
        """
        if not self._status_token:
            return False

        valid_until = self._status_token.get("valid_until")
        if not valid_until:
            return False

        return time.time() < valid_until

    # ─── Proprietăți de status (toate derivate din token-ul serverului) ───

    @property
    def is_trial_valid(self) -> bool:
        """Verifică dacă perioada de evaluare e activă (conform server)."""
        return (
            self._status_token.get("status") == "trial"
            and self._is_status_cache_valid()
        )

    @property
    def trial_days_remaining(self) -> int:
        """Returnează zilele rămase din trial (de la server)."""
        if self._status_token.get("status") != "trial":
            return 0
        return max(0, int(self._status_token.get("trial_days_remaining", 0)))

    @property
    def is_licensed(self) -> bool:
        """Verifică dacă există o licență activă și validă.

        Verifică ATÂT token-ul de activare (Ed25519) CÂT ȘI
        faptul că serverul confirmă statusul 'licensed'.
        """
        token = self._data.get("activation_token")
        if not token or not isinstance(token, dict):
            return False

        # Verifică semnătura token-ului de activare
        if not self._verify_token_signature(token):
            _LOGGER.warning("[Hidroelectrica:License] semnătură token activare invalidă")
            return False

        # Verifică fingerprint-ul din token-ul de activare
        if token.get("fingerprint") != self._fingerprint:
            _LOGGER.warning("[Hidroelectrica:License] fingerprint token nu se potrivește")
            return False

        # Verifică expirarea din token-ul de activare (licențe anuale)
        expires_at = token.get("expires_at")
        if expires_at and time.time() > expires_at:
            _LOGGER.info("[Hidroelectrica:License] licența a expirat (token local)")
            return False

        # Verifică și status-ul de la server (dacă avem cache valid)
        if self._status_token and self._is_status_cache_valid():
            server_status = self._status_token.get("status")
            if server_status not in ("licensed", "trial"):
                _LOGGER.warning(
                    "[Hidroelectrica:License] serverul raportează status '%s' — licență invalidă",
                    server_status,
                )
                return False

        # Dacă cache-ul de status a expirat, licența e invalidă
        # (serverul controlează intervalul de verificare)
        if self._status_token and not self._is_status_cache_valid():
            _LOGGER.warning(
                "[Hidroelectrica:License] cache-ul de status a expirat — necesită "
                "verificare la server"
            )
            return False

        return True

    @property
    def is_valid(self) -> bool:
        """Verifică dacă integrarea poate funcționa (licență SAU trial).

        Prioritizează răspunsul serverului — dacă serverul confirmă
        'licensed' sau 'trial' și cache-ul e valid, e suficient.
        Asta acoperă scenariul backup/restore: storage local gol,
        dar serverul recunoaște fingerprint-ul ca licențiat.
        """
        # Serverul e sursa de adevăr
        if self._status_token and self._is_status_cache_valid():
            server_status = self._status_token.get("status")
            if server_status in ("licensed", "trial"):
                return True

        # Fallback: verificare locală (token de activare + trial)
        return self.is_licensed or self.is_trial_valid

    @property
    def license_type(self) -> str | None:
        """Returnează tipul licenței active: 'perpetual', 'annual' sau None."""
        token = self._data.get("activation_token")
        if token and isinstance(token, dict):
            return token.get("license_type")
        # Verifică și din status token (pentru trial)
        return self._status_token.get("license_type")

    @property
    def license_key_masked(self) -> str | None:
        """Returnează cheia de licență mascată (ex: HDEL-XXXX-****)."""
        key = self._data.get("license_key")
        if not key or len(key) < 10:
            return key
        return key[:10] + "*" * (len(key) - 10)

    @property
    def activated_at(self) -> float | None:
        """Returnează timestamp-ul activării licenței sau None."""
        # 1. Din activation_token (salvat la activare)
        token = self._data.get("activation_token")
        if token and isinstance(token, dict):
            ts = token.get("activated_at")
            if ts:
                return ts
        # 2. Din _data (salvat explicit la activare)
        ts = self._data.get("activated_at")
        if ts:
            return ts
        # 3. Din status_token (dacă serverul îl trimite)
        if self._status_token:
            return self._status_token.get("activated_at")
        return None

    @property
    def license_expires_at(self) -> float | None:
        """Returnează timestamp-ul de expirare sau None (perpetual)."""
        # 1. Din activation_token (salvat la activare)
        token = self._data.get("activation_token")
        if token and isinstance(token, dict):
            ea = token.get("expires_at")
            if ea:
                return ea
        # 2. Fallback: din status_token (de la server /check)
        if self._status_token:
            return self._status_token.get("expires_at")
        return None

    @property
    def status(self) -> str:
        """Returnează starea curentă a licenței.

        Prioritizează răspunsul serverului (din status_token).
        Valori posibile: 'licensed', 'trial', 'expired', 'unlicensed'.
        """
        # Dacă avem status valid de la server, îl folosim
        if self._status_token and self._is_status_cache_valid():
            server_status = self._status_token.get("status", "unlicensed")
            if server_status in ("licensed", "trial", "expired"):
                return server_status

        # Dacă avem token de activare dar cache expirat
        if self._data.get("activation_token"):
            return "expired"

        return "unlicensed"

    @property
    def needs_heartbeat(self) -> bool:
        """Verifică dacă e timpul pentru o verificare la server.

        Intervalul e controlat de server via `valid_until`.
        Nu mai există constantă locală LICENSE_CHECK_INTERVAL_SEC.
        """
        return not self._is_status_cache_valid()

    @property
    def check_interval_seconds(self) -> int:
        """Returnează intervalul de verificare (secundele până la valid_until).

        Folosit de __init__.py pentru a programa heartbeat-ul.
        Dacă nu avem informație de la server, implicit 4 ore (conservator).
        """
        if not self._status_token:
            return 4 * 3600  # 4 ore implicit (conservative)

        valid_until = self._status_token.get("valid_until", 0)
        remaining = valid_until - time.time()

        if remaining <= 0:
            return 300  # 5 minute — trebuie verificat acum

        # Nu depăși 24h chiar dacă serverul zice mai mult
        return min(int(remaining), 24 * 3600)

    # ─── Verificare status la server (alias pentru heartbeat) ───

    async def async_heartbeat(self) -> bool:
        """Trimite un heartbeat de validare la server.

        În v2, heartbeat = async_check_status() + validate (dacă licențiat).
        Returnează True dacă validarea a reușit.
        """
        # 1. Verifică statusul general
        await self.async_check_status()

        # 2. Dacă are licență activă, trimite și validate
        token = self._data.get("activation_token")
        if not token:
            return self._is_status_cache_valid()

        timestamp = int(time.time())
        payload = {
            "license_key": self._data.get("license_key", ""),
            "fingerprint": self._fingerprint,
            "timestamp": timestamp,
            "integration": INTEGRATION,
        }
        payload["hmac"] = self._compute_request_hmac(payload)

        try:
            session = self._session
            async with session.post(
                f"{LICENSE_API_URL}/validate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "Hidroelectrica-HA-Integration/3.0",
                    },
                ) as resp:
                    result = await resp.json()

                    if resp.status == 200 and result.get("valid"):
                        self._data["last_validation"] = time.time()

                        # Dacă serverul trimite un token reînnoit
                        new_token = result.get("token")
                        if new_token and self._verify_token_signature(
                            new_token
                        ):
                            self._data["activation_token"] = new_token

                        await self._async_save()
                        return True

                    _LOGGER.warning(
                        "[Hidroelectrica:License] heartbeat respins — %s",
                        result.get("error", "necunoscut"),
                    )
                    return False

        except Exception:  # noqa: BLE001
            _LOGGER.debug("[Hidroelectrica:License] heartbeat eșuat (rețea indisponibilă)")
            return False

    # ─── Activare licență ───

    async def async_activate(self, license_key: str) -> dict[str, Any]:
        """Activează o cheie de licență prin API.

        Trimite: {license_key, fingerprint, timestamp, hmac}
        Primește: {success, token: {license_key, license_type,
                   fingerprint, activated_at, expires_at, signature}}

        Returnează: {"success": True} sau {"success": False, "error": "..."}
        """
        timestamp = int(time.time())

        payload = {
            "license_key": license_key.strip().upper(),
            "fingerprint": self._fingerprint,
            "timestamp": timestamp,
            "integration": INTEGRATION,
        }
        payload["hmac"] = self._compute_request_hmac(payload)

        try:
            session = self._session
            async with session.post(
                f"{LICENSE_API_URL}/activate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "Hidroelectrica-HA-Integration/3.0",
                    },
                ) as resp:
                    _LOGGER.debug(
                        "[Hidroelectrica:License] /activate răspuns: HTTP %d",
                        resp.status,
                    )

                    # Serverul a returnat eroare HTTP (500, 422, etc.)
                    if resp.status != 200:
                        try:
                            body = await resp.text()
                        except Exception:  # noqa: BLE001
                            body = "(nu s-a putut citi)"
                        _LOGGER.warning(
                            "[Hidroelectrica:License] activare eșuată — "
                            "HTTP %d: %s",
                            resp.status,
                            body[:500],
                        )
                        return {
                            "success": False,
                            "error": f"http_{resp.status}",
                        }

                    result = await resp.json()

                    if result.get("success"):
                        token = result.get("token", {})

                        # Verifică semnătura serverului
                        if not self._verify_token_signature(token):
                            return {
                                "success": False,
                                "error": "invalid_signature",
                            }

                        # Verifică că token-ul e pentru noi
                        if token.get("fingerprint") != self._fingerprint:
                            return {
                                "success": False,
                                "error": "fingerprint_mismatch",
                            }

                        # Salvează token-ul
                        self._data["activation_token"] = token
                        self._data["license_key"] = (
                            license_key.strip().upper()
                        )
                        self._data["last_validation"] = time.time()
                        self._data["activated_at"] = token.get(
                            "activated_at"
                        )
                        await self._async_save()

                        # Invalidează cache-ul de status vechi (trial)
                        # ca async_check_status() să facă request fresh
                        self._status_token = {}
                        self._data.pop("status_token", None)

                        # Actualizează status-ul de la server (acum va fi 'licensed')
                        await self.async_check_status()

                        _LOGGER.info(
                            "[Hidroelectrica:License] licență activată cu succes (%s)",
                            token.get("license_type", "necunoscut"),
                        )

                        # Auto-reload: reîncarcă toate entry-urile hidroelectrica
                        # ca senzorii să se recreeze cu licență validă
                        await self._async_reload_entries()

                        return {"success": True}

                    error = result.get("error", "unknown")
                    _LOGGER.warning(
                        "[Hidroelectrica:License] activare eșuată — %s (răspuns: %s)",
                        error,
                        result,
                    )
                    return {"success": False, "error": error}

        except aiohttp.ClientError as err:
            _LOGGER.error(
                "[Hidroelectrica:License] eroare de rețea la activare — %s", err
            )
            return {"success": False, "error": "network_error"}
        except Exception as err:  # noqa: BLE001
            _LOGGER.error(
                "[Hidroelectrica:License] eroare neașteptată la activare — %s", err
            )
            return {"success": False, "error": "unknown_error"}

    # ─── Dezactivare ───

    async def async_deactivate(self) -> dict[str, Any]:
        """Dezactivează licența curentă (pentru mutare pe alt server).

        Trimite cerere de dezactivare la API, apoi șterge token-ul local.
        """
        token = self._data.get("activation_token")
        if not token:
            return {"success": False, "error": "no_license"}

        timestamp = int(time.time())
        payload = {
            "license_key": self._data.get("license_key", ""),
            "fingerprint": self._fingerprint,
            "timestamp": timestamp,
            "integration": INTEGRATION,
        }
        payload["hmac"] = self._compute_request_hmac(payload)

        try:
            session = self._session
            async with session.post(
                f"{LICENSE_API_URL}/deactivate",
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "Hidroelectrica-HA-Integration/3.0",
                    },
                ) as resp:
                    result = await resp.json()

                    if resp.status == 200 and result.get("success"):
                        # Șterge token-ul local
                        self._data.pop("activation_token", None)
                        self._data.pop("license_key", None)
                        self._data.pop("last_validation", None)
                        self._data.pop("activated_at", None)
                        await self._async_save()

                        # Invalidează cache-ul de status vechi (licensed)
                        self._status_token = {}
                        self._data.pop("status_token", None)

                        # Actualizează status-ul de la server
                        await self.async_check_status()

                        _LOGGER.info(
                            "[Hidroelectrica:License] licență dezactivată cu succes"
                        )

                        # Auto-reload: reîncarcă entry-urile
                        await self._async_reload_entries()

                        return {"success": True}

                    return {
                        "success": False,
                        "error": result.get("error", "server_error"),
                    }

        except Exception as err:  # noqa: BLE001
            _LOGGER.error("[Hidroelectrica:License] eroare la dezactivare — %s", err)
            return {"success": False, "error": "network_error"}

    # ─── Notificări lifecycle (disable / remove) ───

    async def async_notify_event(self, action: str) -> None:
        """Trimite un eveniment de lifecycle la server (fire-and-forget).

        Acțiuni suportate: 'integration_disabled', 'integration_removed'.
        Nu afectează starea licenței — doar loghează în audit_log.
        """
        timestamp = int(time.time())
        payload = {
            "fingerprint": self._fingerprint,
            "timestamp": timestamp,
            "action": action,
            "license_key": self._data.get("license_key", ""),
            "integration": INTEGRATION,
        }
        payload["hmac"] = self._compute_request_hmac(payload)

        try:
            session = self._session
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
                                "[Hidroelectrica:License] Server a refuzat '%s': %s",
                                action, result.get("error"),
                            )
                    else:
                        _LOGGER.warning(
                            "[Hidroelectrica:License] Notify HTTP %d pentru '%s'",
                            resp.status, action,
                        )
        except Exception as err:  # noqa: BLE001
            # Fire-and-forget: nu blocăm unload-ul dacă rețeaua e indisponibilă
            _LOGGER.debug(
                "[Hidroelectrica:License] Nu s-a putut raporta '%s': %s",
                action, err,
            )

    # ─── Reload entries ───

    async def _async_reload_entries(self) -> None:
        """Reîncarcă toate entry-urile hidroelectrica după activare/dezactivare.

        Acest lucru recreează senzorii cu starea corectă de licență,
        fără ca utilizatorul să fie nevoit să facă reload manual.
        """
        entries = self._hass.config_entries.async_entries(DOMAIN)
        if not entries:
            return

        _LOGGER.info(
            "[Hidroelectrica:License] Reîncarc %d entry-uri după schimbarea licenței",
            len(entries),
        )
        for entry in entries:
            self._hass.async_create_task(
                self._hass.config_entries.async_reload(entry.entry_id)
            )

    # ─── Criptografie ───

    def _verify_token_signature(self, token: dict[str, Any]) -> bool:
        """Verifică semnătura Ed25519 a serverului pe un token.

        Token-ul conține diverse câmpuri + 'signature'.
        Semnătura e calculată pe JSON-ul celorlalte câmpuri (sort_keys).

        SEC-03: Încearcă toate cheile publice din SERVER_PUBLIC_KEYS_PEM
        (suport key rotation — prima cheie care validează câștigă).
        """
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import (
                Ed25519PublicKey,
            )
            from cryptography.hazmat.primitives.serialization import (
                load_pem_public_key,
            )

            signature_hex = token.get("signature")
            if not signature_hex:
                return False

            signature = bytes.fromhex(signature_hex)

            # Reconstituie datele semnate (fără câmpul signature)
            signed_data = {
                k: v for k, v in token.items() if k != "signature"
            }
            message = json.dumps(signed_data, sort_keys=True).encode()

            # Încearcă fiecare cheie publică (key rotation support)
            for key_pem in SERVER_PUBLIC_KEYS_PEM:
                try:
                    public_key = load_pem_public_key(key_pem.encode())
                    if not isinstance(public_key, Ed25519PublicKey):
                        continue
                    public_key.verify(signature, message)
                    return True
                except Exception:  # noqa: BLE001
                    continue

            _LOGGER.debug(
                "[Hidroelectrica:License] nicio cheie publică nu a validat semnătura"
            )
            return False

        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "[Hidroelectrica:License] verificare semnătură eșuată — %s", err
            )
            return False

    def _compute_request_hmac(self, payload: dict[str, Any]) -> str:
        """Calculează HMAC-SHA256 pentru integritatea request-ului.

        Cheia HMAC = client_secret (de la server, unic per instalare).
        Fallback pe fingerprint dacă client_secret nu e disponibil încă
        (prima rulare, înainte de primul /check).
        """
        data = {k: v for k, v in payload.items() if k != "hmac"}
        msg = json.dumps(data, sort_keys=True).encode()
        # Folosește client_secret dacă e disponibil (v3.1)
        hmac_key = self._data.get("client_secret") or self._fingerprint
        return hmac_lib.new(
            hmac_key.encode(),
            msg,
            hashlib.sha256,
        ).hexdigest()

    # ─── Info (pentru UI / diagnostics) ───

    def as_dict(self) -> dict[str, Any]:
        """Returnează informațiile de licență pentru diagnostics/UI."""
        return {
            "status": self.status,
            "fingerprint": self._fingerprint[:16] + "...",
            "trial_days_remaining": self.trial_days_remaining,
            "license_type": self.license_type,
            "license_key": self.license_key_masked,
            "is_valid": self.is_valid,
            "cache_valid": self._is_status_cache_valid(),
        }
