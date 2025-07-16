"""
Definirea senzorilor pentru integrarea Hidroelectrica România.
"""

import logging
import datetime

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity
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
        _, _, year = date_str.split("/")
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

    # Pentru fiecare cont (uan, acc_no) creăm senzorii de bază și noii senzori fereastră citire:
    for account_info in coordinator.data.get("utility_accounts", []):
        uan = account_info["UtilityAccountNumber"]
        acc_no = account_info["AccountNumber"]

        # Senzorii de bază
        entities.append(DateContractSensor(coordinator, entry, uan, acc_no))
        entities.append(IndexCurentSensor(coordinator, entry, uan, acc_no))
        entities.append(FacturaRestantaSensor(coordinator, entry, uan, acc_no))
        # Noi: senzori Data început / Data final perioadă citire
        entities.append(DataInceputCitireSensor(coordinator, entry, uan, acc_no))
        entities.append(DataFinalCitireSensor(coordinator, entry, uan, acc_no))
        entities.append(PlataRestantaSensor(coordinator, entry, uan, acc_no))
        entities.append(TotalNeachitatSensor(coordinator, entry, uan, acc_no))
        entities.append(DataScadentaSensor(coordinator, entry, uan, acc_no))

        # Istoric facturi (unchanged)...
        facturi_data = coordinator.data["accounts_data"][uan].get("get_billing_history_list", {})
        result_block = facturi_data.get("result", {})
        facturi_list = result_block.get("objBillingPaymentHistoryEntity", [])
        if facturi_list:
            plati_pe_ani: dict[int, list] = {}
            for f in facturi_list:
                an = _extract_year_from_dd_mm_yyyy(f.get("paymentDate", ""))
                plati_pe_ani.setdefault(an, []).append(f)
            for an, lista_plati in plati_pe_ani.items():
                entities.append(ArhivaPlatiSensor(
                    coordinator,
                    entry,
                    uan,
                    acc_no,
                    an,
                    lista_plati
                ))

        # Istoric consum (unchanged)...

    async_add_entities(entities, update_before_add=True)


# ------------------------------------------------------------------------
# Clasă de bază
# ------------------------------------------------------------------------
class HidroelectricaBaseSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator, config_entry, utility_account_number, account_number):
        super().__init__(coordinator)
        self._config_entry = config_entry
        self._uan = utility_account_number
        self._acc_no = account_number
        self._attr_entity_id = None

    @property
    def entity_id(self):
        return self._attr_entity_id

    @entity_id.setter
    def entity_id(self, value):
        self._attr_entity_id = value

    @property
    def device_info(self):
        val_data = self._acc_data().get("validate_user_login", {})
        address_parts = val_data.get("Address", "N/A").split(", ")
        return {
            "identifiers": {(DOMAIN, f"{self._config_entry.entry_id}_{self._uan}")},
            "name": f"Hidroelectrica România – {address_parts[1].capitalize()}, {address_parts[0]}, {address_parts[2].capitalize()} ({self._uan})",
            "manufacturer": "Ciprian Nicolae (cnecrea)",
            "model": "Hidroelectrica România",
        }

    def _acc_data(self):
        return self.coordinator.data.get("accounts_data", {}).get(self._uan, {})


# ------------------------------------------------------------------------
# DateContractSensor (unchanged)
# ------------------------------------------------------------------------
class DateContractSensor(HidroelectricaBaseSensor):
    def __init__(self, coordinator, config_entry, utility_account_number, account_number):
        super().__init__(coordinator, config_entry, utility_account_number, account_number)
        self._attr_name = "Date contract"
        self._attr_unique_id = f"{config_entry.entry_id}_{utility_account_number}_date_contract"
        self._attr_entity_id = f"sensor.{DOMAIN}_date_contract_{utility_account_number}"
        self._attr_icon = "mdi:file-document-edit-outline"

    @property
    def native_value(self):
        return self._acc_data().get("validate_user_login", {}).get("BPNumber")

    @property
    def extra_state_attributes(self):
        val = self._acc_data().get("validate_user_login", {})
        sett = self._acc_data().get("get_user_setting", {})
        addr = val.get("Address", "N/A").split(", ")
        return {
            "Numele și prenumele": f"{val.get('FirstName','').capitalize()} {val.get('LastName','').capitalize()}",
            "Telefon de contact": val.get("PrimeryContactNumber", "N/A"),
            "Localitate": val.get("CityName", "N/A").capitalize(),
            "Țară": val.get("Country", "N/A").capitalize(),
            "Ultima actualizare de date": sett.get("LastUpdate", "N/A"),
            "attribution": ATTRIBUTION,
        }


