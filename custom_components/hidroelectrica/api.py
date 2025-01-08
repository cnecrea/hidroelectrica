"""Manager pentru gestionarea cererilor către API-ul Hidroelectrica România."""

import logging
import async_timeout
from aiohttp import BasicAuth, ClientSession
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_URL_GET_ID,
    API_URL_VALIDATE_LOGIN,
    API_URL_GET_USER_SETTING,
    API_URL_GET_BILL,
    API_URL_GET_BILL_HISTORY,
    API_URL_GET_MULTI_METER,
    API_URL_GET_USAGE_GENERATION,
)

_LOGGER = logging.getLogger(__name__)


class ExpiredTokenError(Exception):
    """Excepție ridicată când API-ul semnalează un token expirat/invalid (ex. 401)."""
    pass


class ApiManager:
    """Manager pentru gestionarea autentificării și cererilor API."""

    def __init__(self, hass: HomeAssistant, username: str, password: str):
        """Inițializează managerul API."""
        self.hass = hass
        self.username = username
        self.password = password
        self.session: ClientSession = async_get_clientsession(hass)
        self.token_id = None
        self.key = None
        self.user_id = None
        self.session_token = None

    async def async_login(self):
        """Realizează autentificarea cu API-ul."""
        _LOGGER.debug("Începe autentificarea utilizatorului %s", self.username)

        # 1. Cerere pentru token și cheie
        async with async_timeout.timeout(10):
            response = await self.session.post(
                API_URL_GET_ID,
                headers={
                    "SourceType": "0",
                    "Content-Type": "application/json",
                    "User-Agent": "okhttp/4.9.0",
                },
                json={},
            )
            data = await response.json()
            self._check_for_expiration(data)
            self.token_id = data["result"]["Data"]["tokenId"]
            self.key = data["result"]["Data"]["key"]
            _LOGGER.debug("Token și cheie obținute: %s, %s", self.token_id, self.key)

        # 2. Cerere pentru autentificare
        auth = BasicAuth(self.key, self.token_id)
        async with async_timeout.timeout(10):
            response = await self.session.post(
                API_URL_VALIDATE_LOGIN,
                headers={
                    "SourceType": "0",
                    "Content-Type": "application/json",
                    "Authorization": auth.encode(),
                    "User-Agent": "okhttp/4.9.0",
                },
                json={
                    "deviceType": "MobileApp",
                    "OperatingSystem": "Android",
                    "LanguageCode": "RO",
                    "password": self.password,
                    "UserId": self.username,
                },
            )
            data = await response.json()
            self._check_for_expiration(data)
            user_data = data["result"]["Data"]["Table"][0]
            self.user_id = user_data["UserID"]
            self.session_token = user_data["SessionToken"]
            _LOGGER.debug("Autentificare reușită pentru utilizatorul %s", self.username)

    def _check_for_expiration(self, data: dict):
        """
        Verifică dacă răspunsul semnalează un token invalid/expirat,
        de obicei 'status_code' == 401 semnifică 'UnAuthorized Access'.
        """
        status_code = data.get("status_code", 0)
        if status_code == 401:
            # Serverul semnalează 'UnAuthorized Access'
            raise ExpiredTokenError("Sesiune expirată sau neautorizată (401).")

        # Dacă API-ul ar semnala altfel (ex. "errorMessage" = "Session expired"),
        # poți verifica aici și să ridici ExpiredTokenError.

    def _get_authenticated_headers(self):
        """Generează anteturile de autentificare pentru cererile API."""
        auth = BasicAuth(str(self.user_id), self.session_token)
        return {
            "SourceType": "1",
            "Content-Type": "application/json",
            "Host": "hidroelectrica-svc.smartcmobile.com",
            "Authorization": auth.encode(),
            "User-Agent": "okhttp/4.9.0",
        }

    async def _async_get_user_settings(self):
        """Obține setările utilizatorului."""
        payload = {"UserID": self.user_id}
        _LOGGER.debug("Cerere GET_USER_SETTING cu payload: %s", payload)

        async with async_timeout.timeout(10):
            response = await self.session.post(
                API_URL_GET_USER_SETTING,
                headers=self._get_authenticated_headers(),
                json=payload,
            )
            data = await response.json()
            self._check_for_expiration(data)

        status_code = data.get("status_code", 0)
        if status_code == 200:
            _LOGGER.debug("Răspuns GET_USER_SETTING: OK")
        else:
            _LOGGER.error(
                "Eroare GET_USER_SETTING: Cod status %s, Răspuns complet: %s",
                status_code,
                data,
            )
        return data

    async def _async_get_bill(self, account_number, utility_account_number):
        """Obține factura curentă."""
        payload = {
            "LanguageCode": "RO",
            "UserID": self.user_id,
            "IsBillPDF": "0",
            "AccountNumber": account_number,
            "UtilityAccountNumber": utility_account_number,
        }
        _LOGGER.debug("Cerere GET_BILL cu payload: %s", payload)

        async with async_timeout.timeout(10):
            response = await self.session.post(
                API_URL_GET_BILL,
                headers=self._get_authenticated_headers(),
                json=payload,
            )
            data = await response.json()
            self._check_for_expiration(data)

        status_code = data.get("status_code", 0)
        if status_code == 200:
            _LOGGER.debug("Răspuns GET_BILL: OK")
        else:
            _LOGGER.error(
                "Eroare GET_BILL: Cod status %s, Răspuns complet: %s",
                status_code,
                data,
            )
        return data

    async def _async_get_bill_history(
        self, account_number, utility_account_number, from_date, to_date
    ):
        """Obține istoricul facturilor."""
        payload = {
            "LanguageCode": "RO",
            "UserID": self.user_id,
            "AccountNumber": account_number,
            "UtilityAccountNumber": utility_account_number,
            "FromDate": from_date,
            "ToDate": to_date,
        }
        _LOGGER.debug("Cerere GET_BILL_HISTORY cu payload: %s", payload)

        async with async_timeout.timeout(10):
            response = await self.session.post(
                API_URL_GET_BILL_HISTORY,
                headers=self._get_authenticated_headers(),
                json=payload,
            )
            data = await response.json()
            self._check_for_expiration(data)

        status_code = data.get("status_code", 0)
        if status_code == 200:
            _LOGGER.debug("Răspuns GET_BILL_HISTORY: OK")
        else:
            _LOGGER.error(
                "Eroare GET_BILL_HISTORY: Cod status %s, Răspuns complet: %s",
                status_code,
                data,
            )
        return data

    async def _async_get_multi_meter(self, account_number, utility_account_number):
        """Obține informații despre contoare."""
        payload = {
            "MeterType": "E",
            "UserID": self.user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
        }
        _LOGGER.debug("Cerere GET_MULTI_METER cu payload: %s", payload)

        async with async_timeout.timeout(10):
            response = await self.session.post(
                API_URL_GET_MULTI_METER,
                headers=self._get_authenticated_headers(),
                json=payload,
            )
            data = await response.json()
            self._check_for_expiration(data)

        status_code = data.get("status_code", 0)
        if status_code == 200:
            _LOGGER.debug("Răspuns GET_MULTI_METER: OK")
        else:
            _LOGGER.error(
                "Eroare GET_MULTI_METER: Cod status %s, Răspuns complet: %s",
                status_code,
                data,
            )
        return data

    async def _async_get_usage_generation(self, meter_number):
        """Obține istoricul consumului."""
        payload = {
            "UserID": self.user_id,
            "MeterNumber": meter_number,
            "LanguageCode": "RO",
        }
        _LOGGER.debug("Cerere GET_USAGE_GENERATION cu payload: %s", payload)

        async with async_timeout.timeout(10):
            response = await self.session.post(
                API_URL_GET_USAGE_GENERATION,
                headers=self._get_authenticated_headers(),
                json=payload,
            )
            data = await response.json()
            self._check_for_expiration(data)

        status_code = data.get("status_code", 0)
        if status_code == 200:
            _LOGGER.debug("Răspuns GET_USAGE_GENERATION: OK")
        else:
            _LOGGER.error(
                "Eroare GET_USAGE_GENERATION: Cod status %s, Răspuns complet: %s",
                status_code,
                data,
            )
        return data
