"""Platforma pentru senzori din integrarea Hidroelectrica România."""

import logging
from datetime import datetime
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator
from homeassistant.helpers.device_registry import DeviceEntryType
from .const import DOMAIN, ATTRIBUTION

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass: HomeAssistant, entry, async_add_entities):
    """Configurează senzorii pe baza unei intrări de configurare."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: DataUpdateCoordinator = data["coordinator"]

    # Creezi entități separate
    sensors = [
        HidroUserSettingsSensor(coordinator, entry),
        HidroCurrentBillSensor(coordinator, entry),
        HidroBillHistorySensor(coordinator, entry),

    ]

    async_add_entities(sensors, True)


class HidroUserSettingsSensor(CoordinatorEntity, SensorEntity):
    """Senzor pentru date utilizator."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "Date utilizator"
        self._attr_unique_id = f"{entry.entry_id}_user_settings"
        self._icon = "mdi:account"
        self._attr_entity_id = f"sensor.{DOMAIN}_date_utilizator"

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
        """Returnează UserID-ul utilizatorului ca valoare principală."""
        data = self.coordinator.data.get("user_settings", {})
        try:
            user_id = data.get("result", {}).get("Data", {}).get("Table1", [])[0].get("UserID")
            return user_id  # UserID este valoarea principală a senzorului
        except (KeyError, IndexError):
            return None

    @property
    def extra_state_attributes(self):
        """Returnează atributele adiționale ale senzorului."""
        data = self.coordinator.data.get("user_settings", {})
        attributes = {}

        try:
            table_data = data.get("result", {}).get("Data", {}).get("Table1", [])[0]
            attributes = {
                "ID utilizator": str(table_data.get("UserID", "N/A")),
                "Număr cont": str(table_data.get("AccountNumber", "N/A")),

                # Separator pentru lizibilitate
                "---------------": "",

                "Număr cont utilitate": table_data.get("UtilityAccountNumber", "N/A"),
                "Țară": table_data.get("CountryName", "N/A").capitalize(),
                "Oraș": table_data.get("CityName", "N/A").capitalize(),
                "Tip client": table_data.get("CustomerTypeDesc", "N/A"),
                "Ultima actualizare de date": table_data.get("LastUpdate", "N/A"),
                "Tip contor": table_data.get("MeterType", "N/A"),
                "attribution": ATTRIBUTION,
            }
        except (KeyError, IndexError):
            attributes["Eroare"] = "Datele utilizatorului nu sunt disponibile"

        return attributes

    @property
    def icon(self):
        """Pictograma senzorului."""
        return self._icon

    @property
    def device_info(self):
        """Informații despre dispozitiv pentru integrarea Hidroelectrica România."""
        device_info = {
            "identifiers": {(DOMAIN, "hidroelectrica")},
            "name": "Hidroelectrica România",
            "manufacturer": "Ciprian Nicolae (cnecrea)",
            "model": "Hidroelectrica România",
            "entry_type": DeviceEntryType.SERVICE,
        }
        return device_info




# Senzor pentru afișarea facturii neplatite.
# Dicționar pentru mapping-ul lunilor în română
MONTHS_RO = {
    "January": "ianuarie",
    "February": "februarie",
    "March": "martie",
    "April": "aprilie",
    "May": "mai",
    "June": "iunie",
    "July": "iulie",
    "August": "august",
    "September": "septembrie",
    "October": "octombrie",
    "November": "noiembrie",
    "December": "decembrie",
}

