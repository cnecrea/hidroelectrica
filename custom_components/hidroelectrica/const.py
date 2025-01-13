"""Constante pentru integrarea Hidroelectrica România."""

DOMAIN = "hidroelectrica"

# Adresa de bază
API_BASE_URL = "https://hidroelectrica-svc.smartcmobile.com"

# Endpoint-uri
API_URL_GET_ID = f"{API_BASE_URL}/API/UserLogin/GetId"
API_URL_VALIDATE_LOGIN = f"{API_BASE_URL}/API/UserLogin/ValidateUserLogin"
API_URL_GET_USER_SETTING = f"{API_BASE_URL}/API/UserLogin/GetUserSetting"
API_GET_MULTI_METER = f"{API_BASE_URL}/Service/Usage/GetMultiMeter"
API_GET_MULTI_METER_CURRENT = f"{API_BASE_URL}/Service/SelfMeterReading/GetMeterValue"
API_GET_MULTI_METER_READ_DATE = f"{API_BASE_URL}/Service/SelfMeterReading/GetWindowDatesENC"
API_URL_GET_BILL = f"{API_BASE_URL}/Service/Billing/GetBill"
API_URL_GET_BILL_HISTORY = f"{API_BASE_URL}/Service/Billing/GetBillingHistoryList"
API_URL_GET_USAGE_GENERATION = f"{API_BASE_URL}/Service/Usage/GetUsageGeneration"

# Valori implicite
DEFAULT_UPDATE_INTERVAL = 3600  # în secunde (o oră)
MIN_UPDATE_INTERVAL = 300       # 5 minute
MAX_UPDATE_INTERVAL = 86400     # 24 ore

# Chei de configurare
CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_UPDATE_INTERVAL = "update_interval"

# Mesaje și atribute
ATTRIBUTION = "Date furnizate de Hidroelectrica România"
