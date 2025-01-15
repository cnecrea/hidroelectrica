"""
Definirea senzorilor pentru integrarea Hidroelectrica România.
"""

import logging
import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.sensor import SensorStateClass
from .const import DOMAIN, ATTRIBUTION

_LOGGER = logging.getLogger(__name__)

def _extract_year_from_dd_mm_yyyy(date_str: str) -> int:
    """
    Helper pentru a extrage anul dintr-un string gen "19/07/2023".
    Returnează un int (ex: 2023). În caz de eroare, returnează 0.
    """
    if not date_str or len(date_str.split("/")) < 3:
        return 0
    try:
        day, month, year = date_str.split("/")
        return int(year)
    except ValueError:
        return 0

async def async_setup_entry(hass, entry, async_add_entities):
    """
    Punctul de intrare pentru configurarea platformei 'sensor' în Home Assistant.
    """
    stored_data = hass.data[DOMAIN].get(entry.entry_id)
    if not stored_data:
        _LOGGER.error("Nu am găsit date pentru entry_id=%s", entry.entry_id)
        return

    coordinator = stored_data.get("coordinator")
    if not coordinator:
        _LOGGER.error("Nu am găsit coordinator pentru entry_id=%s", entry.entry_id)
        return

    entities = []

    # Pentru fiecare cont (uan, acc_no) creăm senzorii de bază:
    for account_info in coordinator.data.get("utility_accounts", []):
        uan = account_info["UtilityAccountNumber"]
        acc_no = account_info["AccountNumber"]

        # Senzorii de bază (exemplu, dacă ai deja aceste clase definite)
        entities.append(DateContractSensor(coordinator, entry, uan, acc_no))
        entities.append(IndexCurentSensor(coordinator, entry, uan, acc_no))
        entities.append(FacturaRestantaSensor(coordinator, entry, uan, acc_no))

        # -------------------------------------------------
        # 1. Creăm senzori ISTORIC FACTURI, câte unul per an
        # -------------------------------------------------
        # Protejăm accesul la "get_billing_history_list" prin fallback la {}
        facturi_data = coordinator.data["accounts_data"][uan].get("get_billing_history_list", {})
        result_block = facturi_data.get("result", {})
        facturi_list = result_block.get("objBillingPaymentHistoryEntity", [])

        if not facturi_list:
            _LOGGER.debug("Nu există plăți (sau objBillingPaymentHistoryEntity e gol) pentru UAN=%s", uan)
        else:
            # Grupăm plățile după an (extrag an din "paymentDate": dd/MM/yyyy)
            plati_pe_ani = {}
            for f in facturi_list:
                payment_date_str = f.get("paymentDate", "")  # ex: "19/07/2023"
                an = _extract_year_from_dd_mm_yyyy(payment_date_str)
                if an not in plati_pe_ani:
                    plati_pe_ani[an] = []
                plati_pe_ani[an].append(f)

            # Cream câte un sensor pt fiecare an găsit
            for an, lista_plati in plati_pe_ani.items():
                entities.append(ArhivaPlatiSensor(
                    coordinator,
                    entry,
                    uan,
                    acc_no,
                    an,
                    lista_plati
                ))

        # -------------------------------------------------
        # 2. Creăm senzori ISTORIC CONSUM, câte unul per an
        # -------------------------------------------------
        consum_data = coordinator.data["accounts_data"][uan].get("get_usage_generation", {})
        usage_result = consum_data.get("result", {})
        data_block = usage_result.get("Data", {})
        consum_list = data_block.get("objUsageGenerationResultSetTwo", [])

        if not consum_list:
            _LOGGER.debug("Nu există date de consum (sau objUsageGenerationResultSetTwo e gol) pentru UAN=%s", uan)
        else:
            consum_pe_ani = {}
            for c in consum_list:
                usage_date_str = c.get("UsageDate", "")  # ex: "31/10/2024"
                an_c = _extract_year_from_dd_mm_yyyy(usage_date_str)
                if an_c not in consum_pe_ani:
                    consum_pe_ani[an_c] = []
                consum_pe_ani[an_c].append(c)

    async_add_entities(entities, update_before_add=True)



