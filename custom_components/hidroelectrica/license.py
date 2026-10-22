"""
Modul de licențiere pentru integrarea Hidroelectrica.

Arhitectură server-side (protocol v3 — vezi STANDARD-LICENTA.md / WebAPI):
- Fingerprint = SHA-256(HA UUID + machine-id + salt)
- TOTUL e controlat de server: trial, expirare, intervale
- /check   → token de status semnat Ed25519 (valid_until = cât timp e valabil local)
- /validate → heartbeat-ul licenței (actualizează last_heartbeat + versiunile pe server);
             se trimite după fiecare /check reușit care confirmă statusul 'licensed'
- /activate, /deactivate, /notify — semnate HMAC (client_secret, fallback fingerprint)
- La 'invalid_hmac' (client_secret desincronizat) cererea se reia o dată semnată cu fingerprint
"""

from __future__ import annotations

import asyncio
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
USER_AGENT = "Hidroelectrica-HA-Integration/3.1"

STORAGE_KEY = "hidroelectrica_license"
STORAGE_VERSION = 1

# Salt intern pentru fingerprint (face reverse-engineering mai greu)
_FP_SALT = "hDr0_El3c$2026!zW"

# Identificator integrare — trimis la server în fiecare request
INTEGRATION = "hidroelectrica"

# Timeout pentru verificarea care blochează pornirea (doar fără stare locală utilizabilă)
_STARTUP_TIMEOUT_SEC = 10

# Erori /validate care înseamnă că licența NU mai e activă pe acest dispozitiv
_VALIDATE_DEFINITIVE_ERRORS = ("not_active", "fingerprint_mismatch", "invalid_key", "expired")

# ─────────────────────────────────────────────
# Cheia publică Ed25519 a serverului
# ─────────────────────────────────────────────
# Cheia privată corespunzătoare rămâne DOAR pe server. Cheia publică permite
# doar VERIFICAREA semnăturilor. Lista suportă rotația cheilor (SEC-03).
SERVER_PUBLIC_KEYS_PEM: list[str] = [
    """\
-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEAUAZIZ1fw+b7qpq9LA47NRbHYhN8kONMxUiJyx5RHrBg=
-----END PUBLIC KEY-----
""",
]

# Backward compatibility alias (cod existent poate referi forma singulară)
SERVER_PUBLIC_KEY_PEM = SERVER_PUBLIC_KEYS_PEM[0]


# ─────────────────────────────────────────────
# Manager de licențe
# ─────────────────────────────────────────────


