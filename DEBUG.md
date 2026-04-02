# Ghid de depanare — Hidroelectrica România

Acest ghid acoperă activarea logării detaliate, interpretarea mesajelor din loguri și pașii de depanare pentru cele mai comune probleme.

---

## 1. Activarea logării detaliate

Editează `configuration.yaml` și adaugă:

```yaml
logger:
  default: warning
  logs:
    custom_components.hidroelectrica: debug
    homeassistant.const: critical
    homeassistant.loader: critical
    homeassistant.helpers.frame: critical
```

Repornește Home Assistant pentru a aplica modificările.

---

## 2. Structura logurilor

Integrarea generează loguri pe module separate. Filtrează după modulul relevant:

```bash
grep 'custom_components.hidroelectrica' home-assistant.log
```

### Module și ce loghează fiecare

| Modul | Ce loghează |
|---|---|
| `__init__` | Inițializare, conturi selectate, token-uri, migrare config entry |
| `coordinator` | Fazele de refresh (ușor/greu), erori API, structura datelor obținute |
| `sensor` | Crearea senzorilor, detecție prosumator, filtrare registre |
| `button` | Crearea/excluderea butonului Trimite Index, detecție prosumator |
| `api` | Autentificare, reautentificare 401, erori HTTP, request-uri API |
| `config_flow` | Fluxul de configurare, validare credențiale, selecție conturi |

### Mesaje importante de urmărit

**Refresh reușit:**
```
Date grele (UAN=XXXXX): usage=OK, billing=OK, counter_series=OK, read_history=OK.
```

**Prosumator detectat:**
```
Prosumator detectat (UAN=XXXXX): CitirePermisaSensor NU se creează (distribuitorul citește contorul automat).
Prosumator detectat (UAN=XXXXX): creat IndexEnergieProdusSensor.
```

**Reautentificare automată:**
```
Am primit 401 la [endpoint]. Se reîncearcă cu token nou.
```

**Licență — heartbeat:**
```
[LICENSE] Heartbeat OK. Licența este validă (expiră: 2027-01-15).
```

**Erori API:**
```
HTTP XXX la [endpoint]: [mesaj eroare]
```

**Licență invalidă:**
```
[LICENSE] Licența nu este validă. Motiv: expired / invalid_key / server_unreachable.
```

---

## 3. Probleme comune și soluții

### Senzorii afișează „Indisponibil"

**Cauză posibilă:** Prima actualizare a eșuat sau API-ul nu a răspuns.

**Soluție:**
1. Verifică logurile pentru erori la `async_config_entry_first_refresh`.
2. Verifică conectivitatea la `ihidro.ro`.
3. Reîncarcă integrarea din **Setări** → **Dispozitive și Servicii** → **Hiroelectrica** → **Reîncarcă**.

### Index energie = 0

**Cauză:** API-ul Hidroelectrica nu furnizează indexul curent în afara ferestrei de citire.

**Comportament normal:** Integrarea folosește un fallback în cascadă:
1. `meter_read_history` (cea mai recentă citire din istoricul de citiri)
2. `previous_meter_read` (ultima citire cunoscută de API)
3. `meter_counter_series` (indexul din seria contorului)

Dacă toate trei sunt goale, indexul va fi 0. Acest lucru se întâmplă la conturile noi sau la cele fără citiri înregistrate.

### Datele nu se actualizează

**Cauză posibilă:** Datele grele (consum, plăți, citiri) se actualizează doar la fiecare al 4-lea refresh.

**Soluție:**
1. Așteaptă 4 cicluri de refresh (implicit: 4 ore).
2. Sau reîncarcă integrarea — primul refresh include întotdeauna datele grele.

### Butonul „Trimite index" nu apare

**Cauze posibile:**
1. Contul este de prosumator — la prosumatori, distribuitorul citește contorul automat. Butonul nu se creează.
2. Fereastra de citire nu este activă.

**Verificare:** Caută în loguri mesajul:
```
Prosumator detectat (UAN=XXXXX): butonul 'Trimite index' NU se creează
```

---

## 4. Testare cu date de debug

Dacă ai fișierele JSON de debug (generate prin scriptul de test), poți rula testul de simulare:

```bash
cd custom_components/hidroelectrica
python3 test_both_accounts.py
```

Testul verifică: index consum, detecție prosumator, index producție, sold factură, separare registre consum/producție, separare plăți normale/compensații ANRE.

---

## 5. Cum să postezi cod în discuții

Pentru a posta loguri sau cod în mod lizibil pe GitHub, folosește blocuri de cod:

<pre>
```yaml
2026-03-16 10:00:00 DEBUG custom_components.hidroelectrica.coordinator: Date grele (UAN=XXXXXXXXXX): usage=OK, billing=OK...
```
</pre>

Rezultat:

```yaml
2026-03-16 10:00:00 DEBUG custom_components.hidroelectrica.coordinator: Date grele (UAN=XXXXXXXXXX): usage=OK, billing=OK...
```

### Pași:
1. Scrie `` ```yaml `` (trei backticks urmate de `yaml`).
2. Adaugă logurile pe liniile următoare.
3. Încheie cu alte trei backticks: `` ``` ``.