# ------------------------------------------------------------------------
# Baza pentru senzori
# ------------------------------------------------------------------------
class HidroelectricaBaseSensor(CoordinatorEntity, SensorEntity):
    """
    Clasă de bază pentru senzori Hidroelectrica.
    Conține logica comună pentru a se lega la Coordinator, 
    și definește un device_info pentru contul specific.
    """

    def __init__(self, coordinator, config_entry, utility_account_number, account_number):
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._uan = utility_account_number
        self._acc_no = account_number
        self._attr_entity_id = None  # îl setăm în subclase

    @property
    def entity_id(self):
        """Returnează identificatorul explicit al entității."""
        return self._attr_entity_id

    @entity_id.setter
    def entity_id(self, value):
        """Setează identificatorul explicit al entității."""
        self._attr_entity_id = value

    @property
    def device_info(self):
        """Grupăm senzorii într-un "device" pentru fiecare UAN."""
        val_data = self._validate_login_data()
        set_data = self._get_user_setting_data()
        return {
            "identifiers": {(DOMAIN, f"{self._config_entry.entry_id}_{self._uan}")},
            "name": f"Hidroelectrica România - {val_data.get('Address', 'N/A').split(', ')[1].capitalize()}, {val_data.get('Address', 'N/A').split(', ')[0]}, {val_data.get('Address', 'N/A').split(', ')[2].capitalize()} ({self._uan})",
            "manufacturer": "Ciprian Nicolae (cnecrea)",
            "model": "Hidroelectrica România",
            "entry_type": "service",  # sau "device"
        }

    def _acc_data(self):
        """Helper pentru sub-dicționarul acestui UAN în coordinator."""
        all_acc_data = self.coordinator.data.get("accounts_data", {})
        return all_acc_data.get(self._uan, {})

    def _validate_login_data(self):
        """Returnează sub-dicționarul validate_user_login (API_URL_VALIDATE_LOGIN)."""
        return self._acc_data().get("validate_user_login", {})

    def _get_user_setting_data(self):
        """Returnează sub-dicționarul get_user_setting (API_URL_GET_USER_SETTING)."""
        return self._acc_data().get("get_user_setting", {})

# ------------------------------------------------------------------------
# DateContractSensor
# ------------------------------------------------------------------------
class DateContractSensor(HidroelectricaBaseSensor):
    """
    Senzor care afișează date contractuale.
    - Folosește: validate_user_login (API_URL_VALIDATE_LOGIN) și get_user_setting (API_URL_GET_USER_SETTING)
    """
    def __init__(self, coordinator, config_entry, utility_account_number, account_number):
        super().__init__(coordinator, config_entry, utility_account_number, account_number)
        self._attr_name = "Date contract"
        self._attr_unique_id = f"{config_entry.entry_id}_{utility_account_number}_date_contract"
        self._attr_entity_id = f"sensor.{DOMAIN}_date_contract_{utility_account_number}"
        self._attr_icon = "mdi:file-document-edit-outline"

    @property
    def entity_id(self):
        """Returnează identificatorul explicit al entității."""
        return self._attr_entity_id

    @entity_id.setter
    def entity_id(self, value):
        """Setează identificatorul explicit al entității."""
        self._attr_entity_id = value

    @property
    def native_value(self):
        """
        Exemplu: Afișăm 'UserName' din validate_user_login ca stare principală (sau alt câmp dorit).
        """
        val_data = self._validate_login_data()
        if not val_data:
            return None
        return val_data.get("BPNumber", "N/A")

    @property
    def extra_state_attributes(self):
        """
        Ca atribute secundare, combinăm info din validate_user_login și get_user_setting.
        """
        val_data = self._validate_login_data()
        set_data = self._get_user_setting_data()

        return {
            "Numele și prenumele": f"{val_data.get('FirstName', 'N/A').capitalize()} {val_data.get('LastName', 'N/A').capitalize()}",
            "Telefon de contact": val_data.get("PrimeryContactNumber", "N/A"),
            "Număr cont utilitate": val_data.get("UtilityAccountNumber", "N/A"),
            "Cod loc de consum (NLC)": val_data.get("BPNumber", "N/A"),
            "Tip client": val_data.get("CustomerTypeDesc", "N/A"),
            "Adresa de consum": f"Strada {val_data.get('Address', 'N/A').split(', ')[1].capitalize()}, {val_data.get('Address', 'N/A').split(', ')[0]}",
            "Localitate": val_data.get("CityName", "N/A").capitalize(),
            "Țară": val_data.get("Country", "N/A").capitalize(),
            "Ultima actualizare de date": set_data.get("LastUpdate", "N/A"),
            "attribution": ATTRIBUTION,
        }

    def _validate_login_data(self):
        """Returnează sub-dicționarul validate_user_login (API_URL_VALIDATE_LOGIN)."""
        return self._acc_data().get("validate_user_login", {})

    def _get_user_setting_data(self):
        """Returnează sub-dicționarul get_user_setting (API_URL_GET_USER_SETTING)."""
        return self._acc_data().get("get_user_setting", {})