# ------------------------------------------------------------------------
# IndexCurentSensor (patched)
# ------------------------------------------------------------------------
class IndexCurentSensor(HidroelectricaBaseSensor):
    """
    Senzor care afișează indexul curent și fereastra de citire.
    - Folosește:
        • get_meter_value      (stocat în coordinator sub 'get_meter_value')
        • get_multi_meter      (stocat sub 'get_multi_meter')
        • get_window_dates_enc (stocat sub 'get_window_dates_enc')
    """

    def __init__(self, coordinator, config_entry, utility_account_number, account_number):
        super().__init__(coordinator, config_entry, utility_account_number, account_number)
        self._attr_name = "Index curent"
        self._attr_unique_id = f"{config_entry.entry_id}_{utility_account_number}_index_curent"
        self._attr_entity_id = f"sensor.{DOMAIN}_index_curent_{utility_account_number}"
        self._attr_icon = "mdi:gauge"

    @property
    def native_value(self):
        """Returnează valoarea indexului curent (sau 0 dacă nu e disponibil)."""
        meter_data = self._get_meter_value_data() or {}
        result = meter_data.get("result", {})

        # Dacă responsestatus == 0 → nu există măsurătoare
        try:
            if int(result.get("responsestatus", 0)) == 0:
                return 0
        except (TypeError, ValueError):
            # dacă nu putem converti, ignorăm
            pass

        # altfel, IndexValue e definit în interiorul result
        return result.get("IndexValue", 0)

    @property
    def extra_state_attributes(self):
        """
        Atribute suplimentare:
        - numărul și tipul contorului
        - Data de început a perioadei de citire
        - Data de final a perioadei de citire
        """
        # Detalii contor
        multi = self._get_multi_meter_data().get("result", {})  
        details = multi.get("MeterDetails", [])
        if details:
            # folosește ultima intrare dacă sunt multiple contoare
            last = details[-1]
            meter_no   = last.get("MeterNumber", "N/A")
            meter_type = last.get("MeterType",   "N/A")
        else:
            meter_no = meter_type = "N/A"

        # Fereastra de citire
        window = self._get_window_dates_data().get("result", {}).get("Data", {})
        start_date = window.get("NextMonthOpeningDate",  "N/A")
        end_date   = window.get("NextMonthClosingDate",  "N/A")

        return {
            "Numărul dispozitivului":              meter_no,
            "Tip de contor":                        meter_type,
            "Data de început a perioadei de citire": start_date,
            "Data de final a perioadei de citire":   end_date,
            "attribution":                          ATTRIBUTION,
        }

    def _get_multi_meter_data(self):
        """Datele returnate de GetMultiMeter (API_GET_MULTI_METER)."""
        return self._acc_data().get("get_multi_meter", {})

    def _get_meter_value_data(self):
        """Datele returnate de GetMeterValue (API_GET_MULTI_METER_CURRENT)."""
        return self._acc_data().get("get_meter_value", {})

    def _get_window_dates_data(self):
        """Datele returnate de GetWindowDatesENC (API_GET_MULTI_METER_READ_DATE)."""
        return self._acc_data().get("get_window_dates_enc", {})



