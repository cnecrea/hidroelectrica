"""Constante pentru integrarea Hidroelectrica România."""

from typing import Final

from homeassistant.const import Platform

DOMAIN = "hidroelectrica"
DOMAIN_TOKEN_STORE = f"{DOMAIN}_token_store"  # Cheie în hass.data pentru token-uri SEW

# ──────────────────────────────────────────────
# Configurare implicită
# ──────────────────────────────────────────────
DEFAULT_UPDATE_INTERVAL = 3600  # Interval de actualizare în secunde (1 oră)
MIN_UPDATE_INTERVAL = 300       # 5 minute
MAX_UPDATE_INTERVAL = 86400     # 24 ore

# ──────────────────────────────────────────────
# Timeout implicit pentru requesturi API (secunde)
# ──────────────────────────────────────────────
API_TIMEOUT = 15

# ──────────────────────────────────────────────
# Limbă implicită
# ──────────────────────────────────────────────
DEFAULT_LANGUAGE = "RO"

# ──────────────────────────────────────────────
# Headere HTTP — Pre-autentificare (SourceType=0)
# ──────────────────────────────────────────────
PRE_AUTH_HEADERS = {
    "SourceType": "0",
    "Content-Type": "application/json",
    "Host": "hidroelectrica-svc.smartcmobile.com",
    "User-Agent": "okhttp/4.9.0",
}

# ──────────────────────────────────────────────
# Headere HTTP — Post-autentificare (SourceType=1)
# ──────────────────────────────────────────────
POST_AUTH_HEADERS = {
    "SourceType": "1",
    "Content-Type": "application/json",
    "Host": "hidroelectrica-svc.smartcmobile.com",
    "User-Agent": "okhttp/4.9.0",
}

# ──────────────────────────────────────────────
# URL-uri API — Base URL (proxy ihidro.ro)
# ──────────────────────────────────────────────
API_BASE = "https://ihidro.ro"

# ──────────────────────────────────────────────
# URL-uri API — Autentificare
# ──────────────────────────────────────────────
ENDPOINT_GET_ID = "/API/UserLogin/GetId"
ENDPOINT_VALIDATE_LOGIN = "/API/UserLogin/ValidateUserLogin"
ENDPOINT_GET_USER_SETTING = "/API/UserLogin/GetUserSetting"
ENDPOINT_GET_MASTER_DATA_STATUS = "/API/UserLogin/GetMasterDataStatus"

# ──────────────────────────────────────────────
# URL-uri API — Utilizare și consum
# ──────────────────────────────────────────────
ENDPOINT_GET_MULTI_METER = "/Service/Usage/GetMultiMeter"
ENDPOINT_GET_USAGE = "/Service/Usage/GetUsageGeneration"

# ──────────────────────────────────────────────
# URL-uri API — Autocitire și date contor
# ──────────────────────────────────────────────
ENDPOINT_GET_WINDOW_DATES_ENC = "/Service/SelfMeterReading/GetWindowDatesENC"
ENDPOINT_GET_WINDOW_DATES = "/Service/SelfMeterReading/GetWindowDates"
ENDPOINT_GET_PODS = "/Service/SelfMeterReading/GetPods"
ENDPOINT_GET_METER_VALUE = "/Service/SelfMeterReading/GetMeterValue"
ENDPOINT_GET_PREVIOUS_METER_READ = "/Service/SelfMeterReading/GetPreviousMeterRead"
ENDPOINT_SUBMIT_SELF_METER_READ = "/Service/SelfMeterReading/SubmitSelfMeterRead"

# ──────────────────────────────────────────────
# URL-uri API — Facturi și plăți
# ──────────────────────────────────────────────
ENDPOINT_GET_BILL = "/Service/Billing/GetBill"
ENDPOINT_GET_BILLING_HISTORY = "/Service/Billing/GetBillingHistoryList"

# ──────────────────────────────────────────────
# URL-uri API — Istoric citiri și contoare
# ──────────────────────────────────────────────
ENDPOINT_GET_METER_COUNTER_SERIES = "/Service/IndexHistory/GetMeterCounterSeries"
ENDPOINT_GET_METER_READ_HISTORY = "/Service/IndexHistory/GetMeterReadHistory"

# ──────────────────────────────────────────────
# Platforme suportate
# ──────────────────────────────────────────────
PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BUTTON]

# ──────────────────────────────────────────────
# Atribuție
# ──────────────────────────────────────────────
ATTRIBUTION = "Date furnizate de Hidroelectrica România"

# ──────────────────────────────────────────────
# Chei de configurare (din homeassistant.const)
# ──────────────────────────────────────────────
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_UPDATE_INTERVAL = "update_interval"
CONF_SELECTED_ACCOUNTS = "selected_accounts"
CONF_ACCOUNT_METADATA = "account_metadata"

# ──────────────────────────────────────────────
# Licențiere
# ──────────────────────────────────────────────
CONF_LICENSE_KEY = "license_key"
LICENSE_DATA_KEY = "hidroelectrica_license_manager"

LICENSE_PURCHASE_URL: Final = "https://hubinteligent.org/licenta/hidroelectrica"
