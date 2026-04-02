# Ghid de instalare și configurare — Hidroelectrica România

---

## Cerințe preliminare

- **Home Assistant** versiunea 2025.11 sau mai recentă.
- **HACS** (Home Assistant Community Store) instalat. Dacă nu este instalat, urmează [ghidul oficial HACS](https://hacs.xyz/docs/use).
- Un cont activ pe platforma Hidroelectrica România (aplicația iHidro sau contul online).
- **Licență** validă — de la [hubinteligent.org/licenta/hidroelectrica](https://hubinteligent.org/licenta/hidroelectrica)

---

## Pasul 1 — Instalarea integrării

### Varianta A: Prin HACS (recomandat)

1. Deschide Home Assistant → bara laterală → **HACS**.
2. Apasă pe cele **trei puncte** din colțul dreapta-sus → **Custom repositories**.
3. Introdu URL-ul depozitului:
   ```
   https://github.com/cnecrea/hidroelectrica
   ```
4. Selectează tipul: **Integration** → **Add**.
5. Caută **Hidroelectrica România** în lista de integrări HACS → **Download**.
6. Repornește Home Assistant.

Alternativ, apasă direct pe butonul de mai jos:

[![Deschide HACS](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=cnecrea&repository=hidroelectrica&category=Integration)

### Varianta B: Instalare manuală

1. Descarcă sau clonează depozitul:
   ```bash
   git clone https://github.com/cnecrea/hidroelectrica.git
   ```
2. Copiază folderul `custom_components/hidroelectrica` în directorul `custom_components` al Home Assistant:
   ```
   /config/custom_components/hidroelectrica/
   ```
3. Verifică structura — trebuie să existe cel puțin:
   ```
   custom_components/
   └── hidroelectrica/
       ├── __init__.py
       ├── api.py
       ├── button.py
       ├── config_flow.py
       ├── const.py
       ├── coordinator.py
       ├── helpers.py
       ├── manifest.json
       ├── sensor.py
       ├── strings.json
       └── translations/
           ├── en.json
           └── ro.json
   ```
4. Repornește Home Assistant.

---

## Pasul 2 — Configurarea integrării

### 2.1 Adăugarea integrării

1. Navighează la **Setări** → **Dispozitive și Servicii** → **Adaugă Integrare**.
2. Caută **Hidroelectrica România**.
3. Se va deschide formularul de autentificare.

### 2.2 Autentificare (Pasul 1 din configurare)

Introdu datele contului tău Hidroelectrica:

| Câmp | Descriere | Obligatoriu |
|---|---|---|
| **Username (email)** | Adresa de email utilizată pe platforma iHidro | Da |
| **Password** | Parola contului iHidro | Da |
| **Update interval (seconds)** | Intervalul de actualizare a datelor | Nu (implicit: 3600) |

**Intervalul de actualizare:**
- Minim: 300 secunde (5 minute)
- Implicit: 3600 secunde (1 oră)
- Maxim: 86400 secunde (24 ore)

Un interval prea mic poate genera cereri excesive către serverul Hidroelectrica. Se recomandă valoarea implicită de 3600 secunde.

Apasă **Trimite**. Integrarea va valida credențialele și va obține lista de conturi asociate.

**Erori posibile la acest pas:**
- `Authentication failed` — username sau parolă incorectă.
- `No accounts found` — autentificarea a reușit, dar nu s-au găsit conturi de utilitate. Verifică dacă contul are cel puțin un contract activ pe platforma iHidro.
- `An unexpected error occurred` — eroare de comunicare cu serverul. Verifică conexiunea la internet și reîncearcă.

### 2.3 Selecția conturilor (Pasul 2 din configurare)

După autentificarea reușită, se afișează lista conturilor descoperite:

| Opțiune | Descriere |
|---|---|
| **Select all accounts** | Bifează pentru a monitoriza toate conturile |
| **Accounts** | Selectează individual conturile dorite |

Fiecare cont este identificat prin **UAN** (Utility Account Number) și afișat cu adresa de consum asociată.

Apasă **Trimite** pentru a finaliza configurarea. Integrarea va crea un dispozitiv pentru fiecare cont selectat, cu toți senzorii asociați.

### 2.4 Licență (Pasul 3 din configurare)

Integrarea necesită o **licență validă** pentru a funcționa. Fără licență:
- Se creează doar senzorul `sensor.hidroelectrica_{nlc}_licenta` cu valoarea „Licență necesară"
- Toți senzorii normali și butonul sunt dezactivate

Pentru a introduce licența:
1. **Setări** → **Dispozitive și Servicii**
2. Găsește **Hidroelectrica România** → click pe **Configurare**
3. Selectează **Licență**
4. Introdu cheia de licență
5. Click **Salvează**

Licențe disponibile la: [hubinteligent.org/licenta/hidroelectrica](https://hubinteligent.org/licenta/hidroelectrica)

---

## Pasul 3 — Verificare

După configurare, navighează la **Setări** → **Dispozitive și Servicii** → **Hidroelectrica România**.

### Dispozitive create

Pentru fiecare cont selectat, se creează un dispozitiv cu numele `Hidroelectrica România (UAN)`. Sub fiecare dispozitiv, vei găsi senzorii disponibili.

### Senzori la un cont normal (non-prosumator)

| Senzor | Ce afișează |
|---|---|
| Date contract | Informații utilizator, adresă, serie contor |
| Sold factură | Sold curent: Da / Nu / Credit |
| Factură restantă | Da / Nu + zile întârziere |
| Index energie | Ultimul index de consum (kWh) |
| Citire permisă | Fereastra de autocitire activă/inactivă |
| Arhivă consum | Consumul lunar pe ultimul an disponibil |
| Arhivă index | Istoricul citirilor de index pe ultimul an |
| Arhivă plăți | Plățile efectuate pe ultimul an |

### Senzori suplimentari la un cont de prosumator

Detectarea prosumatorului este automată. Senzorii suplimentari apar fără configurare:

| Senzor | Ce afișează |
|---|---|
| Index energie produsă | Ultimul index de producție (kWh) |
| Arhivă index energie produsă | Istoricul citirilor de producție |
| Arhivă plăți prosumator | Compensațiile ANRE primite |

La prosumator, senzorii **Citire permisă** și butonul **Trimite index** nu se creează (distribuitorul citește contorul automat).

### Buton

| Buton | Ce face | Disponibilitate |
|---|---|---|
| Trimite index | Trimite autocitirea în fereastra activă | Doar non-prosumator |

---

## Modificarea configurării

### Schimbarea intervalului de actualizare

1. **Setări** → **Dispozitive și Servicii** → **Hidroelectrica România** → **Configurează**.
2. Modifică intervalul → **Trimite**.
3. Integrarea se reîncarcă automat cu noul interval.

### Schimbarea credențialelor

1. **Setări** → **Dispozitive și Servicii** → **Hidroelectrica România** → **Configurează**.
2. Introdu noul username și/sau parolă → **Trimite**.
3. Se va revalida autentificarea și se va afișa din nou lista de conturi.

### Adăugarea/eliminarea conturilor

1. **Setări** → **Dispozitive și Servicii** → **Hidroelectrica România** → **Configurează**.
2. La pasul de selecție conturi, bifează/debifează conturile dorite → **Trimite**.
3. Integrarea se reîncarcă cu noua selecție.

---

## Dezinstalare

1. **Setări** → **Dispozitive și Servicii** → **Hidroelectrica România** → **Șterge**.
2. Confirmă ștergerea.
3. Dacă vrei să dezinstalezi complet: deschide HACS → caută integrarea → **Remove** → repornește Home Assistant.

---

## Depanare rapidă

| Problemă | Soluție |
|---|---|
| Senzorii afișează „Indisponibil" | Reîncarcă integrarea sau verifică logurile (vezi [DEBUG.md](DEBUG.md)) |
| Index = 0 | Normal dacă nu există citiri în API. Vezi [FAQ.md](FAQ.md) |
| Datele nu se actualizează | Datele grele se actualizează la fiecare al 4-lea ciclu. Reîncarcă integrarea pentru refresh complet |
| Erori 401 în loguri | Normal — reautentificarea este automată |
| Erori 500 în loguri | Problemă pe serverul Hidroelectrica, nu pe integrare |

Pentru depanare detaliată, consultă [DEBUG.md](DEBUG.md).
Pentru întrebări frecvente, consultă [FAQ.md](FAQ.md).