# ------------------------------------------------------------------------
# IndexCurentSensor
# ------------------------------------------------------------------------
class IndexCurentSensor(HidroelectricaBaseSensor):
    """
    Senzor care afișează indexul curent.
    - Folosește: get_multi_meter (API_GET_MULTI_METER), get_meter_value (API_GET_MULTI_METER_CURRENT),
                get_window_dates_enc (API_GET_MULTI_METER_READ_DATE)
    """

    def __init__(self, coordinator, config_entry, utility_account_number, account_number):
        super().__init__(coordinator, config_entry, utility_account_number, account_number)
        self._attr_name = "Index curent"
        self._attr_unique_id = f"{config_entry.entry_id}_{utility_account_number}_index_curent"
        self._attr_entity_id = f"sensor.{DOMAIN}_index_curent_{utility_account_number}"
        self._attr_icon = "mdi:gauge"

    @property
    def entity_id(self):
        """Returnează identificatorul explicit al entității."""
        return self._attr_entity_id

    @entity_id.setter
    def entity_id(self, value):
        """Setează identificatorul explicit al entității."""
        self._attr_entity_id = value

    @property
    def native_value(self):
        """
        Exemplu: afișăm 'IndexValue' din get_meter_value.
        """
        meter_data = self._get_meter_value_data()
        if not meter_data:
            return None

        # Dacă result.responsestatus=0 => "No Record Found" => return 0
        if meter_data.get("result", {}).get("responsestatus") == 0:
            return 0

        return meter_data.get("IndexValue", 0)

    @property
    def extra_state_attributes(self):
        """
        Ca atribute, aducem date din:
        - get_multi_meter (ex. "MeterNumber")
        - get_window_dates_enc (ex. "Is_Window_Open")
        """
        multi_data = self._get_multi_meter_data()
        meter_curent = self._get_meter_value_data() # nu sunt date
        window_data = self._get_window_dates_data()
        usage_gen = self._get_usage_generation()
            
        #_LOGGER.debug("multi_data: %s", multi_data)
        #_LOGGER.debug("meter_curent: %s", meter_curent)
        #_LOGGER.debug("window_data: %s", window_data)
        #_LOGGER.debug("usage_gen: %s", usage_gen)

        return {
            "Numărul dispozitivului": multi_data.get("result", {}).get("MeterDetails", [{}])[0].get("MeterNumber", "N/A"),
            "Tip de contor": multi_data.get("result", {}).get("MeterDetails", [{}])[0].get("MeterType", "N/A"),
            "Data de începere a următoarei citiri": window_data.get("result", {}).get("Data", {}).get("NextMonthOpeningDate", "N/A"),
            "Data de final a citirii": window_data.get("result", {}).get("Data", {}).get("NextMonthClosingDate", "N/A"),
            "attribution": ATTRIBUTION,
        }

    def _get_multi_meter_data(self):
        """Returnează sub-dicționarul get_multi_meter (API_GET_MULTI_METER)."""
        return self._acc_data().get("get_multi_meter", {})

    def _get_meter_value_data(self): # nu sunt date
        """Returnează sub-dicționarul get_meter_value (API_GET_MULTI_METER_CURRENT)."""
        return self._acc_data().get("get_meter_value", {})

    def _get_window_dates_data(self):
        """Returnează sub-dicționarul get_window_dates_enc (API_GET_MULTI_METER_READ_DATE)."""
        return self._acc_data().get("get_window_dates_enc", {})

    def _get_usage_generation(self):
        """Returnează sub-dicționarul get_window_dates_enc (API_GET_MULTI_METER_READ_DATE)."""
        return self._acc_data().get("get_usage_generation", {})


