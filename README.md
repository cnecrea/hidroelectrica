![logo](https://github.com/user-attachments/assets/fef5f68d-5137-4fab-90c5-da8dc28abbae)

# Hidroelectrica România - Integrare pentru Home Assistant 🏠🇷🇴

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)
[![GitHub Release](https://img.shields.io/github/v/release/cnecrea/hidroelectrica)](https://github.com/cnecrea/hidroelectrica/releases)
[![Licență](https://img.shields.io/github/license/cnecrea/hidroelectrica)](https://github.com/cnecrea/hidroelectrica/blob/main/LICENSE.md)
[![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2025.11%2B-41BDF5?logo=homeassistant&logoColor=white)](https://www.home-assistant.io/)
[![GitHub Stars](https://img.shields.io/github/stars/cnecrea/hidroelectrica?style=flat&logo=github)](https://github.com/cnecrea/hidroelectrica/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/cnecrea/hidroelectrica?style=flat&logo=github)](https://github.com/cnecrea/hidroelectrica/network/members)
[![GitHub Watchers](https://img.shields.io/github/watchers/cnecrea/hidroelectrica?style=flat&logo=github)](https://github.com/cnecrea/hidroelectrica/watchers)
[![GitHub Issues](https://img.shields.io/github/issues/cnecrea/hidroelectrica)](https://github.com/cnecrea/hidroelectrica/issues)
[![Ultimul Commit](https://img.shields.io/github/last-commit/cnecrea/hidroelectrica)](https://github.com/cnecrea/hidroelectrica/commits/main)
[![Commit-uri/lună](https://img.shields.io/github/commit-activity/m/cnecrea/hidroelectrica)](https://github.com/cnecrea/hidroelectrica/commits/main)
[![Dimensiune Repo](https://img.shields.io/github/repo-size/cnecrea/hidroelectrica)](https://github.com/cnecrea/hidroelectrica)
[![Limbaj Principal](https://img.shields.io/github/languages/top/cnecrea/hidroelectrica)](https://github.com/cnecrea/hidroelectrica)
[![Total descărcări](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/cnecrea/hidroelectrica/main/statistici/shields/descarcari.json)](https://github.com/cnecrea/hidroelectrica/releases)
[![Descărcări ultima versiune](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/cnecrea/hidroelectrica/main/statistici/shields/ultima_release.json)](https://github.com/cnecrea/hidroelectrica/releases/latest)
![Badge](https://hitscounter.dev/api/hit?url=https%3A%2F%2Fgithub.com%2Fcnecrea%2Fhidroelectrica&label=vizitatori&icon=github&color=%23198754&message=&style=flat&tz=Europe%2FBucharest)


Această integrare pentru Home Assistant oferă **monitorizare completă** a datelor contractuale, facturilor curente, și istoricul plăților pentru utilizatorii Hidroelectrica România. Integrarea este configurabilă prin interfața UI și permite afișarea informațiilor utile în timp real. 🚀

## 🌟 Caracteristici

### Senzor `Date contract`:
  - **🔍 Monitorizare Generală**:
      - Afișează informații detaliate despre utilizator și cont.
  - **📊 Atribute disponibile**:
      - Numele și prenumele
      - Telefon de contact
      - Număr cont utilitate
      - Cod loc de consum (NLC)
      - Tip client
      - Adresa de consum
      - Localitate
      - Țară
      - Ultima actualizare de date

### Senzor `Index curent`:
  - **🔍 Monitorizare date index**:
      - Afișează informații detaliate despre indexul curent al contorului (**de moment, indisponibil**).
  - **📊 Atribute disponibile**:
      - **Numărul dispozitivului**: ID-ul dispozitivului asociat contorului.
      - **Tip de contor**: Indică tipul contorului.
      - **Data de început a citirii**: Data de început a perioadei de citire.
      - **Data de final a citirii**: Data de final a perioadei de citire.



### Senzor `Factură restantă`:
  - **🔍 Detalii despre solduri restante**:
      - Afișează dacă există facturi restante și data scadenței.
  - **📊 Atribute disponibile**:
      - Plată restantă (ex. "259.12 lei, depășită cu 1 zi")
      - Total neachitat

### Senzor `Arhivă`:
  - **📚 Date istorice**:
    - Afișează plățile lunare pentru fiecare an disponibil.
  - **📊 Atribute disponibile**:
    - **Plăți individuale**: Detalii pentru fiecare plată efectuată.
      - Exemplu: `Plată #1 factură luna octombrie: 118,83 lei`
    - **Plăți efectuate**: Numărul total de plăți din anul curent.
      - Exemplu: `Plăți efectuate: 13`
    - **Total suma achitată**: Suma totală achitată pentru anul curent.
      - Exemplu: `Total suma achitată: 2342.50 lei`

---

## ⚙️ Configurare

### 🛠️ Interfața UI:
1. Adaugă integrarea din meniul **Setări > Dispozitive și Servicii > Adaugă Integrare**.
2. Introdu datele contului Hidroelectrica:
   - **Nume utilizator**: username-ul contului tău Hidroelectrica.
   - **Parolă**: parola asociată contului tău.
3. Specifică intervalul de actualizare (implicit: 3600 secunde).

---

## 🚀 Instalare

### 💡 Instalare prin HACS:
1. Adaugă [depozitul personalizat](https://github.com/cnecrea/hidroelectrica) în HACS. 🛠️

[![Deschide instanța ta Home Assistant și accesează un depozit din cadrul magazinului comunitar Home Assistant (Home Assistant Community Store).](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=cnecrea&repository=hidroelectrica&category=Integration)

3. Caută integrarea **Hidroelectrica România** și instaleaz-o. ✅
4. Repornește Home Assistant și configurează integrarea. 🔄

### ✋ Instalare manuală:
1. Clonează sau descarcă [depozitul GitHub](https://github.com/cnecrea/hidroelectrica). 📂
2. Copiază folderul `custom_components/hidroelectrica` în directorul `custom_components` al Home Assistant. 🗂️
3. Repornește Home Assistant și configurează integrarea. 🔧

---

## ✨ Exemple de utilizare

### 🔔 Automatizare pentru Factură Restantă:
Creează o automatizare pentru a primi notificări când există o factură restantă.

```yaml
alias: Notificare Factură Restantă
description: Notificare dacă există facturi restante
trigger:
  - platform: state
    entity_id: sensor.hidroelectrica_factura_restanta_XXXXXXXX
    to: "Da"
action:
  - service: notify.mobile_app_your_phone
    data:
      title: "Factură Restantă Detectată! ⚡"
      message: "Aveți o factură restantă în valoare de {{ states('sensor.hidroelectrica_factura_restanta_XXXXXXXX') }}."
mode: single
```

### 🔍 Card pentru Dashboard:
Afișează datele despre utilizator, facturi restante și istoric plăți pe interfața Home Assistant.

```yaml
type: entities
title: Monitorizare Hidroelectrica România
entities:
  - entity: sensor.hidroelectrica_date_contract_XXXXXXXX
    name: Date Utilizator
  - entity: sensor.hidroelectrica_factura_restanta_XXXXXXXX
    name: Factură Restantă
  - entity: sensor.hidroelectrica_factura_restanta_XXXXXXXX
    name: Istoric Facturi Achitate
```

---

## ☕ Susține dezvoltatorul

Dacă ți-a plăcut această integrare și vrei să sprijini munca depusă, **invită-mă la o cafea**! 🫶  
Nu costă nimic, iar contribuția ta ajută la dezvoltarea viitoare a proiectului. 🙌  

[![Buy Me A Coffee](https://img.shields.io/badge/Buy%20Me%20A%20Coffee-Susține%20dezvoltatorul-orange?style=for-the-badge&logo=buy-me-a-coffee)](https://buymeacoffee.com/cnecrea)

Mulțumesc pentru sprijin și apreciez fiecare gest de susținere! 🤗

--- 

## 🧑‍💻 Contribuții

Contribuțiile sunt binevenite! Simte-te liber să trimiți un pull request sau să raportezi probleme [aici](https://github.com/cnecrea/hidroelectrica/issues).

---

## 🌟 Suport
Dacă îți place această integrare, oferă-i un ⭐ pe [GitHub](https://github.com/cnecrea/hidroelectrica/)! 😊
