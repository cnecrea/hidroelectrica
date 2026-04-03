# Hidroelectrica România — Integrare Home Assistant

[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.11%2B-41BDF5?logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/cnecrea/hidroelectrica)](https://github.com/cnecrea/hidroelectrica/releases)
[![GitHub Stars](https://img.shields.io/github/stars/cnecrea/hidroelectrica?style=flat&logo=github)](https://github.com/cnecrea/hidroelectrica/stargazers)
[![Instalări](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/cnecrea/hidroelectrica/main/statistici/shields/descarcari.json)](https://github.com/cnecrea/hidroelectrica)
[![Ultima versiune](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/cnecrea/hidroelectrica/main/statistici/shields/ultima_release.json)](https://github.com/cnecrea/hidroelectrica/releases/latest)

Integrare Home Assistant pentru **monitorizarea completă** a conturilor Hidroelectrica România. Suport complet pentru conturi de consum și conturi de **prosumator**, cu detectare automată și senzori dedicați. Datele sunt obținute prin platforma SEW (Smart Energy Water) și sunt actualizate periodic.

---

## Caracteristici

### Senzori de bază (prezenți pentru orice cont)

**Date contract**
- Afișează informații detaliate despre utilizator și cont.
- Atribute: nume, prenume, telefon, număr cont utilitate (UAN), cod loc de consum (NLC), tip client, adresă, localitate, serie contor activă.

**Sold factură**
- Starea curentă: `Da` (sold de plată), `Nu` (achitat integral), `Credit` (credit prosumator).
- Atribute: suma datorată sau creditul disponibil, data scadenței, detalii factură curentă.

**Factură restantă**
- Indică `Da` sau `Nu` dacă există facturi neplătite după data scadenței.
- Atribute: suma restantă, numărul de zile de întârziere.

**Index energie activă**
- Indexul curent al contorului (registrul 1.8.0 — energie activă consumată).
- Sursă: `meter_read_history` → `previous_meter_read` → `meter_counter_series` (fallback în cascadă).
- Unitate de măsură: kWh.

**Citire permisă** *(doar la non-prosumator)*
- Afișează dacă fereastra de autocitire este activă și datele de început/sfârșit.
- La prosumator, acest senzor nu se creează (distribuitorul citește contorul automat).

### Senzori de arhivă

**Arhivă consum** *(anul cel mai recent)*
- Consumul lunar din datele de utilizare (`GetUsageGeneration`).
- Atribute: consum pe fiecare lună disponibilă, total anual.

**Arhivă index** *(anul cel mai recent)*
- Istoricul citirilor de index din `GetMeterReadHistory`.
- La prosumator, filtrează automat doar registrul 1.8.0 (consum), excluzând producția.
- Atribute: fiecare citire cu data, indexul, tipul citirii (autocitire/distribuitor/estimare).

**Arhivă plăți** *(anul cel mai recent)*
- Plățile efective realizate de utilizator către companie (canale de tip `Incasari-*`).
- Atribute: fiecare plată cu luna, canalul de plată, suma; total plăți, sumă totală.

### Senzori exclusivi prosumator

Acești senzori se creează **automat** când integrarea detectează registrul `1.8.0_P` în istoricul de citiri.

**Index energie produsă**
- Indexul curent al producției (registrul 1.8.0_P — energie activă produsă).
- Unitate de măsură: kWh.

**Arhivă index energie produsă** *(anul cel mai recent)*
- Istoricul citirilor de index producție (doar registrul 1.8.0_P).
- Atribute: fiecare citire cu data, indexul, tipul citirii.

**Arhivă plăți prosumator** *(anul cel mai recent)*
- Compensațiile ANRE primite (canale de tip `Comp ANRE-*`).
- Atribute: fiecare compensație cu luna, canalul (furnizor/distribuitor), suma; total compensații, sumă totală.

### Buton

**Trimite index** *(doar la non-prosumator)*
- Permite trimiterea autocitrii când fereastra de citire este activă.
- La prosumator, butonul nu se creează (distribuitorul citește contorul automat).

### Licență

**Sistem de licență** — fără licență validă se afișează doar senzorul „Licență necesară".

---

## Arhitectură tehnică

### Surse de date API (platforma SEW)

| Endpoint | Date furnizate | Frecvență |
|---|---|---|
| `GetMultiMeter` | Detalii contor, tip client | La fiecare refresh |
| `GetBill` | Sold curent, scadență | La fiecare refresh |
| `GetWindowDatesENC` / `GetWindowDates` | Fereastră autocitire | La fiecare refresh |
| `GetPods` | POD, instalație | La fiecare refresh |
| `GetPreviousMeterRead` | Index curent (consum + producție) | La fiecare refresh |
| `GetUsageGeneration` | Consum lunar istoric | La fiecare al 4-lea refresh |
| `GetBillingHistoryList` | Istoric plăți | La fiecare al 4-lea refresh |
| `GetMeterCounterSeries` | Serii contor | La fiecare al 4-lea refresh |
| `GetMeterReadHistory` | Istoric citiri index | La fiecare al 4-lea refresh |

### Strategia de refresh

Coordonatorul folosește un mecanism de refresh în două faze pentru a reduce încărcarea API:
- **Faza 1** (la fiecare refresh): date ușoare — contor, factură, fereastră citire, POD, index curent.
- **Faza 2** (la fiecare al 4-lea refresh): date grele — consum istoric, plăți, serii contor, citiri index.

Primul refresh include întotdeauna ambele faze.

### Detecție prosumator

Detecția se face automat pe baza prezenței registrului `1.8.0_P` în `GetMeterReadHistory`. Nu depinde de flag-uri precum `IsAMI`.

### Gestiunea sesiunii

- Token partajat între toate conturile unui utilizator.
- Reautentificare automată la expirarea sesiunii (401).
- Token injectat din `config_flow` la configurare sau din `config_entry.data` la restart.

---

## Configurare

### Interfața UI
1. **Setări** → **Dispozitive și Servicii** → **Adaugă Integrare** → caută **Hidroelectrica România**.
2. Introdu datele contului Hidroelectrica (username + parolă).
3. Selectează conturile (UAN-urile) pe care vrei să le monitorizezi.
4. Specifică intervalul de actualizare (implicit: 3600 secunde, minim: 300, maxim: 86400).

### Configurare licență
Integrarea necesită o licență validă. După configurarea contului, mergi la **Setări** → **Dispozitive și Servicii** → **Hidroelectrica România** → **Configurare** și introdu cheia de licență în secțiunea **Licență**.

### Opțiuni configurabile
- Interval de actualizare (modificabil din opțiunile integrării fără a reconfigura).
- Licență (modificabilă din opțiunile integrării fără a reconfigura).

---

## Cerințe

- **Home Assistant** versiunea 2025.11 sau mai recentă.
- **HACS** instalat (opțional, dar recomandat).
- Un cont activ pe platforma Hidroelectrica România (aplicația iHidro sau contul online).
- **Licență** validă — [hubinteligent.org/donate?ref=hidroelectrica](https://hubinteligent.org/donate?ref=hidroelectrica)

## Instalare

### Prin HACS
1. Adaugă [depozitul personalizat](https://github.com/cnecrea/hidroelectrica) în HACS.

[![Deschide instanța ta Home Assistant și accesează un depozit din cadrul magazinului comunitar Home Assistant (Home Assistant Community Store).](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=cnecrea&repository=hidroelectrica&category=Integration)

2. Caută integrarea **Hidroelectrica România** și instaleaz-o.
3. Repornește Home Assistant și configurează integrarea.

### Instalare manuală
1. Descarcă sau clonează [depozitul GitHub](https://github.com/cnecrea/hidroelectrica).
2. Copiază folderul `custom_components/hidroelectrica` în directorul `custom_components` al Home Assistant.
3. Repornește Home Assistant și configurează integrarea.

---

## Exemple de utilizare

### Automatizare pentru factură restantă

```yaml
alias: Notificare Factură Restantă
description: Notificare dacă există facturi restante
trigger:
  - platform: state
    entity_id: sensor.hidroelectrica_XXXXXXXX_factura_restanta
    to: "Da"
action:
  - service: notify.mobile_app_telefon
    data:
      title: "Factură Restantă Detectată"
      message: >-
        Ai o factură restantă Hidroelectrica.
        Verifică detaliile în Home Assistant.
mode: single
```

### Card pentru Dashboard (cont normal)

```yaml
type: entities
title: Hidroelectrica România
entities:
  - entity: sensor.hidroelectrica_XXXXXXXX_date_contract
    name: Date Contract
  - entity: sensor.hidroelectrica_XXXXXXXX_sold_factura
    name: Sold Factură
  - entity: sensor.hidroelectrica_XXXXXXXX_factura_restanta
    name: Factură Restantă
  - entity: sensor.hidroelectrica_XXXXXXXX_index_energie
    name: Index Energie
  - entity: sensor.hidroelectrica_XXXXXXXX_citire_permisa
    name: Citire Permisă
```

### Card pentru Dashboard (prosumator)

```yaml
type: entities
title: Hidroelectrica România (Prosumator)
entities:
  - entity: sensor.hidroelectrica_XXXXXXXX_date_contract
    name: Date Contract
  - entity: sensor.hidroelectrica_XXXXXXXX_sold_factura
    name: Sold Factură
  - entity: sensor.hidroelectrica_XXXXXXXX_index_energie
    name: Index Consum
  - entity: sensor.hidroelectrica_XXXXXXXX_index_energie_produsa
    name: Index Producție
  - entity: sensor.hidroelectrica_XXXXXXXX_arhiva_plati_2026
    name: Plăți 2026
  - entity: sensor.hidroelectrica_XXXXXXXX_arhiva_plati_prosumator_2026
    name: Compensații ANRE 2026
```

---

## Structura fișierelor

```
custom_components/hidroelectrica/
├── __init__.py          # Setup/unload integrare (runtime_data, licență)
├── api.py               # HidroelectricaApiClient — autentificare, GET
├── button.py            # Butonul Trimite index (doar non-prosumator)
├── config_flow.py       # ConfigFlow + OptionsFlow (autentificare, licență)
├── const.py             # Constante, URL-uri API
├── coordinator.py       # DataUpdateCoordinator — refresh în două faze
├── helpers.py           # Funcții utilitare
├── license.py           # Manager licență (server-side, Ed25519, HMAC-SHA256)
├── manifest.json        # Metadata integrare
├── sensor.py            # Senzori (date contract, sold, index, etc.)
├── strings.json         # Traduceri implicite (engleză)
└── translations/
    ├── en.json          # Traduceri engleză
    └── ro.json          # Traduceri române
```

---

## Susține dezvoltatorul

Dacă ți-a plăcut această integrare și vrei să sprijini munca depusă, **invită-mă la o cafea**!

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Susține%20dezvoltatorul-orange?style=for-the-badge&logo=buy-me-a-coffee)](https://buymeacoffee.com/cnecrea)

---

## Contribuții

Contribuțiile sunt binevenite! Trimite un pull request sau raportează probleme [aici](https://github.com/cnecrea/hidroelectrica/issues).

---

## Suport

Dacă îți place această integrare, oferă-i un ⭐ pe [GitHub](https://github.com/cnecrea/hidroelectrica/)!
