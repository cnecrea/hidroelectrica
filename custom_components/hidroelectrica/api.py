"""Client API async pentru comunicarea cu Hidroelectrica România (platforma SEW).

Autentificare în 3 pași:
  1. GetId           → key + tokenId
  2. ValidateUserLogin → UserID + SessionToken  (Basic auth = key:tokenId)
  3. Apeluri post-auth → (Basic auth = UserID:SessionToken, SourceType=1)

Retry automat la 401 (re-login + reîncercare o dată).
Persistență token prin export_token_data / inject_token.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import ssl
import time
from datetime import datetime
from typing import Any

from aiohttp import ClientSession, ClientTimeout

from .const import (
    API_BASE,
    API_TIMEOUT,
    DEFAULT_LANGUAGE,
    ENDPOINT_GET_BILL,
    ENDPOINT_GET_BILLING_HISTORY,
    ENDPOINT_GET_ID,
    ENDPOINT_GET_MASTER_DATA_STATUS,
    ENDPOINT_GET_METER_COUNTER_SERIES,
    ENDPOINT_GET_METER_READ_HISTORY,
    ENDPOINT_GET_METER_VALUE,
    ENDPOINT_GET_MULTI_METER,
    ENDPOINT_GET_PODS,
    ENDPOINT_GET_PREVIOUS_METER_READ,
    ENDPOINT_GET_USAGE,
    ENDPOINT_GET_USER_SETTING,
    ENDPOINT_GET_WINDOW_DATES,
    ENDPOINT_GET_WINDOW_DATES_ENC,
    ENDPOINT_SUBMIT_SELF_METER_READ,
    ENDPOINT_VALIDATE_LOGIN,
    POST_AUTH_HEADERS,
    PRE_AUTH_HEADERS,
)

_LOGGER = logging.getLogger(__name__)

# SSL bypass — serverul SEW Hidroelectrica are certificat problematic
_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


class HidroelectricaApiError(Exception):
    """Eroare generică aruncată de API client."""


class HidroelectricaAuthError(HidroelectricaApiError):
    """Eroare de autentificare (credențiale invalide)."""


class HidroelectricaApiClient:
    """Client async pentru API-ul Hidroelectrica România (SEW platform)."""

    def __init__(
        self,
        session: ClientSession,
        username: str,
        password: str,
    ) -> None:
        self._session = session
        self._username = username
        self._password = password

        # Stare autentificare
        self._key: str | None = None
        self._token_id: str | None = None
        self._user_id: str | None = None
        self._session_token: str | None = None
        self._token_obtained_at: float = 0.0

        # Lock pentru a preveni login-uri concurente
        self._auth_lock = asyncio.Lock()
        self._token_generation: int = 0

        self._timeout = ClientTimeout(total=API_TIMEOUT)

    # ══════════════════════════════════════════════
    # Proprietăți publice
    # ══════════════════════════════════════════════

    @property
    def has_token(self) -> bool:
        """Verifică dacă există un session token setat."""
        return self._session_token is not None

    @property
    def token_generation(self) -> int:
        """Generația curentă a token-ului (crește la fiecare login/inject)."""
        return self._token_generation

    @property
    def user_id(self) -> str | None:
        """Returnează UserID-ul obținut la autentificare."""
        return self._user_id

    # ══════════════════════════════════════════════
    # Persistență token (export / inject)
    # ══════════════════════════════════════════════

    def export_token_data(self) -> dict | None:
        """Exportă datele de autentificare pentru persistență.

        Folosit de __init__.py pentru a salva tokenul în hass.data
        și de config_flow pentru a-l transfera la coordinator.
        """
        if self._session_token is None:
            return None
        return {
            "key": self._key,
            "token_id": self._token_id,
            "user_id": self._user_id,
            "session_token": self._session_token,
        }

    def inject_token(self, token_data: dict) -> None:
        """Injectează un token existent (obținut anterior).

        Setează token_obtained_at la momentul curent.
        """
        self._key = token_data.get("key")
        self._token_id = token_data.get("token_id")
        self._user_id = token_data.get("user_id")
        self._session_token = token_data.get("session_token")
        self._token_obtained_at = time.monotonic()
        self._token_generation += 1
        _LOGGER.debug(
            "Token injectat (user_id=%s, gen=%s).",
            self._user_id,
            self._token_generation,
        )

    def invalidate_session(self) -> None:
        """Invalidează sesiunea curentă (forțează re-login la următorul apel)."""
        self._session_token = None
        self._token_obtained_at = 0.0

    # ══════════════════════════════════════════════
    # Autentificare — 3 pași SEW
    # ══════════════════════════════════════════════

    async def async_login(self) -> bool:
        """Autentificare completă în 3 pași.

        Returns:
            True dacă autentificarea a reușit.

        Raises:
            HidroelectricaAuthError: Dacă credențialele sunt invalide.
            HidroelectricaApiError: Dacă un pas tehnic eșuează.
        """
        _LOGGER.debug("[LOGIN] Pornire autentificare pentru '%s'.", self._username)

        # ── Pas 1: GetId ──
        resp_id = await self._post(
            endpoint=ENDPOINT_GET_ID,
            payload={},
            headers=dict(PRE_AUTH_HEADERS),
            label="GetId",
        )

        data_id = self._extract_data(resp_id, "GetId")
        self._key = data_id.get("key")
        self._token_id = data_id.get("tokenId")

        if not self._key or not self._token_id:
            raise HidroelectricaApiError(
                "GetId nu a returnat key/tokenId."
            )

        _LOGGER.debug(
            "[LOGIN] Pas 1 OK: key=%s, tokenId=%s.",
            self._key[:8] if self._key else "?",
            self._token_id[:8] if self._token_id else "?",
        )

        # ── Pas 2: ValidateUserLogin ──
        basic_pre = base64.b64encode(
            f"{self._key}:{self._token_id}".encode()
        ).decode()

        login_headers = {
            **PRE_AUTH_HEADERS,
            "Authorization": f"Basic {basic_pre}",
        }

        login_payload = {
            "deviceType": "MobileApp",
            "OperatingSystem": "Android",
            "UpdatedDate": datetime.now().strftime("%m/%d/%Y %H:%M:%S"),
            "Deviceid": "",
            "SessionCode": "",
            "LanguageCode": DEFAULT_LANGUAGE,
            "password": self._password,
            "UserId": self._username,
            "TFADeviceid": "",
            "OSVersion": 14,
            "TimeOffSet": "120",
            "LUpdHideShow": datetime.now().strftime("%m/%d/%Y %H:%M:%S"),
            "Browser": "NA",
        }

        resp_login = await self._post(
            endpoint=ENDPOINT_VALIDATE_LOGIN,
            payload=login_payload,
            headers=login_headers,
            label="ValidateUserLogin",
        )

        data_login = self._extract_data(resp_login, "ValidateUserLogin")
        table = data_login.get("Table", [])
        if not table:
            raise HidroelectricaAuthError(
                "Autentificare eșuată — 'Table' gol sau lipsă "
                "(credențiale invalide sau cont blocat)."
            )

        first_row = table[0]
        self._user_id = first_row.get("UserID", "")
        self._session_token = first_row.get("SessionToken", "")

        if not self._user_id or not self._session_token:
            raise HidroelectricaAuthError(
                "Autentificare eșuată — UserID sau SessionToken lipsă."
            )

        self._token_obtained_at = time.monotonic()
        self._token_generation += 1

        _LOGGER.debug(
            "[LOGIN] Pas 2 OK: UserID=%s, gen=%s.",
            self._user_id,
            self._token_generation,
        )

        return True

    async def async_ensure_authenticated(self) -> bool:
        """Asigură că avem o sesiune validă (cu lock anti-concurență).

        Dacă session_token există, presupunem că e valid.
        Dacă lipsește, face login complet.
        """
        if self._session_token:
            return True

        async with self._auth_lock:
            # Double-check după obținerea lock-ului
            if self._session_token:
                return True
            return await self.async_login()

    # ══════════════════════════════════════════════
    # Metode private — transport HTTP
    # ══════════════════════════════════════════════

    def _build_auth_headers(self) -> dict[str, str]:
        """Construiește headerele post-autentificare (Basic UserID:SessionToken)."""
        basic = base64.b64encode(
            f"{self._user_id}:{self._session_token}".encode()
        ).decode()
        return {
            **POST_AUTH_HEADERS,
            "Authorization": f"Basic {basic}",
        }

    async def _post(
        self,
        endpoint: str,
        payload: dict,
        headers: dict,
        label: str = "request",
    ) -> dict:
        """POST brut (fără retry pe 401). Returnează JSON-ul decodat."""
        url = f"{API_BASE}{endpoint}"

        _LOGGER.debug("[%s] POST %s", label, url)

        try:
            async with self._session.post(
                url,
                json=payload,
                headers=headers,
                timeout=self._timeout,
                ssl=_SSL_CTX,
            ) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)

                text = await resp.text()
                _LOGGER.error(
                    "[%s] HTTP %s — %s", label, resp.status, text[:500]
                )
                raise HidroelectricaApiError(
                    f"{label}: HTTP {resp.status}"
                )

        except asyncio.TimeoutError as exc:
            _LOGGER.error("[%s] Timeout.", label)
            raise HidroelectricaApiError(f"{label}: Timeout") from exc
        except HidroelectricaApiError:
            raise
        except Exception as exc:
            _LOGGER.error("[%s] Eroare: %s", label, exc)
            raise HidroelectricaApiError(f"{label}: {exc}") from exc

    async def _post_auth(
        self,
        endpoint: str,
        payload: dict,
        label: str = "request",
    ) -> dict | None:
        """POST autentificat cu retry automat la 401.

        1. Asigură token valid
        2. Execută POST
        3. La 401: invalidează sesiunea, re-login, reîncearcă o dată
        """
        await self.async_ensure_authenticated()

        gen_before = self._token_generation
        url = f"{API_BASE}{endpoint}"

        _LOGGER.debug("[%s] POST auth %s", label, url)

        try:
            async with self._session.post(
                url,
                json=payload,
                headers=self._build_auth_headers(),
                timeout=self._timeout,
                ssl=_SSL_CTX,
            ) as resp:
                text = await resp.text()

                if resp.status == 200:
                    return await resp.json(content_type=None)

                if resp.status != 401:
                    _LOGGER.error(
                        "[%s] HTTP %s — %s", label, resp.status, text[:500]
                    )
                    return None

        except asyncio.TimeoutError:
            _LOGGER.error("[%s] Timeout (prima încercare).", label)
            return None
        except Exception as exc:
            _LOGGER.error("[%s] Eroare (prima încercare): %s", label, exc)
            return None

        # ── Retry pe 401 ──
        if self._token_generation != gen_before:
            _LOGGER.debug(
                "[%s] Token deja reînnoit de alt apel (gen %s→%s).",
                label, gen_before, self._token_generation,
            )
        else:
            _LOGGER.warning("[%s] HTTP 401 — se reautentifică.", label)
            self.invalidate_session()
            try:
                await self.async_ensure_authenticated()
            except HidroelectricaApiError:
                _LOGGER.error("[%s] Reautentificare eșuată.", label)
                return None

        try:
            async with self._session.post(
                url,
                json=payload,
                headers=self._build_auth_headers(),
                timeout=self._timeout,
                ssl=_SSL_CTX,
            ) as resp:
                text = await resp.text()
                if resp.status == 200:
                    return await resp.json(content_type=None)
                _LOGGER.error(
                    "[%s] Retry eșuat: HTTP %s — %s",
                    label, resp.status, text[:500],
                )
                return None

        except asyncio.TimeoutError:
            _LOGGER.error("[%s] Timeout (retry).", label)
            return None
        except Exception as exc:
            _LOGGER.error("[%s] Eroare (retry): %s", label, exc)
            return None

    @staticmethod
    def _extract_data(response: dict, label: str) -> dict:
        """Extrage 'result.Data' din răspunsul SEW standard."""
        try:
            return response["result"]["Data"]
        except (KeyError, TypeError) as exc:
            raise HidroelectricaApiError(
                f"{label}: Structură răspuns invalidă (lipsă result.Data)."
            ) from exc

    # ══════════════════════════════════════════════
    # Endpoint: Setări utilizator / conturi
    # ══════════════════════════════════════════════

    async def async_fetch_user_setting(self) -> dict:
        """GetUserSetting — returnează tot JSON-ul brut.

        Conține Table1 (conturi) + Table2 (conturi suplimentare) + alte setări.
        """
        payload = {"UserID": self._user_id}
        resp = await self._post_auth(
            endpoint=ENDPOINT_GET_USER_SETTING,
            payload=payload,
            label="GetUserSetting",
        )
        if resp is None:
            return {}
        return resp

    async def async_fetch_utility_accounts(self) -> list[dict]:
        """Extrage lista conturilor din GetUserSetting.

        Returns:
            Lista de conturi cu contractAccountID, address, pod, etc.
        """
        resp = await self.async_fetch_user_setting()
        data = resp.get("result", {}).get("Data", {})

        accounts: list[dict] = []
        seen: set[str] = set()

        for table_key in ("Table1", "Table2"):
            for entry in data.get(table_key, []) or []:
                uan = entry.get("UtilityAccountNumber", "").strip()
                if uan and uan not in seen:
                    seen.add(uan)
                    accounts.append({
                        "contractAccountID": uan,
                        "accountNumber": entry.get("AccountNumber", ""),
                        "address": entry.get("Address", ""),
                        "pod": entry.get("Pod", ""),
                        "equipmentNo": entry.get("EquipmentNo", ""),
                        "isDefault": entry.get("IsDefaultAccount", False),
                    })

        return accounts

    async def async_fetch_master_data_status(self) -> dict | None:
        """GetMasterDataStatus — starea datelor master."""
        payload = {"UserID": self._user_id}
        return await self._post_auth(
            endpoint=ENDPOINT_GET_MASTER_DATA_STATUS,
            payload=payload,
            label="GetMasterDataStatus",
        )

    # ══════════════════════════════════════════════
    # Endpoint: Contoare și citiri
    # ══════════════════════════════════════════════

    async def async_fetch_multi_meter(
        self,
        utility_account_number: str,
        account_number: str,
    ) -> dict | None:
        """GetMultiMeter — detalii contor(uri) pentru un cont."""
        payload = {
            "MeterType": "E",
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_auth(
            endpoint=ENDPOINT_GET_MULTI_METER,
            payload=payload,
            label=f"GetMultiMeter ({utility_account_number})",
        )

    async def async_fetch_meter_counter_series(
        self,
        utility_account_number: str,
        installation_number: str,
        pod_value: str,
    ) -> dict | None:
        """GetMeterCounterSeries — serii contor pentru istoric.

        Payload EXACT din j0.java (APK decompilare):
          {utilityAccountNumber, InstallationNumber, podValue, LanguageCode}

        NECESITĂ: InstallationNumber și podValue din GetPods!
        """
        payload = {
            "utilityAccountNumber": utility_account_number,
            "InstallationNumber": installation_number,
            "podValue": pod_value,
            "LanguageCode": DEFAULT_LANGUAGE,
        }
        return await self._post_auth(
            endpoint=ENDPOINT_GET_METER_COUNTER_SERIES,
            payload=payload,
            label=f"GetMeterCounterSeries ({utility_account_number})",
        )

    async def async_fetch_meter_read_history(
        self,
        utility_account_number: str,
        installation_number: str,
        pod_value: str,
        serial_numbers: list | None = None,
    ) -> dict | None:
        """GetMeterReadHistory — istoric citiri contor.

        Payload EXACT din h0.java (APK decompilare):
          {utilityAccountNumber, podValue, LanguageCode, InstallationNumber,
           SerialNumber: JSONArray}

        NECESITĂ: InstallationNumber și podValue din GetPods!
        SerialNumber opțional (din GetMeterCounterSeries).
        """
        payload = {
            "utilityAccountNumber": utility_account_number,
            "podValue": pod_value,
            "LanguageCode": DEFAULT_LANGUAGE,
            "InstallationNumber": installation_number,
            "SerialNumber": serial_numbers or [],
        }
        return await self._post_auth(
            endpoint=ENDPOINT_GET_METER_READ_HISTORY,
            payload=payload,
            label=f"GetMeterReadHistory ({utility_account_number})",
        )

    # ══════════════════════════════════════════════
    # Endpoint: Fereastra autocitire
    # ══════════════════════════════════════════════

    async def async_fetch_window_dates_enc(
        self,
        utility_account_number: str,
        account_number: str,
    ) -> dict | None:
        """GetWindowDatesENC — fereastra de autocitire (criptat)."""
        payload = {
            "MeterType": "E",
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_auth(
            endpoint=ENDPOINT_GET_WINDOW_DATES_ENC,
            payload=payload,
            label=f"GetWindowDatesENC ({utility_account_number})",
        )

    async def async_fetch_window_dates(
        self,
        utility_account_number: str,
        account_number: str,
    ) -> dict | None:
        """GetWindowDates — fereastra de autocitire (plain)."""
        payload = {
            "MeterType": "E",
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_auth(
            endpoint=ENDPOINT_GET_WINDOW_DATES,
            payload=payload,
            label=f"GetWindowDates ({utility_account_number})",
        )

    # ══════════════════════════════════════════════
    # Endpoint: Autocitire (self-meter reading)
    # ══════════════════════════════════════════════

    async def async_fetch_pods(
        self,
        utility_account_number: str,
        account_number: str,
    ) -> dict | None:
        """GetPods — puncte de livrare pentru autocitire."""
        payload = {
            "MeterType": "E",
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_auth(
            endpoint=ENDPOINT_GET_PODS,
            payload=payload,
            label=f"GetPods ({utility_account_number})",
        )

    async def async_fetch_previous_meter_read(
        self,
        utility_account_number: str,
        installation_number: str = "",
        pod_value: str = "",
        customer_number: str = "",
    ) -> dict | None:
        """GetPreviousMeterRead — citirea anterioară a contorului.

        Payload EXACT din y0.java (APK decompilare):
          {UtilityAccountNumber, InstallationNumber, podValue, LanguageCode,
           UserID, BasicValue, CustomerNumber, Distributor}

        NECESITĂ: InstallationNumber și podValue din GetPods!
        CustomerNumber = BPNumber din login response.
        Returnează HTTP 400 când fereastra de autocitire este ÎNCHISĂ.
        """
        payload = {
            "UtilityAccountNumber": utility_account_number,
            "InstallationNumber": installation_number,
            "podValue": pod_value,
            "LanguageCode": DEFAULT_LANGUAGE,
            "UserID": self._user_id,
            "BasicValue": "",
            "CustomerNumber": customer_number,
            "Distributor": "",
        }
        return await self._post_auth(
            endpoint=ENDPOINT_GET_PREVIOUS_METER_READ,
            payload=payload,
            label=f"GetPreviousMeterRead ({utility_account_number})",
        )

    async def async_get_meter_value(
        self,
        user_id: str,
        pod_value: str,
        installation_number: str,
        account_number: str,
        usage_entity: list[dict],
    ) -> dict | None:
        """GetMeterValue — validează valoarea citită înainte de submit.

        Payload-ul urmează structura din APK (w0.java, metoda g0):
        {UserId, podValue, InstallationNumber, AccountNumber,
         UsageSelfMeterReadEntity: [...]}
        """
        payload = {
            "UserId": user_id,
            "podValue": pod_value,
            "InstallationNumber": installation_number,
            "AccountNumber": account_number,
            "UsageSelfMeterReadEntity": usage_entity,
        }
        return await self._post_auth(
            endpoint=ENDPOINT_GET_METER_VALUE,
            payload=payload,
            label=f"GetMeterValue ({account_number})",
        )

    async def async_submit_self_meter_read(
        self,
        user_id: str,
        pod_value: str,
        installation_number: str,
        account_number: str,
        usage_entity: list[dict],
    ) -> dict | None:
        """SubmitSelfMeterRead — trimite autocitirea.

        Payload-ul urmează structura din APK (w0.java, metoda i0):
        {UserId, podValue, InstallationNumber, AccountNumber,
         UsageSelfMeterReadEntity: [...]}
        """
        payload = {
            "UserId": user_id,
            "podValue": pod_value,
            "InstallationNumber": installation_number,
            "AccountNumber": account_number,
            "UsageSelfMeterReadEntity": usage_entity,
        }
        return await self._post_auth(
            endpoint=ENDPOINT_SUBMIT_SELF_METER_READ,
            payload=payload,
            label=f"SubmitSelfMeterRead ({account_number})",
        )

    # ══════════════════════════════════════════════
    # Endpoint: Facturi
    # ══════════════════════════════════════════════

    async def async_fetch_bill(
        self,
        utility_account_number: str,
        account_number: str,
    ) -> dict | None:
        """GetBill — factura curentă."""
        payload = {
            "LanguageCode": DEFAULT_LANGUAGE,
            "UserID": self._user_id,
            "IsBillPDF": "0",
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_auth(
            endpoint=ENDPOINT_GET_BILL,
            payload=payload,
            label=f"GetBill ({utility_account_number})",
        )

    async def async_fetch_billing_history(
        self,
        utility_account_number: str,
        account_number: str,
        from_date: str = "",
        to_date: str = "",
    ) -> dict | None:
        """GetBillingHistoryList — istoricul facturilor."""
        payload = {
            "LanguageCode": DEFAULT_LANGUAGE,
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
            "FromDate": from_date,
            "ToDate": to_date,
        }
        return await self._post_auth(
            endpoint=ENDPOINT_GET_BILLING_HISTORY,
            payload=payload,
            label=f"GetBillingHistory ({utility_account_number})",
        )

    # ══════════════════════════════════════════════
    # Endpoint: Consum / generare
    # ══════════════════════════════════════════════

    async def async_fetch_usage(
        self,
        utility_account_number: str,
        account_number: str,
    ) -> dict | None:
        """GetUsageGeneration — istoric consum/generare."""
        payload = {
            "date": "",
            "IsCSR": False,
            "IsUSD": False,
            "Mode": "M",
            "HourlyType": "H",
            "UsageType": "e",
            "UsageOrGeneration": False,
            "GroupId": 0,
            "LanguageCode": DEFAULT_LANGUAGE,
            "Type": "D",
            "MeterNumber": "",
            "IsEnterpriseUser": False,
            "SeasonType": 0,
            "DateFromDaily": "",
            "IsNetUsage": False,
            "TimeOffset": "120",
            "UserType": "Residential",
            "DateToDaily": "",
            "UtilityId": 0,
            "IsLastTendays": False,
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        return await self._post_auth(
            endpoint=ENDPOINT_GET_USAGE,
            payload=payload,
            label=f"GetUsageGeneration ({utility_account_number})",
        )
