"""Funcții și constante utilitare pentru integrarea Hidroelectrica România."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.helpers.selector import SelectOptionDict


# ══════════════════════════════════════════════
# Mapping-uri luni și tipuri citire
# ══════════════════════════════════════════════

MONTHS_NUM_RO: dict[int, str] = {
    1: "Ianuarie",
    2: "Februarie",
    3: "Martie",
    4: "Aprilie",
    5: "Mai",
    6: "Iunie",
    7: "Iulie",
    8: "August",
    9: "Septembrie",
    10: "Octombrie",
    11: "Noiembrie",
    12: "Decembrie",
}

READING_TYPE_MAP: dict[str, str] = {
    "Estimat distribuitor": "Estimat distribuitor",
    "Autocitire": "Autocitire",
    "Regularizare": "Regularizare",
    "Regularizare + estimare": "Regularizare + estimare",
    "Regularizare CV": "Regularizare CV",
}

INVOICE_TYPE_MAP: dict[str, str] = {
    "Factură": "Factură",
    "Notă de credit": "Notă de credit",
    "Notă de debit": "Notă de debit",
}


# ══════════════════════════════════════════════
# Funcții de formatare
# ══════════════════════════════════════════════

def format_ron(value: float) -> str:
    """Formatează o valoare numerică în format românesc (1.234,56 lei).

    Args:
        value: Valoarea numerică de formatat

    Returns:
        String formatat în format românesc cu zecimale
    """
    formatted = f"{value:,.2f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def format_number_ro(value: float | int | str) -> str:
    """Formatează un număr cu separatorul zecimal românesc (virgulă).

    Exemple:
        4.029   → '4,029'
        124.91  → '124,91'
        11.9    → '11,9'
        0.424   → '0,424'
        100     → '100'
        100.0   → '100'

    Args:
        value: Valoarea numerică de formatat

    Returns:
        String formatat cu virgulă ca separator zecimal
    """
    try:
        num = float(value)
    except (ValueError, TypeError):
        return str(value)
    if num == int(num):
        return str(int(num))
    text = str(num)
    return text.replace(".", ",")


def parse_romanian_amount(value_str: str) -> float:
    """Parsează o sumă în format românesc ("1.234,56" sau "1234,56") la float.

    Args:
        value_str: String cu suma în format românesc

    Returns:
        Valoarea numerică ca float

    Raises:
        ValueError: Dacă string-ul nu poate fi parsat
    """
    if not value_str:
        return 0.0

    # Curață spațiile
    value_str = value_str.strip()

    # Înlocuiește separatoarele românești cu separatorii standard Python
    # "1.234,56" → "1234.56"
    value_str = value_str.replace(".", "").replace(",", ".")

    try:
        return float(value_str)
    except ValueError as exc:
        raise ValueError(f"Cannot parse Romanian amount: {value_str}") from exc


def format_date_ro(
    date_str: str,
    input_format: str = "%Y-%m-%dT%H:%M:%S"
) -> str:
    """Convertește data din ISO format la "dd/MM/yyyy".

    Args:
        date_str: Data ca string
        input_format: Formatul de intrare (implicit ISO 8601 fără Z)

    Returns:
        Data formatată ca "dd/MM/yyyy"

    Raises:
        ValueError: Dacă date_str nu poate fi parsat
    """
    try:
        # Eliminează Z din finalul stringului dacă există
        if date_str.endswith("Z"):
            date_str = date_str[:-1]
        parsed_date = datetime.strptime(date_str, input_format)
        return parsed_date.strftime("%d/%m/%Y")
    except ValueError as exc:
        raise ValueError(f"Cannot parse date: {date_str}") from exc


# ══════════════════════════════════════════════
# Funcții de acces sigur la date
# ══════════════════════════════════════════════

def safe_get(data: Any, *keys: str, default: Any = None) -> Any:
    """Acces sigur la chei imbricate într-un dicționar.

    Args:
        data: Dicționarul din care se extrag date
        *keys: Seria de chei pentru acces imbricat
        default: Valoarea implicită dacă cheia nu există

    Returns:
        Valoarea găsită sau default
    """
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key)
            if current is None:
                return default
        else:
            return default
    return current if current is not None else default


# ══════════════════════════════════════════════
# Funcții pentru configurare conturi
# ══════════════════════════════════════════════

def build_address_display(address_str: str) -> str:
    """Parsează și formatează adresa din format SEW.

    Formatul tipic: "162, Bicaz, BACAU, BC, 600286"
    Output: "Bicaz 162, Bacău (BC)"

    Args:
        address_str: String cu adresa din API

    Returns:
        Adresa formatată pentru afișare
    """
    if not address_str or not isinstance(address_str, str):
        return ""

    parts = [p.strip() for p in address_str.split(",")]

    if len(parts) < 2:
        return address_str

    # Format: "número, localitate, județ_mare, județ_cod, cp"
    numero = parts[0] if parts[0] else ""
    localitate = parts[1].title() if len(parts) > 1 else ""
    judet_cod = parts[3].upper() if len(parts) > 3 else ""

    # Construiește afișarea: "Localitate Număr (Cod județ)"
    if localitate and numero:
        result = f"{localitate} {numero}"
    elif localitate:
        result = localitate
    else:
        result = address_str

    if judet_cod:
        result += f" ({judet_cod})"

    return result


def build_account_options(accounts: list[dict]) -> list[SelectOptionDict]:
    """Construiește lista de opțiuni pentru selectorul de conturi.

    Args:
        accounts: Lista de conturi din răspunsul API

    Returns:
        Lista de opțiuni pentru selectarea contururilor
    """
    options: list[SelectOptionDict] = []
    seen: set[str] = set()

    for account in accounts or []:
        if not isinstance(account, dict):
            continue

        uan = safe_get(account, "contractAccountID", default="").strip()
        if not uan or uan in seen:
            continue

        seen.add(uan)

        # Construiește adresa
        address = build_address_display(safe_get(account, "address", default=""))
        if not address:
            address = "Fără adresă"

        # Label final: "Address ➜ UAN"
        label = f"{address} ➜ {uan}"

        options.append(
            SelectOptionDict(
                value=uan,
                label=label,
            )
        )

    # Sortează alfabetic după label
    options.sort(key=lambda x: x["label"].lower())

    return options


def extract_all_accounts(accounts: list[dict]) -> list[str]:
    """Extrage toate codurile UAN unice din lista de conturi.

    Args:
        accounts: Lista de conturi din răspunsul API

    Returns:
        Lista de UAN-uri unice
    """
    result: list[str] = []
    for account in accounts or []:
        if isinstance(account, dict):
            uan = safe_get(account, "contractAccountID", default="").strip()
            if uan and uan not in result:
                result.append(uan)
    return result


def build_account_metadata(accounts: list[dict]) -> dict[str, dict]:
    """Construiește un dicționar cu metadatele relevante per cont.

    Args:
        accounts: Lista de conturi din răspunsul API

    Returns:
        Dicționar cu metadate: {UAN: {"address": str, ...}}
    """
    metadata: dict[str, dict] = {}
    for account in accounts or []:
        if not isinstance(account, dict):
            continue

        uan = safe_get(account, "contractAccountID", default="").strip()
        if not uan:
            continue

        metadata[uan] = {
            "accountNumber": safe_get(account, "accountNumber", default=""),
            "address": safe_get(account, "address", default=""),
            "pod": safe_get(account, "pod", default=""),
            "equipment_no": safe_get(account, "equipmentNo", default=""),
        }

    return metadata


# ══════════════════════════════════════════════
# Funcții pentru autentificare
# ══════════════════════════════════════════════

def resolve_selection(
    select_all: bool,
    selected: list[str],
    accounts: list[dict],
) -> list[str]:
    """Returnează lista finală de conturi selectate.

    Args:
        select_all: Dacă sunt selectate toate conturile
        selected: Lista de conturi selectate manual
        accounts: Lista completă de conturi din API

    Returns:
        Lista finală de UAN-uri selectate
    """
    if select_all:
        return extract_all_accounts(accounts)
    return selected


# ══════════════════════════════════════════════
# Funcții pentru entități de consum
# ══════════════════════════════════════════════

def build_usage_entity(
    previous_read: dict,
    new_meter_read: str = "",
    new_meter_read_date: str = ""
) -> dict:
    """Construiește entitatea UsageSelfMeterReadEntity din răspunsul GetPreviousMeterRead.

    Asamblează datele conturului pentru autocitire pe baza răspunsului API.

    Args:
        previous_read: Dicționar cu datele anterioare din GetPreviousMeterRead
        new_meter_read: Noua valoare a citirilor (opțional)
        new_meter_read_date: Data noii citiri (opțional)

    Returns:
        Dicționar cu structura completă a entității de consum
    """
    # Structura EXACTĂ din payload-ul care a returnat 200 OK (debug 23.03.2026).
    # Key-urile trebuie să fie IDENTICE cu cele din GetPreviousMeterRead response,
    # NU redenumite (ex: contractAccountID, NU UtilityAccountNumber).
    return {
        "contractAccountID": safe_get(previous_read, "contractAccountID", default=""),
        "accountID": safe_get(previous_read, "accountID", default=""),
        "equipmentNo": safe_get(previous_read, "equipmentNo", default=""),
        "registerNo": safe_get(previous_read, "registerNo", default=""),
        "registerType": safe_get(previous_read, "registerType", default=""),
        "uom": safe_get(previous_read, "uom", default="KWH"),
        "preDecimals": safe_get(previous_read, "preDecimals", default=""),
        "postDecimals": safe_get(previous_read, "postDecimals", default=""),
        "noMROrder": safe_get(previous_read, "noMROrder", default=""),
        "prevMRResult": safe_get(previous_read, "prevMRResult", default=""),
        "prevMRDate": safe_get(previous_read, "prevMRDate", default=""),
        "prevMRRsn": safe_get(previous_read, "prevMRRsn", default=""),
        "prevMRCat": safe_get(previous_read, "prevMRCat", default=""),
        "serialNumber": safe_get(previous_read, "serialNumber", default=""),
        "pod": safe_get(previous_read, "pod", default=""),
        "registerCat": safe_get(previous_read, "registerCat", default=""),
        "distributor": safe_get(previous_read, "distributor", default=""),
        "meterInterval": safe_get(previous_read, "meterInterval", default=""),
        "supplier": safe_get(previous_read, "supplier", default=""),
        "distCustomer": safe_get(previous_read, "distCustomer", default=""),
        "distCustomerId": safe_get(previous_read, "distCustomerId", default=""),
        "distContract": safe_get(previous_read, "distContract", default=""),
        "distContractDate": safe_get(previous_read, "distContractDate", default=""),
        "newmeterread": new_meter_read,
        "NewMeterReadDate": new_meter_read_date,
    }