# ------------------------------------------------------------------------
# FacturaRestantaSensor
# ------------------------------------------------------------------------
class FacturaRestantaSensor(HidroelectricaBaseSensor):
    """
    Senzor pentru afișarea facturii curente (cât mai ai de plată).
    - Folosește: get_bill (API_URL_GET_BILL)
    """

    def __init__(self, coordinator, config_entry, utility_account_number, account_number):
        super().__init__(coordinator, config_entry, utility_account_number, account_number)
        self._attr_name = "Factura restantă"
        self._attr_unique_id = f"{config_entry.entry_id}_{utility_account_number}_factura_restanta"
        self._attr_entity_id = f"sensor.{DOMAIN}_factura_restanta_{utility_account_number}"
        self._attr_icon = "mdi:invoice-text-arrow-left"

    @property
    def entity_id(self):
        """Returnează identificatorul explicit al entității."""
        return self._attr_entity_id

    @entity_id.setter
    def entity_id(self, value):
        """Setează identificatorul explicit al entității."""
        self._attr_entity_id = value

    @property
    def native_value(self):
        """
        Returnează 'Da' dacă există sumă rămasă de plată (rembalance) 
        sau 'Nu' dacă factura este achitată integral sau are un sold negativ.
        """
        bill_data = self._get_bill_data()
        _LOGGER.debug(f"Bill data in native_value: {bill_data}")

        if not bill_data:
            _LOGGER.debug("Bill data is None or empty.")
            return None

        result_block = bill_data.get("result", {})
        rembalance = result_block.get("rembalance", "N/A")

        _LOGGER.debug(f"Result block: {result_block}")
        _LOGGER.debug(f"Rembalance value: {rembalance}")

        # Convertim rembalance în float pentru verificare, dacă este posibil
        try:
            rembalance_value = float(rembalance.replace(",", "."))
        except (ValueError, AttributeError):
            _LOGGER.debug("Failed to convert rembalance to float.")
            rembalance_value = None

        _LOGGER.debug(f"Rembalance numeric value: {rembalance_value}")

        # Verificăm dacă rembalance_value este valid înainte de comparație
        if rembalance_value is not None:
            if rembalance_value > 0:
                return "Da"
            elif rembalance_value < 0:
                return "Sold"
        else:
            # Dacă rembalance_value este None, tratăm acest caz
            _LOGGER.debug("Rembalance value is None, returning default 'Nu'")
            return "Nu"

    @property
    def extra_state_attributes(self):
        """
        Afișăm detalii adiționale despre factură:
        - 'Total neachitat': Suma totală neachitată din toate facturile.
        - 'Total credit': Suma totală de credit disponibilă.
        - 'duedate': Data scadenței (dacă există o singură factură relevantă).
        - 'Detalii': Mesaj specific dacă nu există facturi disponibile.
        - 'billamount': Valoarea totală a facturii, inclusiv semnul negativ dacă este cazul.
        """
        bill_data = self._get_bill_data()
        _LOGGER.debug(f"Bill data in extra_state_attributes: {bill_data}")

        if not bill_data:
            _LOGGER.debug("Bill data is None or empty.")
            return {}

        result_block = bill_data.get("result", {})
        _LOGGER.debug(f"Result block: {result_block}")

        facturi = result_block.get("facturi", [])  # Presupunem că facturile sunt stocate sub această cheie
        _LOGGER.debug(f"Facturi list: {facturi}")

        total_neachitat = 0.0
        total_credit = 0.0
        total_neachitat_formatted = "0,00"
        total_credit_formatted = "0,00"

        if facturi:
            # Iterăm prin facturi și cumulăm suma neachitată și creditul
            for factura in facturi:
                rembalance_str = factura.get("rembalance", "0,00")
                rembalance = rembalance_str.replace(",", ".")
                _LOGGER.debug(f"Processing factura rembalance: {rembalance}")
                try:
                    rembalance_value = float(rembalance)
                    if rembalance_value > 0:
                        total_neachitat += rembalance_value
                    elif rembalance_value < 0:
                        total_credit += rembalance_value
                except ValueError:
                    _LOGGER.debug(f"Skipping invalid rembalance: {rembalance}")
                    continue

            _LOGGER.debug(f"Total neachitat calculated from facturi: {total_neachitat}")
            _LOGGER.debug(f"Total credit calculated from facturi: {total_credit}")
            total_neachitat_formatted = f"{total_neachitat:.2f}".replace(".", ",")
            total_credit_formatted = f"{total_credit:.2f}".replace(".", ",")
        else:
            # Dacă nu există facturi, folosește billamount
            billamount = result_block.get("billamount", "0,00")
            _LOGGER.debug(f"No facturi, using billamount: {billamount}")
            try:
                total_neachitat = float(billamount.replace(",", "."))
                if total_neachitat > 0:
                    total_neachitat_formatted = billamount
                elif total_neachitat < 0:
                    total_credit = total_neachitat
                    total_credit_formatted = billamount
            except (ValueError, AttributeError):
                _LOGGER.debug("Failed to convert billamount to float.")
                total_neachitat = 0.0
                total_credit = 0.0

        _LOGGER.debug(f"Total neachitat calculated: {total_neachitat}")
        _LOGGER.debug(f"Total credit calculated: {total_credit}")

        # Construim atributele
        attributes = {
            "attribution": ATTRIBUTION,
        }

        if total_neachitat > 0:
            attributes["Total neachitat"] = f"{total_neachitat_formatted} lei"
            #attributes["duedate"] = result_block.get("duedate", "N/A")  # Poți ajusta să ia prima factură restantă
        elif total_credit < 0:
            attributes["Total credit"] = f"{total_credit_formatted} lei"
            #attributes["duedate"] = result_block.get("duedate", "N/A")  # Poți ajusta dacă este necesar

        if not facturi:
            # Dacă nu avem facturi, afișăm billamount și detalii
            #attributes["billamount"] = result_block.get("billamount", "N/A")
            attributes["Detalii"] = "Nu există facturi individuale disponibile"

        return attributes

    def _get_bill_data(self):
        """Returnează sub-dicționarul get_bill (API_URL_GET_BILL)."""
        bill_data = self._acc_data().get("get_bill", {})
        _LOGGER.debug(f"Data returned by _get_bill_data: {bill_data}")
        return bill_data



