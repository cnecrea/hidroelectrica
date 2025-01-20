
# Debugging pentru integrarea personalizată

Acest ghid oferă pașii necesari pentru a activa logarea detaliată și pentru a analiza problemele dintr-o integrare personalizată.

---

## 1. Activează logarea detaliată

### Adaugă în `configuration.yaml`:
Pentru a activa logarea detaliată pentru integrarea ta personalizată, editează fișierul `configuration.yaml` și adaugă următoarele:
```yaml
logger:
  default: warning
  logs:
    custom_components.hidroelectrica: debug
    homeassistant.const: critical
    homeassistant.loader: critical
    homeassistant.helpers.frame: critical
```

### Restartează sistemul
După ce ai salvat fișierul, repornește sistemul Home Assistant pentru ca modificările să fie aplicate.

---

## 2. Analizează logurile

### Localizarea logurilor
Logurile se află, de obicei, în fișierul `home-assistant.log`, în directorul principal al Home Assistant.

### Filtrarea logurilor
Pentru a găsi rapid informațiile relevante despre integrarea ta, poți folosi comanda:
```bash
grep 'custom_components.hidroelectrica' home-assistant.log
```

---

## Notă
Asigură-te că toate configurațiile din `configuration.yaml` sunt corecte înainte de a începe procesul de debugging.



# Cum să postezi cod în discuții

Pentru a posta cod în mod corect și lizibil, utilizează blocuri de cod delimitate de trei backticks (```) urmate de limbajul codului. De exemplu, pentru YAML, folosește:

<pre>
```yaml
2025-01-20 15:35:12 INFO     custom_components.example_integration: Initializing Example Integration.
2025-01-20 15:35:13 DEBUG    custom_components.example_integration: Configuration loaded: {'username': 'test_user', 'update_interval': 30}
2025-01-20 15:35:14 INFO     custom_components.example_integration.api: Attempting to authenticate user 'test_user'.
2025-01-20 15:35:15 ERROR    custom_components.example_integration.api: Authentication failed. Invalid credentials provided.
2025-01-20 15:35:16 DEBUG    custom_components.example_integration: Retrying authentication in 10 seconds.
```
</pre>

Rezultatul va arăta astfel:

```yaml
2025-01-20 15:35:12 INFO     custom_components.example_integration: Initializing Example Integration.
2025-01-20 15:35:13 DEBUG    custom_components.example_integration: Configuration loaded: {'username': 'test_user', 'update_interval': 30}
2025-01-20 15:35:14 INFO     custom_components.example_integration.api: Attempting to authenticate user 'test_user'.
2025-01-20 15:35:15 ERROR    custom_components.example_integration.api: Authentication failed. Invalid credentials provided.
2025-01-20 15:35:16 DEBUG    custom_components.example_integration: Retrying authentication in 10 seconds.
```

## Pași pentru a posta cod:
1. Scrie ` ```yaml ` (trei backticks urmate de "yaml").
2. Adaugă codul tău pe liniile următoare.
3. Încheie cu alte trei backticks: ` ``` `.

Astfel, codul va fi formatat corespunzător și ușor de citit de ceilalți utilizatori.
