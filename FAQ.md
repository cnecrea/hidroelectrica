<a name="top"></a>
# Întrebări frecvente

- [Cum instalez integrarea în Home Assistant?](#cum-instalez-integrarea-în-home-assistant)
- [Observ în loguri „Am primit 401". De ce?](#observ-în-loguri-am-primit-401-de-ce)
- [De ce primesc o eroare 500 (Internal Server Error)?](#de-ce-primesc-o-eroare-500-internal-server-error)
- [Indexul afișează valoarea 0. De ce?](#indexul-afișează-valoarea-0-de-ce)
- [Ce este un prosumator și cum îl detectează integrarea?](#ce-este-un-prosumator-și-cum-îl-detectează-integrarea)
- [De ce nu apare butonul „Trimite index"?](#de-ce-nu-apare-butonul-trimite-index)
- [De ce nu apare senzorul „Citire permisă"?](#de-ce-nu-apare-senzorul-citire-permisă)
- [Ce diferență este între „Arhivă plăți" și „Arhivă plăți prosumator"?](#ce-diferență-este-între-arhivă-plăți-și-arhivă-plăți-prosumator)
- [Ce înseamnă „Credit" la Sold factură?](#ce-înseamnă-credit-la-sold-factură)
- [Datele nu se actualizează. Ce fac?](#datele-nu-se-actualizează-ce-fac)
- [Pot monitoriza mai multe conturi?](#pot-monitoriza-mai-multe-conturi)
- [Ce e licența și de ce am nevoie de ea?](#ce-e-licența-și-de-ce-am-nevoie-de-ea)
- [Am introdus licența dar senzorii tot arată „Licență necesară". De ce?](#am-introdus-licența-dar-senzorii-tot-arată-licență-necesară-de-ce)

---

## Cum instalez integrarea în Home Assistant?

[Înapoi sus](#top)

**Răspuns:**

HACS (Home Assistant Community Store) permite instalarea integrărilor personalizate.

1. **Verifică HACS** — Navighează la **Setări** → **Dispozitive și servicii** → **Integrări** și caută „HACS". Dacă nu este instalat, urmează [ghidul oficial HACS](https://hacs.xyz/docs/use).
2. **Adaugă depozitul** — În HACS, apasă cele trei puncte din colțul dreapta-sus → **Repositories** → adaugă `https://github.com/cnecrea/hidroelectrica` cu tipul **Integration**.
3. **Instalează** — Caută „Hidroelectrica România" în HACS → **Download**.
4. **Repornește** Home Assistant.
5. **Configurează** — **Setări** → **Dispozitive și servicii** → **Adaugă integrare** → caută „Hidroelectrica România" → introdu username și parola → selectează conturile dorite.

---

## Observ în loguri „Am primit 401". De ce?

[Înapoi sus](#top)

**Răspuns:**

Este un comportament complet normal. Mesajul „401 Unauthorized" apare când sesiunea curentă expiră. Integrarea detectează acest răspuns și se reautentifică automat — nu este necesară nicio intervenție.

Sesiunile expiră periodic ca măsură standard de securitate implementată de serverul SEW. Integrarea gestionează complet acest proces.

Dacă mesajul apare în mod continuu și senzorii rămân indisponibili, verifică dacă username-ul și parola sunt corecte în configurarea integrării.

---

## De ce primesc o eroare 500 (Internal Server Error)?

[Înapoi sus](#top)

**Răspuns:**

O eroare 500 indică o problemă internă pe serverul Hidroelectrica, nu o problemă a integrării. Integrarea trimite cereri valide, dar serverul nu le poate procesa temporar.

Aceasta se rezolvă de obicei singură în câteva minute sau ore. Integrarea va reîncerca automat la următorul ciclu de refresh. Dacă problema persistă mai mult de 24 de ore, este posibil ca serverul Hidroelectrica să aibă o întrerupere majoră.

---

## Indexul afișează valoarea 0. De ce?

[Înapoi sus](#top)

**Răspuns:**

În versiunea 3.0.0, integrarea folosește un sistem de fallback în cascadă pentru a obține indexul:

1. **meter_read_history** — cea mai recentă citire din istoricul complet de citiri.
2. **previous_meter_read** — ultima citire cunoscută, raportată de API.
3. **meter_counter_series** — indexul extras din seria contorului activ.

Dacă toate cele trei surse sunt goale (cont nou, fără citiri înregistrate), indexul va fi 0. Aceasta nu este o eroare a integrării, ci reflectă lipsa datelor în API-ul Hidroelectrica.

La conturile cu istoric de citiri, indexul ar trebui să afișeze corect ultima valoare cunoscută.

---

## Ce este un prosumator și cum îl detectează integrarea?

[Înapoi sus](#top)

**Răspuns:**

Un prosumator este un utilizator care atât consumă, cât și produce energie electrică (de exemplu, prin panouri fotovoltaice). Contorul unui prosumator înregistrează două tipuri de date: consum (registrul `1.8.0`) și producție (registrul `1.8.0_P`).

Integrarea detectează automat prosumatorii verificând prezența registrului `1.8.0_P` în istoricul de citiri (`GetMeterReadHistory`). Dacă există cel puțin o citire cu acest registru, contul este clasificat ca prosumator.

Senzorii suplimentari creați pentru prosumator: **Index energie produsă**, **Arhivă index energie produsă**, **Arhivă plăți prosumator** (compensații ANRE).

---

## De ce nu apare butonul „Trimite index"?

[Înapoi sus](#top)

**Răspuns:**

La conturile de prosumator, butonul „Trimite index" nu se creează. Motivul: la prosumatori, distribuitorul citește contorul automat — nu este necesară autocitirea.

Dacă ai un cont de consum normal și butonul tot nu apare, verifică:
1. Fereastra de citire — butonul funcționează doar în perioada activă de autocitire.
2. Logurile — caută mesajul „Prosumator detectat" sau erori la crearea butonului.

---

## De ce nu apare senzorul „Citire permisă"?

[Înapoi sus](#top)

**Răspuns:**

Identic cu butonul „Trimite index": la prosumatori, senzorul „Citire permisă" nu se creează, deoarece autocitirea nu este aplicabilă — distribuitorul se ocupă de citire.

---

## Ce diferență este între „Arhivă plăți" și „Arhivă plăți prosumator"?

[Înapoi sus](#top)

**Răspuns:**

Cei doi senzori separă tipurile de tranzacții financiare:

- **Arhivă plăți** — plățile efectuate de utilizator către companie (canale de tip `Incasari-Online`, `Incasari-BCR`, etc.). Prezent la toate conturile.
- **Arhivă plăți prosumator** — compensațiile ANRE primite de prosumator (canale de tip `Comp ANRE-furn.en.el`, `Comp ANRE-dist.en.el`). Prezent doar la conturi de prosumator.

La un cont non-prosumator, apare doar „Arhivă plăți".

---

## Ce înseamnă „Credit" la Sold factură?

[Înapoi sus](#top)

**Răspuns:**

Starea „Credit" apare când soldul este negativ — adică utilizatorul are un credit în cont. Acest lucru este tipic pentru prosumatori, unde compensațiile ANRE pot depăși facturile de plată.

De exemplu: sold = -5,21 lei înseamnă că Hidroelectrica îi datorează utilizatorului 5,21 lei.

---

## Datele nu se actualizează. Ce fac?

[Înapoi sus](#top)

**Răspuns:**

Integrarea folosește un mecanism de refresh în două faze:
- **Datele ușoare** (sold, index, fereastră citire) se actualizează la fiecare ciclu (implicit: 1 oră).
- **Datele grele** (consum, plăți, citiri, serii contor) se actualizează doar la fiecare al 4-lea ciclu (implicit: la 4 ore).

Dacă ai modificat recent o plată sau o citire, poate dura până la 4 ore până apare în senzori. Poți forța o actualizare completă reîncărcând integrarea: **Setări** → **Dispozitive și Servicii** → **Hidroelectrica** → **Reîncarcă**.

---

## Pot monitoriza mai multe conturi?

[Înapoi sus](#top)

**Răspuns:**

Da. La configurare, poți selecta mai multe conturi (UAN-uri) asociate aceluiași utilizator. Fiecare cont va avea propriul set de senzori, cu identificare prin UAN în numele entității.

Integrarea creează un dispozitiv separat pentru fiecare UAN, cu toți senzorii grupați sub acel dispozitiv.

---

## Ce e licența și de ce am nevoie de ea?

[Înapoi sus](#top)

**Răspuns:**

Integrarea folosește un sistem de licențiere server-side cu semnături Ed25519 și HMAC-SHA256. Fără o licență validă, integrarea afișează doar senzorul „Licență necesară" și nu creează senzori sau butoane funcționale.

Licența se achiziționează de la: [hubinteligent.org/donate?ref=hidroelectrica](https://hubinteligent.org/donate?ref=hidroelectrica)

După achiziție, introdu cheia de licență din OptionsFlow:
1. **Setări** → **Dispozitive și Servicii** → **Hidroelectrica România** → **Configurare**
2. Selectează **Licență**
3. Completează câmpul „Cheie licență"
4. Salvează

---

## Am introdus licența dar senzorii tot arată „Licență necesară". De ce?

[Înapoi sus](#top)

**Răspuns:**

Câteva cauze posibile:

1. **Licența nu a fost validată** — verifică logurile pentru mesaje cu `LICENSE`
2. **Serverul de licențe nu este accesibil** — dacă HA nu are acces la internet, validarea eșuează
3. **Cheie greșită** — verifică că ai copiat cheia corect, fără spații suplimentare
4. **Restartare necesară** — în rare cazuri, un restart al HA poate rezolva problema

Activează debug logging ([DEBUG.md](DEBUG.md)) și caută mesaje legate de licență.