# ------------------------------------------------------------------------
# FacturaRestantaSensor (unchanged)
# ------------------------------------------------------------------------
class FacturaRestantaSensor(HidroelectricaBaseSensor):
    def __init__(self, coordinator, config_entry, utility_account_number, account_number):
        super().__init__(coordinator, config_entry, utility_account_number, account_number)
        self._attr_name = "Factura restantă"
        self._attr_unique_id = f"{config_entry.entry_id}_{utility_account_number}_factura_restanta"
        self._attr_entity_id = f"sensor.{DOMAIN}_factura_restanta_{utility_account_number}"
        self._attr_icon = "mdi:invoice-text-arrow-left"

    @property
    def native_value(self):
        bill = self._acc_data().get("get_bill", {}).get("result", {})
        try:
            val = float(str(bill.get("rembalance","0")).replace(",","."))
        except Exception:
            return "Nu"
        if val > 0:
            return "Da"
        if val < 0:
            return "Sold"
        return "Nu"

    @property
    def extra_state_attributes(self):
        bill = self._acc_data().get("get_bill", {}).get("result", {})
        rem = bill.get("rembalance","0").replace(",",".")
        dued = bill.get("duedate")
        attrs: dict[str, any] = {"attribution": ATTRIBUTION}
        try:
            rem_v = float(rem)
        except ValueError:
            rem_v = 0.0

        if rem_v > 0:
            days_over_text = ""
            if dued:
                try:
                    due_date = datetime.datetime.strptime(dued, "%d/%m/%Y").date()
                    delta = (datetime.date.today() - due_date).days
                    days_over_text = f", depășită cu {delta} zile" if delta > 0 else ""
                except Exception:
                    pass
                attrs["Data scadenței"] = dued
            attrs["Plată restantă"] = f"{rem_v:.2f} lei{days_over_text}"
            attrs["Total neachitat"] = f"{rem_v:.2f} lei"
        elif rem_v < 0:
            attrs["Total credit"] = f"{abs(rem_v):.2f} lei"
        else:
            attrs["Detalii"] = "Nu există facturi restante"

        return attrs
class PlataRestantaSensor(HidroelectricaBaseSensor):
    """Afișează suma rămasă de plată pentru factura curentă."""
    def __init__(self, coordinator, config_entry, uan, acc_no):
        super().__init__(coordinator, config_entry, uan, acc_no)
        self._attr_name = "Plată restantă"
        self._attr_unique_id = (
            f"{config_entry.entry_id}_{uan}_plata_restanta"
        )
        self._attr_entity_id = (
            f"sensor.{DOMAIN}_plata_restanta_{uan}"
        )
        self._attr_icon = "mdi:cash-multiple"
        self._attr_unit_of_measurement = "lei"

    @property
    def native_value(self):
        bill = self._acc_data().get("get_bill", {}).get("result", {})
        rem = bill.get("rembalance", "0").replace(",", ".")
        try:
            return float(rem)
        except (ValueError, TypeError):
            return None


class TotalNeachitatSensor(HidroelectricaBaseSensor):
    """Afișează totalul neachitat (identic cu Plata restantă)."""
    def __init__(self, coordinator, config_entry, uan, acc_no):
        super().__init__(coordinator, config_entry, uan, acc_no)
        self._attr_name = "Total neachitat"
        self._attr_unique_id = (
            f"{config_entry.entry_id}_{uan}_total_neachitat"
        )
        self._attr_entity_id = (
            f"sensor.{DOMAIN}_total_neachitat_{uan}"
        )
        self._attr_icon = "mdi:currency-ron"
        self._attr_unit_of_measurement = "lei"

    @property
    def native_value(self):
        bill = self._acc_data().get("get_bill", {}).get("result", {})
        rem = bill.get("rembalance", "0").replace(",", ".")
        try:
            return float(rem)
        except (ValueError, TypeError):
            return None


class DataScadentaSensor(HidroelectricaBaseSensor):
    """Afișează data scadenței facturii restante."""
    def __init__(self, coordinator, config_entry, uan, acc_no):
        super().__init__(coordinator, config_entry, uan, acc_no)
        self._attr_name = "Data scadenței"
        self._attr_unique_id = (
            f"{config_entry.entry_id}_{uan}_data_scadenta"
        )
        self._attr_entity_id = (
            f"sensor.{DOMAIN}_data_scadenta_{uan}"
        )
        self._attr_icon = "mdi:calendar-alert"

    @property
    def native_value(self):
        bill = self._acc_data().get("get_bill", {}).get("result", {})
        dued = bill.get("duedate")
        if not dued:
            return None
        try:
            # API returns "DD/MM/YYYY"
            return datetime.datetime.strptime(dued, "%d/%m/%Y").date()
        except ValueError:
            return dued  # fallback to raw string if parse fails


