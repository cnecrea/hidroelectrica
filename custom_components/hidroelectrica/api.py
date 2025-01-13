"""
Modul care definește clasa HidroelectricaAPI pentru apeluri la API-ul Hidroelectrica România.

- Folosim requests (sincron).
- Fiecare endpoint are propria metodă.
- Stocăm datele brute din ValidateUserLogin + GetUserSetting pentru a le putea expune către coordinator.
- Cu metoda login_if_needed(), evităm logarea repetată la fiecare refresh (dacă deja avem session_token).
"""

import logging
import requests
import base64
import json
import urllib3
from datetime import datetime

from .const import (
    API_BASE_URL,
    API_URL_GET_ID,
    API_URL_VALIDATE_LOGIN,
    API_URL_GET_USER_SETTING,
    API_GET_MULTI_METER,
    API_GET_MULTI_METER_CURRENT,
    API_GET_MULTI_METER_READ_DATE,
    API_URL_GET_BILL,
    API_URL_GET_BILL_HISTORY,
    API_URL_GET_USAGE_GENERATION,
)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

_LOGGER = logging.getLogger(__name__)


class HidroelectricaAPI:
    def __init__(self, username: str, password: str):
        self._username = username
        self._password = password

        self._user_id = None
        self._session_token = None
        self._auth_header = None
        self._token_id = None
        self._key = None

        self._utility_accounts = []

        # Sesiune requests
        self._session = requests.Session()
        self._session.verify = False

        # Date brute reținute pentru coordinator:
        # - rândurile din ValidateUserLogin (Table)
        self._validate_user_login_rows = []  # list[dict]
        # - tot JSON-ul brut primit la get_user_setting
        self._raw_user_setting_data = {}      # dict complet

    def login_if_needed(self) -> None:
        """
        Face login doar dacă _session_token e None.
        Evităm logarea repetitivă la fiecare apel.
        """
        if self._session_token:
            _LOGGER.debug("Avem deja session_token, deci nu mai refacem login.")
            return

        # Altfel, facem login complet
        self.login()

    def login(self) -> None:
        """
        Secvența clasică de autentificare la Hidroelectrica:
          1. API_URL_GET_ID (key + token_id)
          2. API_URL_VALIDATE_LOGIN (username/password)
          3. get_user_setting => conturile
        """
        _LOGGER.debug("=== HIDRO: Începem login pentru user '%s'... ===", self._username)

        # 1. GetId
        resp_get_id = self._post_request(
            API_URL_GET_ID,
            payload={},
            headers={
                "SourceType": "0",
                "Content-Type": "application/json",
                "Host": "hidroelectrica-svc.smartcmobile.com",
                "User-Agent": "okhttp/4.9.0",
            },
            descriere="Obținere ID utilizator (GetId)"
        )
        self._key = resp_get_id["result"]["Data"]["key"]
        self._token_id = resp_get_id["result"]["Data"]["tokenId"]

        _LOGGER.debug("Am obținut key=%s, token_id=%s", self._key, self._token_id)

        # 2. Validate Login
        auth = base64.b64encode(f"{self._key}:{self._token_id}".encode()).decode()
        login_headers = {
            "SourceType": "0",
            "Content-Type": "application/json",
            "Host": "hidroelectrica-svc.smartcmobile.com",
            "User-Agent": "okhttp/4.9.0",
            "Authorization": f"Basic {auth}"
        }
        login_payload = {
            "deviceType": "MobileApp",
            "OperatingSystem": "Android",
            "UpdatedDate": datetime.now().strftime("%m/%d/%Y %H:%M:%S"),
            "Deviceid": "",
            "SessionCode": "",
            "LanguageCode": "RO",
            "password": self._password,
            "UserId": self._username,
            "TFADeviceid": "",
            "OSVersion": 14,
            "TimeOffSet": "120",
            "LUpdHideShow": datetime.now().strftime("%m/%d/%Y %H:%M:%S"),
            "Browser": "NA"
        }
        resp_login = self._post_request(
            API_URL_VALIDATE_LOGIN,
            payload=login_payload,
            headers=login_headers,
            descriere="Autentificare (ValidateUserLogin)"
        )

        # 2.1. Citim rândurile din "Table"
        self._validate_user_login_rows = resp_login["result"]["Data"].get("Table", [])
        if not self._validate_user_login_rows:
            raise Exception("Eroare: Lipsește 'Table' sau e gol în ValidateUserLogin.")

        first_user_entry = self._validate_user_login_rows[0]
        self._user_id = first_user_entry["UserID"]
        self._session_token = first_user_entry["SessionToken"]

        _LOGGER.debug("UserID=%s, SessionToken=%s", self._user_id, self._session_token)

        encoded_auth = base64.b64encode(f"{self._user_id}:{self._session_token}".encode()).decode()
        self._auth_header = {
            "SourceType": "1",
            "Content-Type": "application/json",
            "Host": "hidroelectrica-svc.smartcmobile.com",
            "User-Agent": "okhttp/4.9.0",
            "Authorization": f"Basic {encoded_auth}"
        }

        # 3. get_user_setting => conturi
        resp_userset = self._get_utility_accounts()  # stocăm și în self._utility_accounts
        self._raw_user_setting_data = resp_userset   # tot JSON-ul brut

        _LOGGER.debug(
            "=== HIDRO: Login finalizat pentru '%s'. Identificate %d cod(uri) de încasare. ===",
            self._username, len(self._utility_accounts)
        )

    def _get_utility_accounts(self):
        """
        Apel la GetUserSetting, returnează tot JSON-ul brut.
        De asemenea, populăm self._utility_accounts cu conturile filtrate.
        """
        payload = {"UserID": self._user_id}
        resp = self._post_request(
            API_URL_GET_USER_SETTING,
            payload=payload,
            headers=self._auth_header,
            descriere="Setări Utilizator (GetUserSetting)"
        )

        data = resp["result"]["Data"]
        accounts = []
        if "Table1" in data and data["Table1"]:
            accounts.extend(data["Table1"])
        if "Table2" in data and data["Table2"]:
            for entry in data["Table2"]:
                if entry not in accounts:
                    accounts.append(entry)

        filtered = []
        for acc in accounts:
            if acc.get("UtilityAccountNumber"):
                filtered.append(
                    {
                        "AccountNumber": acc.get("AccountNumber"),
                        "UtilityAccountNumber": acc.get("UtilityAccountNumber"),
                        "Address": acc.get("Address"),
                        "IsDefaultAccount": acc.get("IsDefaultAccount"),
                    }
                )
        self._utility_accounts = filtered
        return resp

    # ---------------------------------------------------------------------
    # Metode "get_validate_user_login_data" & "get_raw_user_setting_data"
    # ---------------------------------------------------------------------
    def get_validate_user_login_data(self):
        """
        Returnează list[dict], conținutul integral al "Table" 
        din ValidateUserLogin (resp_login).
        """
        return self._validate_user_login_rows

    def get_raw_user_setting_data(self):
        """
        Returnează JSON-ul brut (dict) primit la GetUserSetting.
        """
        return self._raw_user_setting_data

    def get_utility_accounts(self):
        """
        Returnează lista conturilor extrase deja (filtered).
        """
        return self._utility_accounts

    def login_if_needed(self) -> None:
        """
        Face login doar dacă _session_token e None (sau considerăm expirat).
        """
        if self._session_token:
            _LOGGER.debug("Avem deja session_token, nu mai refacem login.")
            return
        self.login()

    def close(self):
        """
        Închide sesiunea requests (opțional).
        """
        self._session.close()
        _LOGGER.debug("Sesiunea Hidroelectrica închisă.")

    # ---------------------------------------------------------------------
    #  Metode pentru restul endpoint-urilor 
    # ---------------------------------------------------------------------
    def get_multi_meter_details(self, utility_account_number, account_number):
        payload = {
            "MeterType": "E",
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number
        }
        return self._post_request(
            API_GET_MULTI_METER,
            payload=payload,
            headers=self._auth_header,
            descriere="GetMultiMeter (Detalii contor)"
        )

    def get_current_meter_value(self, utility_account_number, account_number):
        payload = {
            "MeterType": "E",
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number
        }
        return self._post_request(
            API_GET_MULTI_METER_CURRENT,
            payload=payload,
            headers=self._auth_header,
            descriere="GetMeterValue (Index contor)"
        )

    def get_window_dates_enc(self, utility_account_number, account_number):
        payload = {
            "MeterType": "E",
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number
        }
        return self._post_request(
            API_GET_MULTI_METER_READ_DATE,
            payload=payload,
            headers=self._auth_header,
            descriere="GetWindowDatesENC (Fereastra citire)"
        )

    def get_current_bill(self, utility_account_number, account_number):
        payload = {
            "LanguageCode": "RO",
            "UserID": self._user_id,
            "IsBillPDF": "0",
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number
        }
        return self._post_request(
            API_URL_GET_BILL,
            payload=payload,
            headers=self._auth_header,
            descriere="GetBill (Factura curentă)"
        )

    def get_bill_history(self, utility_account_number, account_number, from_date, to_date):
        payload = {
            "LanguageCode": "RO",
            "UserID": self._user_id,
            "UtilityAccountNumber": utility_account_number,
            "AccountNumber": account_number,
            "FromDate": from_date,
            "ToDate": to_date
        }
        return self._post_request(
            API_URL_GET_BILL_HISTORY,
            payload=payload,
            headers=self._auth_header,
            descriere="GetBillingHistoryList (Istoric Facturi)"
        )

    def get_usage_generation(self, utility_account_number, account_number):
        payload = {
            "date": "",
            "IsCSR": False,
            "IsUSD": False,
            "Mode": "M",
            "HourlyType": "H",
            "UsageType": "e",
            "UsageOrGeneration": False,
            "GroupId": 0,
            "LanguageCode": "RO",
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
            "AccountNumber": account_number
        }
        return self._post_request(
            API_URL_GET_USAGE_GENERATION,
            payload=payload,
            headers=self._auth_header,
            descriere="GetUsageGeneration (Istoric consum/generare)"
        )

    def _post_request(self, url, payload, headers, descriere="Fără descriere"):
        """
        Metodă internă care face un POST și returnează JSON-ul decodat.
        Dacă primim 401, încercăm re-autentificare o dată și refacem cererea,
        dar doar dacă UAN încă există în noile conturi.
        """
        _LOGGER.debug("=== Cerere POST către %s (%s) ===", url, descriere)

        # 1. Prima încercare
        response = self._session.post(url, json=payload, headers=headers, timeout=10)
        if response.status_code == 401:
            _LOGGER.warning("Am primit 401 la %s, încerc re-autentificare...", descriere)
            # Invalidăm token-ul curent
            self._session_token = None
            # Apelăm login_if_needed(), care va seta un nou session_token
            self.login_if_needed()

            # Facem refresh la conturile după re-login
            # (Poate userul actual nu mai are acces la UAN-ul cerut)
            new_accounts = self.get_utility_accounts()  # reîncărcăm
            # Observăm dacă payload-ul conține "UtilityAccountNumber" + "AccountNumber"
            # (și vrei să verifici că există încă)
            # => Presupunem că, la majoritatea endpoint-urilor, avem "UtilityAccountNumber" în payload
            new_uan = payload.get("UtilityAccountNumber")
            if new_uan:
                # Vedem dacă UAN există în new_accounts
                has_uan = any(a["UtilityAccountNumber"] == new_uan for a in new_accounts)
                if not has_uan:
                    # userul nu mai are acces la acest UAN => ridicăm excepție direct
                    raise Exception(
                        f"Userul nu mai are acces la UAN={new_uan}. "
                        f"Re-login a reușit, dar contul nu mai figurează în get_utility_accounts()."
                    )

            # A doua încercare (retry)
            response = self._session.post(url, json=payload, headers=self._auth_header, timeout=10)

        # După eventualul retry, dacă tot nu e 200, ridicăm excepție
        if response.status_code != 200:
            raise Exception(f"Eroare la cererea {descriere}: {response.status_code}, {response.text}")

        return response.json()


if __name__ == "__main__":
    """
    Test local.
    """
    api = HidroelectricaAPI("nume_utilizator", "parola")
    try:
        # login_if_needed() => va apela login() doar dacă e necesar
        api.login_if_needed()
        conturi = api.get_utility_accounts()
        print("Coduri de încasare:", conturi)

        rows = api.get_validate_user_login_data()
        print("Rânduri ValidateUserLogin:", rows)

        raw_userset = api.get_raw_user_setting_data()
        print("Raw userSetting:", json.dumps(raw_userset, indent=2))

        # A doua oară, nu se mai face login
        api.login_if_needed()

    finally:
        api.close()