class LicenseManager:
    """Gestionează licența pentru integrarea Hidroelectrica.

    Toate deciziile de autorizare vin de la server:
    - Trial: serverul decide durata, zilele rămase, expirarea
    - Licență: serverul semnează token-ul de activare
    - Cache: serverul controlează `valid_until` (cât timp e valid local)

    Ciclu de viață:
    1. async_load() — o singură dată la setup
    2. async_check_status() — status de la server (sau din cache) + heartbeat /validate
    3. is_valid — poate funcționa integrarea?
    4. async_activate(key) / async_deactivate()
    5. check_interval_seconds — când trebuie verificat din nou (folosit de __init__.py)

    NU reîncarcă singur entry-urile la schimbarea statusului — de asta se ocupă
    timer-ul din __init__.py (care actualizează și notificările).
    """

    # Perioadă de grație după expirarea cache-ului (server inaccesibil).
    _GRACE_LICENSED_SEC: int = 72 * 3600   # 72h pentru licențe active
    _GRACE_TRIAL_SEC: int = 24 * 3600      # 24h pentru trial

    def __init__(self, hass: HomeAssistant) -> None:
        """Inițializează managerul de licențe."""
        self._hass = hass
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._data: dict[str, Any] = {}
        self._fingerprint: str = ""
        self._hardware_fingerprint: str = ""
        self._loaded = False
        # Token de status primit de la server (cache local)
        self._status_token: dict[str, Any] = {}
        # Flag anti-spam: logăm WARNING de cache expirat O SINGURĂ DATĂ
        self._cache_expiry_warned = False
        # Eșecuri consecutive la contactarea serverului (pentru backoff)
        self._consecutive_failures: int = 0
        # Serializează verificările: două timere / fluxuri simultane nu dublează request-urile
        self._check_lock = asyncio.Lock()
        # Previne bucla validate → re-check → validate
        self._revalidating = False
        # Versiunea integrării — citită din manifest.json în async_load() (I/O în executor)
        self._integration_version: str | None = None
        # Versiunea Home Assistant (import pur, fără I/O)
        self._ha_version: str | None = None
        try:
            from homeassistant.const import __version__ as ha_ver
            self._ha_version = ha_ver
        except ImportError:
            pass

    @staticmethod
    def _read_manifest_version() -> str | None:
        """Citește versiunea integrării din manifest.json (o singură dată, la startup)."""
        try:
            manifest_path = Path(__file__).parent / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            return manifest.get("version")
        except Exception:  # noqa: BLE001
            return None

    @property
    def _session(self) -> aiohttp.ClientSession:
        """Returnează sesiunea HTTP partajată din Home Assistant."""
        return async_get_clientsession(self._hass)

    # ─── Încărcare / Salvare ───

    async def async_load(self) -> None:
        """Încarcă datele de licență din storage și verifică statusul la server."""
        try:
            stored = await self._store.async_load()
            self._data = dict(stored) if stored else {}
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "[Hidroelectrica:License] Storage corupt sau ilizibil "
                "— pornesc cu date goale (serverul va restaura starea)"
            )
            self._data = {}

        self._fingerprint = await self._hass.async_add_executor_job(
            self._generate_fingerprint
        )
        self._hardware_fingerprint = await self._hass.async_add_executor_job(
            self._generate_hardware_fingerprint
        )
        self._integration_version = await self._hass.async_add_executor_job(
            self._read_manifest_version
        )
        _LOGGER.debug(
            "[Hidroelectrica:License] Fingerprint: %s... (hw: %s...)",
            self._fingerprint[:16],
            self._hardware_fingerprint[:16],
        )

        # Restaurează status token din cache — doar dacă aparține ACESTUI dispozitiv
        # (un storage copiat de pe alt sistem nu trebuie să deblocheze integrarea).
        cached = self._data.get("status_token")
        if not isinstance(cached, dict):
            cached = {}
        if cached and self._token_matches(cached):
            self._status_token = cached
            _LOGGER.debug(
                "[Hidroelectrica:License] Cache restaurat: status=%s, valid=%s",
                cached.get("status"),
                self._is_status_cache_valid(),
            )
        elif cached:
            _LOGGER.info(
                "[Hidroelectrica:License] Cache de status ignorat — aparține altui "
                "dispozitiv/integrări (fingerprint diferit)"
            )
            self._data.pop("status_token", None)

        if self._is_status_cache_valid() or self._is_within_grace_period():
            # Pornirea Home Assistant NU așteaptă serverul de licențe când există o
            # stare locală utilizabilă (cache valid sau perioadă de grație):
            # verificarea se face în fundal, de timer-ul din __init__.py.
            _LOGGER.debug("[Hidroelectrica:License] Stare locală utilizabilă — verificare în fundal")
        else:
            # Prima pornire / grație depășită: statusul e necesar acum, dar cu
            # timeout scurt (un server căzut nu ține pornirea 30s).
            await self.async_check_status(timeout=_STARTUP_TIMEOUT_SEC)
        self._loaded = True

        final_status = self.status
        if final_status == "licensed":
            _LOGGER.info(
                "[Hidroelectrica:License] ✓ Licență ACTIVĂ (cheie: %s)",
                self.license_key_masked or "?",
            )
        elif final_status == "trial":
            _LOGGER.info(
                "[Hidroelectrica:License] ⏳ Perioadă de evaluare: %d zile rămase",
                self.trial_days_remaining,
            )
        elif final_status == "expired":
            _LOGGER.warning(
                "[Hidroelectrica:License] ✗ EXPIRAT — perioada de evaluare "
                "sau licența a expirat. Senzorii nu vor funcționa."
            )
        else:
            _LOGGER.warning(
                "[Hidroelectrica:License] ✗ FĂRĂ LICENȚĂ (status=%s) — "
                "senzorii nu vor funcționa.", final_status
            )

    async def _async_save(self) -> None:
        """Salvează datele de licență."""
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

    def _generate_hardware_fingerprint(self) -> str:
        """Generează un fingerprint hardware unic per mașină fizică (v2).

        Combină multiple surse hardware care supraviețuiesc ștergerii .storage:
        - machine-id: identificator OS (poate fi partajat în HAOS/Docker)
        - CPU serial: unic per Raspberry Pi (gravat în SoC)
        - DMI UUID: unic per placă de bază x86
        - MAC address: unic per interfață de rețea

        Chiar dacă unele surse lipsesc, combinația reduce dramatic
        probabilitatea de coliziune între mașini fizice diferite.

        NU conține HA UUID → supraviețuiește ștergerii .storage/core.uuid.
        """
        parts: list[str] = []

        # 1. machine-id (poate fi partajat în HAOS, dar contribuie la hash)
        machine_id = ""
        try:
            mid_path = Path("/etc/machine-id")
            if mid_path.exists():
                machine_id = mid_path.read_text().strip()
        except Exception:  # noqa: BLE001
            pass
        parts.append(f"mid:{machine_id}")

        # 2. CPU serial — unic per Raspberry Pi (gravat hardware)
        cpu_serial = ""
        try:
            cpuinfo_path = Path("/proc/cpuinfo")
            if cpuinfo_path.exists():
                for line in cpuinfo_path.read_text().splitlines():
                    if line.strip().lower().startswith("serial"):
                        cpu_serial = line.split(":", 1)[1].strip()
                        break
        except Exception:  # noqa: BLE001
            pass
        parts.append(f"cpu:{cpu_serial}")

        # 3. DMI product UUID — unic per placă de bază x86
        dmi_uuid = ""
        try:
            dmi_path = Path("/sys/class/dmi/id/product_uuid")
            if dmi_path.exists():
                dmi_uuid = dmi_path.read_text().strip()
        except Exception:  # noqa: BLE001
            pass
        parts.append(f"dmi:{dmi_uuid}")

        # 4. MAC address — unic per interfață de rețea
        mac_addr = ""
        try:
            import uuid as _uuid_mod
            node = _uuid_mod.getnode()
            # getnode() returnează random dacă nu găsește MAC real;
            # verificăm bitul multicast (bit 0 al primului octet)
            if not (node >> 40) & 1:  # bit multicast = 0 → MAC real
                mac_addr = format(node, "012x")
        except Exception:  # noqa: BLE001
            pass
        parts.append(f"mac:{mac_addr}")

        raw = "|".join(parts) + f"|{_FP_SALT}"
        return hashlib.sha256(raw.encode()).hexdigest()

    @property
    def fingerprint(self) -> str:
        """Returnează fingerprint-ul principal."""
        return self._fingerprint

    @property
    def hardware_fingerprint(self) -> str:
        """Returnează fingerprint-ul hardware (anti-abuse)."""
        return self._hardware_fingerprint

    def _token_matches(self, token: dict[str, Any]) -> bool:
        """Token-ul (semnat de server) aparține acestui dispozitiv și acestei integrări?"""
        return (
            token.get("fingerprint") == self._fingerprint
            and token.get("integration", INTEGRATION) == INTEGRATION
        )

    # ─── Comunicare cu serverul ───

    async def _async_signed_post(
        self, endpoint: str, payload: dict[str, Any], timeout: int = 30
    ) -> tuple[int, dict[str, Any]]:
        """POST semnat HMAC către /license/v1/<endpoint>. Returnează (HTTP status, JSON).

        Dacă serverul răspunde 'invalid_hmac' și cererea a fost semnată cu
        client_secret, secretul local e desincronizat (ex: trial recreat pe server):
        îl ștergem și reluăm O DATĂ cererea semnată cu fingerprint — serverul
        acceptă oricând fallback-ul pe fingerprint și trimite secretul nou la /check.
        Excepțiile de rețea/timeout sunt propagate apelantului.
        """
        for attempt in (1, 2):
            body = dict(payload)
            body["hmac"] = self._compute_request_hmac(body)
            async with self._session.post(
                f"{LICENSE_API_URL}/{endpoint}",
                json=body,
                timeout=aiohttp.ClientTimeout(total=timeout),
                headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
            ) as resp:
                status = resp.status
                try:
                    result = await resp.json(content_type=None)
                except ValueError:  # răspuns non-JSON (ex: pagină HTML 502 de la proxy)
                    result = {}
            if not isinstance(result, dict):
                result = {}
            if (
                attempt == 1
                and result.get("error") == "invalid_hmac"
                and self._data.get("client_secret")
            ):
                _LOGGER.warning(
                    "[Hidroelectrica:License] /%s: HMAC invalid — client_secret desincronizat, "
                    "reîncerc semnat cu fingerprint", endpoint,
                )
                self._data.pop("client_secret", None)
                await self._async_save()
                continue
            return status, result
        return status, result  # pragma: no cover — bucla returnează mereu

    def _register_failure(self, message: str, *args: Any) -> None:
        self._consecutive_failures += 1
        _LOGGER.warning(
            "[Hidroelectrica:License] " + message + " (eșec consecutiv #%d)",
            *args, self._consecutive_failures,
        )

    # ─── Verificare status la server ───

    async def async_check_status(
        self, force: bool = False, timeout: int = 30
    ) -> dict[str, Any]:
        """Statusul de la server (/check), sau din cache dacă e încă valid.

        `force=True` ignoră cache-ul (după activare/dezactivare sau când
        /validate arată că licența nu mai e activă).
        Returnează token-ul de status curent.
        """
        async with self._check_lock:
            if not force and self._is_status_cache_valid():
                return self._status_token
            return await self._async_refresh_status(timeout)

    async def _async_refresh_status(self, timeout: int = 30) -> dict[str, Any]:
        """Cere statusul la server. Apelat doar cu _check_lock deținut."""
        payload = {
            "fingerprint": self._fingerprint,
            "timestamp": int(time.time()),
            "integration": INTEGRATION,
            "hardware_fingerprint": self._hardware_fingerprint,
            "integration_version": self._integration_version,
            "ha_version": self._ha_version,
        }
        try:
            http_status, result = await self._async_signed_post("check", payload, timeout)
        except Exception as err:  # noqa: BLE001 — rețea, timeout, DNS
            self._register_failure("server inaccesibil la /check — %s", err)
            return self._status_token

        if http_status != 200 or "status" not in result:
            if result.get("error") == "invalid_hmac":
                self._register_failure(
                    "HMAC invalid la /check — serverul nu recunoaște acest dispozitiv"
                )
            else:
                self._register_failure(
                    "răspuns invalid de la /check — HTTP %d %s",
                    http_status, result.get("error") or result.get("detail") or "",
                )
            return self._status_token

        if not self._verify_token_signature(result):
            self._register_failure("semnătura token-ului de status e invalidă — ignor răspunsul")
            return self._status_token
        if not self._token_matches(result):
            self._register_failure("token de status pentru alt dispozitiv/integrare — ignor răspunsul")
            return self._status_token

        self._status_token = result
        self._data["status_token"] = result
        self._data["last_server_check"] = time.time()

        # Serverul e sursa de adevăr pentru cheie și pentru client_secret
        server_key = result.get("license_key")
        if server_key and self._data.get("license_key") != server_key:
            self._data["license_key"] = server_key
        client_secret = result.get("client_secret")
        if client_secret and self._data.get("client_secret") != client_secret:
            self._data["client_secret"] = client_secret

        await self._async_save()
        self._cache_expiry_warned = False
        self._consecutive_failures = 0

        server_status = result.get("status")
        _LOGGER.debug(
            "[Hidroelectrica:License] Status de la server: %s (valid_until: %s)",
            server_status, result.get("valid_until"),
        )

        # Heartbeat-ul licenței: WebAPI ține evidența instalărilor licențiate
        # active (last_heartbeat, versiuni) DOAR prin /validate.
        if server_status == "licensed":
            await self._async_validate(timeout)

        return self._status_token

    async def _async_validate(self, timeout: int = 30) -> bool:
        """Trimite /validate pentru licența activă. Apelat doar cu _check_lock deținut."""
        key = self._status_token.get("license_key") or self._data.get("license_key")
        if not key:
            return False
        payload = {
            "license_key": key,
            "fingerprint": self._fingerprint,
            "timestamp": int(time.time()),
            "integration": INTEGRATION,
            "integration_version": self._integration_version,
            "ha_version": self._ha_version,
        }
        try:
            http_status, result = await self._async_signed_post("validate", payload, timeout)
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("[Hidroelectrica:License] /validate eșuat (rețea) — %s", err)
            return False

        if http_status == 200 and result.get("valid"):
            self._data["last_validation"] = time.time()
            await self._async_save()
            return True

        error = result.get("error") or f"http_{http_status}"
        _LOGGER.warning("[Hidroelectrica:License] /validate respins — %s", error)
        if error in _VALIDATE_DEFINITIVE_ERRORS and not self._revalidating:
            # Licența nu mai e activă pe acest dispozitiv (revocată, mutată, expirată):
            # nu mai așteptăm expirarea cache-ului — cerem imediat statusul real.
            self._revalidating = True
            try:
                await self._async_refresh_status(timeout)
            finally:
                self._revalidating = False
        return False

    def _is_status_cache_valid(self) -> bool:
        """Token-ul de status cached e încă valid (valid_until setat de server)?"""
        if not self._status_token:
            return False
        valid_until = self._status_token.get("valid_until")
        if not valid_until:
            return False
        return time.time() < valid_until

    def _is_within_grace_period(self) -> bool:
        """Cache expirat dar server temporar inaccesibil: 72h licențiat / 24h trial.

        Grația NU extinde o licență expirată real (expires_at depășit) și nu se
        aplică statusurilor expired/unlicensed. La reconectare decide serverul.
        """
        if not self._status_token:
            return False
        valid_until = self._status_token.get("valid_until", 0)
        if valid_until <= 0:
            return False
        now = time.time()
        if now < valid_until:
            return False

        last_status = self._status_token.get("status", "unlicensed")
        if last_status == "licensed":
            expires_at = self.license_expires_at
            if expires_at and now > expires_at:
                return False
            grace_seconds = self._GRACE_LICENSED_SEC
        elif last_status == "trial":
            grace_seconds = self._GRACE_TRIAL_SEC
        else:
            return False
        return now < valid_until + grace_seconds

    # ─── Proprietăți de status (derivate din token-ul serverului) ───

    @property
    def is_trial_valid(self) -> bool:
        """Perioada de evaluare e activă (inclusiv grația la server inaccesibil)."""
        if self._status_token.get("status") != "trial":
            return False
        return self._is_status_cache_valid() or self._is_within_grace_period()

    @property
    def trial_days_remaining(self) -> int:
        """Zilele rămase din trial (de la server)."""
        if self._status_token.get("status") != "trial":
            return 0
        return max(0, int(self._status_token.get("trial_days_remaining", 0)))

    def _local_activation_token(self) -> dict[str, Any] | None:
        """Token-ul de activare local, doar dacă e semnat de server și e al acestui dispozitiv."""
        token = self._data.get("activation_token")
        if not token or not isinstance(token, dict):
            return None
        if not self._token_matches(token) or not self._verify_token_signature(token):
            return None
        return token

    @property
    def is_licensed(self) -> bool:
        """Licență activă: token de activare valid local + serverul nu contrazice."""
        token = self._local_activation_token()
        if token is None:
            return False

        expires_at = token.get("expires_at")
        if expires_at and time.time() > expires_at:
            return False

        if self._status_token and self._is_status_cache_valid():
            # Serverul are ultimul cuvânt
            return self._status_token.get("status") in ("licensed", "trial")

        if self._status_token and not self._is_status_cache_valid():
            if self._is_within_grace_period():
                if not self._cache_expiry_warned:
                    grace_end = self._status_token.get("valid_until", 0) + self._GRACE_LICENSED_SEC
                    _LOGGER.warning(
                        "[Hidroelectrica:License] Server inaccesibil — funcționare în perioada "
                        "de grație (%d ore rămase)",
                        max(0, int((grace_end - time.time()) / 3600)),
                    )
                    self._cache_expiry_warned = True
                return True
            if not self._cache_expiry_warned:
                _LOGGER.warning(
                    "[Hidroelectrica:License] Cache expirat + perioadă de grație depășită "
                    "— licență invalidă. Verificați conexiunea la server."
                )
                self._cache_expiry_warned = True
            return False

        # Fără niciun status de la server (ex: imediat după activare, server căzut)
        return True

    @property
    def is_valid(self) -> bool:
        """Poate funcționa integrarea (licență SAU trial)?

        1. Cache valid + server confirmă 'licensed'/'trial'
        2. Perioadă de grație (server inaccesibil, ultimul status era ok)
        3. Fallback local: token de activare valid
        """
        if self._status_token and self._is_status_cache_valid():
            if self._status_token.get("status") in ("licensed", "trial"):
                return True
        if self._status_token and self._is_within_grace_period():
            if self._status_token.get("status") in ("licensed", "trial"):
                return True
        return self.is_licensed or self.is_trial_valid

    @property
    def has_license(self) -> bool:
        """Dispozitivul a avut o licență (pentru a deosebi „licență expirată" de „trial expirat")."""
        return bool(
            self._local_activation_token()
            or self._status_token.get("license_key")
        )

    @property
    def license_type(self) -> str | None:
        """Tipul licenței: 'perpetual', 'annual', 'semi_annual', 'monthly' sau None."""
        if self._status_token.get("license_type"):
            return self._status_token["license_type"]
        token = self._local_activation_token()
        return token.get("license_type") if token else None

    @property
    def license_key_masked(self) -> str | None:
        """Cheia de licență mascată (ex: HDEL-XXXX-****)."""
        key = self._data.get("license_key")
        if not key or len(key) < 10:
            return key
        return key[:10] + "*" * (len(key) - 10)

    @property
    def activated_at(self) -> float | None:
        """Momentul activării licenței sau None."""
        if self._status_token.get("activated_at"):
            return self._status_token["activated_at"]
        token = self._local_activation_token()
        if token and token.get("activated_at"):
            return token["activated_at"]
        return self._data.get("activated_at")

    @property
    def license_expires_at(self) -> float | None:
        """Momentul expirării licenței sau None (perpetuă / necunoscut)."""
        st = self._status_token
        if st.get("expires_at"):
            return st["expires_at"]
        if st.get("expired_at"):  # răspunsul /check pentru o licență expirată
            return st["expired_at"]
        token = self._local_activation_token()
        return token.get("expires_at") if token else None

    @property
    def status(self) -> str:
        """Starea curentă: 'licensed', 'trial', 'expired' sau 'unlicensed'.

        Prioritizează răspunsul serverului; în grație returnează ultimul status bun.
        """
        if self._status_token and self._is_status_cache_valid():
            server_status = self._status_token.get("status", "unlicensed")
            if server_status in ("licensed", "trial", "expired"):
                return server_status
        if self._status_token and self._is_within_grace_period():
            server_status = self._status_token.get("status", "unlicensed")
            if server_status in ("licensed", "trial"):
                return server_status
        if self.is_licensed:
            return "licensed"
        if self._status_token.get("status") == "expired" or self._local_activation_token():
            return "expired"
        return "unlicensed"

    @property
    def needs_heartbeat(self) -> bool:
        """E timpul pentru o verificare la server (intervalul vine din `valid_until`)."""
        return not self._is_status_cache_valid()

    @property
    def check_interval_seconds(self) -> int:
        """Secunde până la următoarea verificare necesară.

        - Cache valid: până la `valid_until` (max 24h).
        - Cache expirat sau inexistent (ex: rețea indisponibilă la pornirea HA):
          backoff 60s → 5 min → 30 min → 1h, ca să nu bombardăm un server căzut,
          dar nici să lăsăm integrarea blocată ore întregi.
        """
        valid_until = (self._status_token or {}).get("valid_until", 0)
        remaining = valid_until - time.time()
        if remaining > 0:
            return max(1, min(int(remaining), 24 * 3600))
        failures = self._consecutive_failures
        if failures <= 1:
            return 60
        if failures <= 5:
            return 300
        if failures <= 12:
            return 1800
        return 3600

    async def async_heartbeat(self) -> bool:
        """Verificare periodică: /check (dacă cache-ul a expirat) + /validate pentru licențe.

        Returnează is_valid după verificare.
        """
        await self.async_check_status()
        return self.is_valid

    # ─── Activare licență ───

    async def async_activate(self, license_key: str) -> dict[str, Any]:
        """Activează o cheie de licență.

        Returnează {"success": True} sau {"success": False, "error": "<cod>"} cu
        codurile serverului: invalid_key, already_used, expired_key, invalid_hmac
        + locale: invalid_signature, fingerprint_mismatch, network_error, http_<cod>.
        """
        key = license_key.strip().upper()
        payload = {
            "license_key": key,
            "fingerprint": self._fingerprint,
            "timestamp": int(time.time()),
            "integration": INTEGRATION,
        }
        try:
            http_status, result = await self._async_signed_post("activate", payload)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("[Hidroelectrica:License] eroare de rețea la activare — %s", err)
            return {"success": False, "error": "network_error"}

        if http_status != 200:
            _LOGGER.warning(
                "[Hidroelectrica:License] activare eșuată — HTTP %d %s",
                http_status, result.get("detail") or result.get("error") or "",
            )
            return {"success": False, "error": f"http_{http_status}"}

        if not result.get("success"):
            error = result.get("error", "unknown_error")
            _LOGGER.warning("[Hidroelectrica:License] activare eșuată — %s", error)
            return {"success": False, "error": error}

        token = result.get("token") or {}
        if not self._verify_token_signature(token):
            return {"success": False, "error": "invalid_signature"}
        if not self._token_matches(token):
            return {"success": False, "error": "fingerprint_mismatch"}

        self._data["activation_token"] = token
        self._data["license_key"] = key
        self._data["activated_at"] = token.get("activated_at")
        self._data["last_validation"] = time.time()
        # Statusul vechi (trial/expired) nu mai e relevant
        self._status_token = {}
        self._data.pop("status_token", None)
        await self._async_save()

        await self.async_check_status(force=True)
        _LOGGER.info(
            "[Hidroelectrica:License] licență activată cu succes (%s)",
            token.get("license_type", "necunoscut"),
        )
        # Senzorii se recreează cu licența validă
        await self._async_reload_entries()
        return {"success": True}

    # ─── Dezactivare ───

    async def async_deactivate(self) -> dict[str, Any]:
        """Dezactivează licența curentă (pentru mutare pe alt server)."""
        key = self._data.get("license_key")
        if not key:
            return {"success": False, "error": "no_license"}

        payload = {
            "license_key": key,
            "fingerprint": self._fingerprint,
            "timestamp": int(time.time()),
            "integration": INTEGRATION,
        }
        try:
            http_status, result = await self._async_signed_post("deactivate", payload)
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("[Hidroelectrica:License] eroare la dezactivare — %s", err)
            return {"success": False, "error": "network_error"}

        if http_status != 200 or not result.get("success"):
            return {"success": False, "error": result.get("error") or f"http_{http_status}"}

        for k in ("activation_token", "license_key", "last_validation", "activated_at", "status_token"):
            self._data.pop(k, None)
        self._status_token = {}
        await self._async_save()

        await self.async_check_status(force=True)
        _LOGGER.info("[Hidroelectrica:License] licență dezactivată cu succes")
        await self._async_reload_entries()
        return {"success": True}

    # ─── Notificări lifecycle (disable / enable / remove) ───

    async def async_notify_event(self, action: str) -> None:
        """Eveniment de lifecycle către server (fire-and-forget, doar audit).

        Acțiuni: 'integration_disabled', 'integration_enabled', 'integration_removed'.
        """
        payload = {
            "fingerprint": self._fingerprint,
            "timestamp": int(time.time()),
            "action": action,
            "license_key": self._data.get("license_key", ""),
            "integration": INTEGRATION,
        }
        try:
            http_status, result = await self._async_signed_post("notify", payload, timeout=10)
            if http_status != 200 or not result.get("success"):
                _LOGGER.debug(
                    "[Hidroelectrica:License] Notify '%s' refuzat: HTTP %d %s",
                    action, http_status, result.get("error"),
                )
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("[Hidroelectrica:License] Nu s-a putut raporta '%s': %s", action, err)

    # ─── Reload entries ───

    async def _async_reload_entries(self) -> None:
        """Reîncarcă toate entry-urile Hidroelectrica (senzorii se recreează cu noul status)."""
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
        Încearcă toate cheile publice din SERVER_PUBLIC_KEYS_PEM (SEC-03 key rotation).
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

            # Încearcă fiecare cheie publică (key rotation)
            for pem in SERVER_PUBLIC_KEYS_PEM:
                try:
                    public_key = load_pem_public_key(pem.encode())
                    if not isinstance(public_key, Ed25519PublicKey):
                        continue
                    public_key.verify(signature, message)
                    return True
                except Exception:  # noqa: BLE001
                    continue

            _LOGGER.debug("[Hidroelectrica:License] nicio cheie publică nu a validat semnătura")
            return False

        except Exception as err:  # noqa: BLE001
            _LOGGER.debug(
                "[Hidroelectrica:License] verificare semnătură eșuată — %s", err
            )
            return False

    def _compute_request_hmac(self, payload: dict[str, Any]) -> str:
        """Calculează HMAC-SHA256 pentru integritatea request-ului.

        Cheia HMAC = client_secret (v3.1) cu fallback pe fingerprint.
        Mesajul = JSON al payload-ului fără câmpul 'hmac'.
        """
        hmac_key = self._data.get("client_secret") or self._fingerprint
        data = {
            k: v for k, v in payload.items()
            if k not in ("hmac", "hardware_fingerprint", "integration_version", "ha_version")
        }
        msg = json.dumps(data, sort_keys=True).encode()
        return hmac_lib.new(
            hmac_key.encode(),
            msg,
            hashlib.sha256,
        ).hexdigest()

    # ─── Info (pentru UI / diagnostics) ───

    def as_dict(self) -> dict[str, Any]:
        """Informațiile de licență pentru diagnostics/UI (fără secrete)."""
        return {
            "status": self.status,
            "fingerprint": self._fingerprint[:16] + "...",
            "trial_days_remaining": self.trial_days_remaining,
            "license_type": self.license_type,
            "license_key": self.license_key_masked,
            "is_valid": self.is_valid,
            "cache_valid": self._is_status_cache_valid(),
            "consecutive_failures": self._consecutive_failures,
        }