# ------------------------------------------------------------------------
# Noile senzori perioadă citire
# ------------------------------------------------------------------------
class DataInceputCitireSensor(HidroelectricaBaseSensor):
    """
    Afișează Data de început a perioadei de citire.
    """
    def __init__(self, coordinator, config_entry, utility_account_number, account_number):
        super().__init__(coordinator, config_entry, utility_account_number, account_number)
        self._attr_name = "Data început citire"
        self._attr_unique_id = f"{config_entry.entry_id}_{utility_account_number}_start_citire"
        self._attr_entity_id = f"sensor.{DOMAIN}_start_citire_{utility_account_number}"
        self._attr_icon = "mdi:calendar-start"

    @property
    def native_value(self):
        window = self._acc_data().get("get_window_dates_enc", {}).get("result", {}).get("Data", {})
        return window.get("NextMonthOpeningDate")

    @property
    def extra_state_attributes(self):
        return {"attribution": ATTRIBUTION}


class DataFinalCitireSensor(HidroelectricaBaseSensor):
    """
    Afișează Data de final a perioadei de citire.
    """
    def __init__(self, coordinator, config_entry, utility_account_number, account_number):
        super().__init__(coordinator, config_entry, utility_account_number, account_number)
        self._attr_name = "Data final citire"
        self._attr_unique_id = f"{config_entry.entry_id}_{utility_account_number}_end_citire"
        self._attr_entity_id = f"sensor.{DOMAIN}_end_citire_{utility_account_number}"
        self._attr_icon = "mdi:calendar-end"

    @property
    def native_value(self):
        window = self._acc_data().get("get_window_dates_enc", {}).get("result", {}).get("Data", {})
        return window.get("NextMonthClosingDate")

    @property
    def extra_state_attributes(self):
        return {"attribution": ATTRIBUTION}


# ------------------------------------------------------------------------
# ArhivaPlatiSensor (unchanged)
# ------------------------------------------------------------------------
class ArhivaPlatiSensor(HidroelectricaBaseSensor):
    def __init__(self, coordinator, config_entry, utility_account_number, account_number, an, facturi_list_an):
        super().__init__(coordinator, config_entry, utility_account_number, account_number)
        self._an = an
        self._facturi_list_an = facturi_list_an
        self._attr_name = f"Arhivă plăți - {an}"
        self._attr_unique_id = f"{config_entry.entry_id}_{utility_account_number}_arhiva_plati_{an}"
        self._attr_entity_id = f"sensor.{DOMAIN}_arhiva_plati_{utility_account_number}_{an}"
        self._attr_icon = "mdi:cash-register"

    @staticmethod
    def _parse_amount(amount_str: str) -> float:
        try:
            return float(amount_str.replace(".", "").replace(",", "."))
        except ValueError:
            _LOGGER.error("Eroare la parsarea sumei: %s", amount_str)
            return 0.0

    @property
    def native_value(self):
        return len(self._facturi_list_an)

    @property
    def extra_state_attributes(self):
        if not self._facturi_list_an:
            return {}
        attributes: dict[str, any] = {}
        MONTHS_RO = {
            "01": "ianuarie", "02": "februarie", "03": "martie",
            "04": "aprilie", "05": "mai", "06": "iunie",
            "07": "iulie", "08": "august", "09": "septembrie",
            "10": "octombrie", "11": "noiembrie", "12": "decembrie"
        }
        total = 0.0
        for idx, p in enumerate(self._facturi_list_an, start=1):
            raw = p.get("paymentDate", "")
            month = raw.split("/")[1] if len(raw.split("/")) == 3 else "00"
            amt = p.get("amount", "0,00")
            total += self._parse_amount(amt)
            text = MONTHS_RO.get(month, "necunoscută")
            attributes[f"Plată #{idx} factură luna {text}"] = amt
        attributes["Plăți efectuate"] = len(self._facturi_list_an)
        attributes["Total suma achitată"] = f"{total:.2f} lei"
        attributes["attribution"] = ATTRIBUTION
        return attributes