class HidroCurrentBillSensor(CoordinatorEntity, SensorEntity):
    """Senzor pentru factură curentă."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "Factură restantă"
        self._attr_unique_id = f"{entry.entry_id}_current_bill"
        self._icon = "mdi:file-document-alert-outline"
        self._attr_entity_id = f"sensor.{DOMAIN}_factura_restanta"

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
        """Returnează starea principală a senzorului."""
        data = self.coordinator.data.get("current_bill", {}).get("result", {})
        bill_amount = float(data.get("billamount", "0,00").replace(",", "."))
        return "Da" if bill_amount > 0 else "Nu"

    @property
    def extra_state_attributes(self):
        """Returnează atributele adiționale ale senzorului."""
        data = self.coordinator.data.get("current_bill", {}).get("result", {})
        attributes = {}
        total_sold = 0  # Inițializăm suma totală

        if isinstance(data, dict):
            balance = float(data.get("billamount", "0,00").replace(",", "."))
            rem_balance = float(data.get("rembalance", "0,00").replace(",", "."))
            total_sold += rem_balance

            # Obținem luna din data scadenței
            raw_date = data.get("duedate", "Necunoscut")
            try:
                parsed_date = datetime.strptime(raw_date, "%Y%m%d")  # Format corectat
                month_name_en = parsed_date.strftime("%B")  # Obține numele lunii în engleză
                month_name_ro = MONTHS_RO.get(month_name_en, "necunoscut")

                # Calculăm zilele rămase până la data scadenței
                days_until_due = (parsed_date - datetime.now()).days
                due_message = (
                    f"Următoarea plată de {balance:.2f} lei este scadentă "
                    f"pe luna {month_name_ro} ({days_until_due} zile)"
                )
                attributes["Plată scadentă"] = due_message

            except ValueError:
                month_name_ro = "necunoscut"
                attributes["Plată scadentă"] = "Data scadenței necunoscută"

        # Adăugăm separatorul explicit înainte de total sold
        attributes["---------------"] = ""
        attributes["Total neachitat"] = f"{total_sold:.2f} lei" if total_sold > 0 else "0.00 lei"
        attributes["attribution"] = ATTRIBUTION
        return attributes

    @property
    def icon(self):
        """Pictograma senzorului."""
        return self._icon

    @property
    def device_info(self):
        """Informații despre dispozitiv pentru integrarea Hidroelectrica România."""
        device_info = {
            "identifiers": {(DOMAIN, "hidroelectrica")},
            "name": "Hidroelectrica România",
            "manufacturer": "Ciprian Nicolae (cnecrea)",
            "model": "Hidroelectrica România",
            "entry_type": DeviceEntryType.SERVICE,
        }
        return device_info



# Senzor pentru afișarea facturilor plătite.
# Dicționar pentru mapping-ul lunilor în română
MONTHS_RO = {
    "January": "ianuarie",
    "February": "februarie",
    "March": "martie",
    "April": "aprilie",
    "May": "mai",
    "June": "iunie",
    "July": "iulie",
    "August": "august",
    "September": "septembrie",
    "October": "octombrie",
    "November": "noiembrie",
    "December": "decembrie",
}

class HidroBillHistorySensor(CoordinatorEntity, SensorEntity):
    """Senzor pentru istoricul facturilor achitate."""

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        self._attr_name = "Istoric facturi achitate"
        self._attr_unique_id = f"{entry.entry_id}_paid_bill_history"
        self._icon = "mdi:clipboard-text-clock"
        self._attr_entity_id = f"sensor.{DOMAIN}_istoric_facturi_achitate"

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
        """Returnează numărul total de facturi achitate."""
        data = self.coordinator.data.get("bill_history", {}).get("result", {}).get("objBillingPaymentHistoryEntity", [])
        return len(data)  # Numărul total de facturi achitate

    @property
    def extra_state_attributes(self):
        """Returnează atributele adiționale ale senzorului."""
        data = self.coordinator.data.get("bill_history", {}).get("result", {}).get("objBillingPaymentHistoryEntity", [])
        attributes = {}
        total_paid = 0.0

        for idx, payment in enumerate(data, start=1):
            try:
                payment_date = payment.get("paymentDate", "Necunoscut")
                amount = float(payment.get("amount", "0").replace(",", "."))
                total_paid += amount

                # Transformăm luna în română
                try:
                    parsed_date = datetime.strptime(payment_date, "%d/%m/%Y")
                    month_name_en = parsed_date.strftime("%B")
                    month_name_ro = MONTHS_RO.get(month_name_en, "necunoscut")
                    formatted_date = f"{parsed_date.day} {month_name_ro} {parsed_date.year}"
                except ValueError:
                    formatted_date = "necunoscut"

                # Adăugăm în atribute
                attributes[f"Emisă la data de {formatted_date}"] = f"{amount:,.2f} lei".replace(",", "X").replace(".", ",").replace("X", ".")
            except ValueError:
                continue

        # Adăugăm separatorul explicit înainte de total achitat
        attributes["---------------"] = ""
        attributes["Număr total de plăți efectuate"] = len(data)
        attributes["Total achitat"] = f"{total_paid:,.2f} lei".replace(",", "X").replace(".", ",").replace("X", ".")
        attributes["attribution"] = ATTRIBUTION
        return attributes

    @property
    def icon(self):
        """Pictograma senzorului."""
        return self._icon

    @property
    def device_info(self):
        """Informații despre dispozitiv pentru integrarea Hidroelectrica România."""
        device_info = {
            "identifiers": {(DOMAIN, "hidroelectrica")},
            "name": "Hidroelectrica România",
            "manufacturer": "Ciprian Nicolae (cnecrea)",
            "model": "Hidroelectrica România",
            "entry_type": DeviceEntryType.SERVICE,
        }
        return device_info