# ------------------------------------------------------------------------
# ArhivaPlatiSensor
# ------------------------------------------------------------------------
class ArhivaPlatiSensor(HidroelectricaBaseSensor):
    """
    Senzor care afișează numărul de plăți (PaymentHistory) pentru un an specific.
    Exemplu: 'Arhivă plăți - 2023'
    """

    def __init__(self, coordinator, config_entry, utility_account_number, account_number, an, facturi_list_an):
        super().__init__(coordinator, config_entry, utility_account_number, account_number)
        self._an = an  # de ex. 2023
        self._facturi_list_an = facturi_list_an  # toate plățile din acel an

        self._attr_name = f"Arhivă plăți - {an}"
        self._attr_unique_id = f"{config_entry.entry_id}_{utility_account_number}_arhiva_plati_{an}"
        self._attr_entity_id = f"sensor.{DOMAIN}_arhiva_plati_{utility_account_number}_{an}"
        self._attr_icon = "mdi:cash-register"

    @staticmethod
    def _parse_amount(amount_str):
        """
        Convertește o sumă în format european în float.
        Exemplu: '1.580,10' -> 1580.10
        """
        try:
            # Înlocuiește punctul pentru separarea miilor și virgula cu punct pentru zecimale
            return float(amount_str.replace(".", "").replace(",", "."))
        except ValueError:
            _LOGGER.error("Eroare la parsarea sumei: %s", amount_str)
            return 0.0

    @property
    def native_value(self):
        """
        Afișăm numărul total de plăți pentru acest an.
        """
        return len(self._facturi_list_an)

    @property
    def extra_state_attributes(self):
        if not self._facturi_list_an:
            return {}

        # Dicționar în care vom pune atributele
        attributes = {}

        # Mapare numerică -> lunile în română
        MONTHS_RO = {
            "01": "ianuarie", "02": "februarie", "03": "martie",
            "04": "aprilie", "05": "mai", "06": "iunie",
            "07": "iulie", "08": "august", "09": "septembrie",
            "10": "octombrie", "11": "noiembrie", "12": "decembrie"
        }

        # Inițializăm totaluri
        total_suma = 0.0
        total_facturi = len(self._facturi_list_an)

        for idx, payment in enumerate(self._facturi_list_an, start=1):
            raw_date = payment.get("paymentDate", "")
            luna_str = "00"
            if len(raw_date.split("/")) == 3:
                _, month, _ = raw_date.split("/")
                luna_str = month

            luna_text = MONTHS_RO.get(luna_str, "necunoscută")
            amount_str = payment.get("amount", "0.00")

            # Adăugăm la total suma achitată
            total_suma += self._parse_amount(amount_str)

            attr_key = f"Plată #{idx} factură luna {luna_text}"
            attributes[attr_key] = amount_str

        # Adăugăm totaluri și atribuire
        attributes["---------------"] = ""
        attributes["Plăți efectuate"] = total_facturi
        attributes["Total suma achitată"] = f"{total_suma:.2f} lei"
        attributes["attribution"] = ATTRIBUTION

        return attributes
