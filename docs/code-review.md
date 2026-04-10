# Code Review — Arbiter Memory Broker

_Data: 2026-04-10 | Reviewer: Hive-mind `hive-1775804308630-m4eq2j` (5 specialist, mesh topology, Byzantine consensus) | Consensus: APPROVED (Raft 3/3)_

---

## Sommario

| Categoria | HIGH | MEDIUM | LOW | INFO |
|-----------|------|--------|-----|------|
| Bug / Correttezza | 2 | 2 | 1 | - |
| Sicurezza | 1 | 1 | 1 | - |
| Performance | - | 2 | 2 | - |
| Architettura | - | 2 | 1 | 2 |
| Test | - | 1 | 1 | - |
| Documentazione | - | 1 | - | - |
| **Totale** | **3** | **9** | **6** | **2** |

**Test suite: 38/38 PASS (4.7s) su Python 3.14**

File analizzati: `engine.py`, `schema.py`, `policy.py`, `config.py`, `server.py`, `hooks.py`, `__main__.py`, `adapters/ruflo.py`, `adapters/local_cache.py`, `adapters/supermemory.py`, `pyproject.toml`, `Dockerfile`, `config.example.json`, + 3 file di test.

---

## HIGH

### BUG-01: Metrics status tracking errato in `do_POST`

**File:** `broker/server.py:219`

```python
status = 200 if self.path in ("/capture", "/retrieve", "/explain", "/upsert") else 404
_metrics.record(self.path, status)
```

**Problema:** Dopo che i singoli handler (`_handle_capture`, ecc.) inviano la propria risposta, la riga 219 assume sempre `status=200` per i path noti. Se l'handler ha un errore interno (es. `ValueError` da enum invalido), le metriche registrano comunque 200.

**Impatto:** `/metrics` mostra conteggi inaffidabili. Non si vedono errori interni dai contatori.

**Fix suggerito:** Far restituire lo status code dai metodi handler e usare quello per le metriche, oppure spostare `_metrics.record()` dentro ogni handler individualmente.

---

### BUG-02: Il parametro `query` non viene mai passato ai backend

**File:** `broker/engine.py:122-147`, `broker/adapters/supermemory.py:186`

```python
# engine.py — retrieve_context()
def retrieve_context(self, query: str, scope_filters=None):
    # ...
    records = backend.retrieve(scope=scope, ...)  # 'query' non viene mai passato!
```

```python
# supermemory.py — retrieve()
body = {"q": f"scope:{scope_val}", ...}  # query hardcoded, non usa il parametro utente
```

**Problema:** `retrieve_context()` accetta un parametro `query` ma non lo passa a nessun backend. Il retrieve Supermemory cerca sempre `scope:{scope_val}` invece della query dell'utente. Il retrieve locale e Ruflo filtrano solo per scope. La ricerca e' di fatto un "list by scope", non una vera query.

**Impatto:** L'endpoint `/retrieve` accetta un campo `query` nel body ma lo ignora completamente. L'utente pensa di cercare per contenuto ma riceve solo un dump filtrato per scope.

**Fix suggerito:** Propagare `query` nella signature di `backend.retrieve()` e usarla:
- Supermemory: passarla nel campo `q` della search API
- Ruflo: aggiungere un `WHERE content LIKE` o FTS
- Local cache: filtrare con substring match

---

### SEC-01: Nessun limite sulla dimensione del body HTTP

**File:** `broker/server.py:111-116`

```python
def _read_json_body(handler):
    length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(length)  # legge tutto in memoria
```

**Problema:** `Content-Length` e' fidato ciecamente. Un client malevolo puo' inviare un payload JSON arbitrariamente grande, consumando tutta la RAM del server.

**Impatto:** Denial of Service facile da sfruttare. Critico se il server e' esposto su VPS.

**Fix suggerito:** Aggiungere un `MAX_BODY_SIZE` (es. 1MB) e rifiutare con 413 se `Content-Length` lo supera:
```python
MAX_BODY_SIZE = 1_048_576  # 1 MB
if length > MAX_BODY_SIZE:
    _json_response(handler, 413, {"error": "payload too large"})
    return {}
```

---

## MEDIUM

### BUG-03: `body.pop()` muta il dizionario input in `_handle_capture`

**File:** `broker/server.py:247-248`

```python
client = body.pop("client", "")
dry_run = body.pop("dry_run", False)
```

**Problema:** `.pop()` rimuove chiavi dal dict prima di passarlo a `normalize()`. Il dict originale viene modificato. Non causa bug oggi ma e' una fonte di problemi futuri se il dict viene riusato.

**Fix suggerito:** Usare `.get()` e passare esplicitamente:
```python
client = body.get("client", "")
dry_run = body.get("dry_run", False)
```

---

### BUG-04: Scope/memory_type invalidi restituiscono 500 invece di 400

**File:** `broker/server.py` + `broker/schema.py:144`

**Problema:** Se il body contiene `"scope": "invalid"`, `MemoryScope("invalid")` solleva `ValueError`. Il server non ha un try/except per questo, quindi restituisce un 500 non gestito invece di un 400 con messaggio descrittivo.

**Impatto:** UX del client scadente; il 500 non spiega cosa c'e' di sbagliato. In produzione un 500 puo' attivare allarmi inutili.

**Fix suggerito:** Wrappare la logica degli handler in un try/except per `ValueError`/`KeyError`:
```python
try:
    body = _read_json_body(self)
    # ...handler logic...
except (ValueError, KeyError) as exc:
    _json_response(self, 400, {"error": "invalid input", "detail": str(exc)})
```

---

### SEC-02: `/upsert` non valida confidence/importance

**File:** `broker/server.py:296-315`

**Problema:** `_handle_upsert` costruisce un `MemoryRecord` direttamente dal body senza chiamare `clamp_unit()`. Un client puo' inviare `"confidence": 999` e il valore viene persistito senza clamping. In contrasto, `/capture` passa per `normalize_client_event()` che chiama `clamp_unit()`.

**Fix suggerito:** Aggiungere clamping in `_handle_upsert`:
```python
confidence=clamp_unit(body.get("confidence", 0.5), "confidence"),
importance=clamp_unit(body.get("importance", 0.5), "importance"),
```

---

### PERF-01: PRAGMA eseguiti ad ogni connessione SQLite

**File:** `broker/adapters/ruflo.py:84-88`

```python
def _connect(self):
    conn = sqlite3.connect(str(self.db_path))
    conn.execute("PRAGMA journal_mode = WAL")     # persiste gia' dopo il primo SET
    conn.execute("PRAGMA foreign_keys = ON")       # serve ma e' leggero
```

**Problema:** `PRAGMA journal_mode = WAL` persiste una volta impostato e non serve ripeterlo. Ogni `upsert()` e `retrieve()` apre una nuova connessione ed esegue questi PRAGMA. Overhead inutile.

**Fix suggerito:** Impostare WAL una volta in `_ensure_db()` e rimuoverlo da `_connect()`. Oppure usare un connection pool / connessione persistente.

---

### PERF-02: Filtraggio post-fetch e UPDATE per-riga in `retrieve()`

**File:** `broker/adapters/ruflo.py:170-238`

```python
# Filtraggio user/workspace in Python DOPO il fetch
if user_id and record_dict.get("user_id") and record_dict["user_id"] != user_id:
    continue

# UPDATE access_count per ogni riga nel loop
conn.execute("UPDATE memory_entries SET ... WHERE id = :id", ...)
```

**Problema:**
1. Il filtraggio per user/workspace avviene in Python dopo aver scaricato tutte le righe dal DB. Su dataset grandi, questo spreca banda I/O.
2. `access_count` viene aggiornato riga per riga dentro un loop Python, generando N query UPDATE separate.

**Fix suggerito:**
1. Aggiungere `AND tags LIKE '%user:{user_id}%'` nella query SQL (o meglio, indicizzare `owner_id`)
2. Raccogliere gli ID e fare un singolo `UPDATE ... WHERE id IN (...)`

---

### ARCH-01: Singleton mutabili a livello di modulo

**File:** `broker/server.py:39-43, 69, 98`

```python
_API_KEY = os.environ.get("BROKER_API_KEY", "")     # letto all'import
_rate_limiter = _RateLimiter(_RATE_LIMIT, _RATE_WINDOW)  # istanza globale
_metrics = _Metrics()                                     # istanza globale
```

**Problema:** Questi valori vengono letti una volta all'import e condivisi tra tutte le istanze del server (incluse quelle nei test). I test devono fare monkey-patching diretto (`srv._API_KEY = "..."`) che e' fragile e causa problemi di isolamento tra classi di test.

**Fix suggerito:** Spostare queste configurazioni dentro `BrokerHandler` o `serve()`, oppure passarle come parametri. Per i test, usare un factory che crea handler con la propria configurazione.

---

### ARCH-02: `BrokerEvent` sintetico in `upsert_memory()`

**File:** `broker/engine.py:106-109`

```python
event = BrokerEvent(
    scope=record.scope,
    importance=record.importance,
)
```

**Problema:** Per valutare la write policy, viene creato un `BrokerEvent` con solo scope e importance. Tutti gli altri campi hanno i default. Se in futuro la policy controlla altri campi (es. `confidence`, `memory_type`), il routing sara' sbagliato.

**Fix suggerito:** Costruire l'event con tutti i campi disponibili dal record:
```python
event = BrokerEvent(
    scope=record.scope,
    importance=record.importance,
    confidence=record.confidence,
    memory_type=record.memory_type,
)
```

---

### TEST-01: Isolamento test fragile per singletons

**File:** `tests/test_server_http.py:182-193, 274-276`

**Problema:** `TestServerAuth` patcha `srv._API_KEY` e `TestRateLimiting` patcha `srv._rate_limiter` a livello di classe. Poiche' i test condividono lo stesso modulo importato, l'ordine di esecuzione puo' influenzare i risultati. I `ResourceWarning` per socket non chiusi confermano problemi di cleanup.

**Fix suggerito:** Usare `unittest.mock.patch` come context manager o decorator per garantire il ripristino anche in caso di errore. Aggiungere cleanup esplicito dei socket nei `tearDownClass`.

---

### DOC-01: README.md riporta 32 test, sono 38

**File:** `README.md:152`

```
32 tests covering:
```

**Stato reale:** 38 test (17 unit + 15 HTTP + 6 hooks), tutti passanti.

**Fix:** Aggiornare il numero a 38.

---

## LOW

### BUG-05: Flag `--success` sempre True in hooks CLI

**File:** `broker/hooks.py:149`

```python
pt.add_argument("--success", action="store_true", default=True)
```

**Problema:** `store_true` con `default=True` rende il flag inutile: `args.success` e' sempre `True`. Solo `--failed` (tramite `not args.failed`) permette di segnalare un fallimento. UX confusa.

**Fix suggerito:** Rimuovere `--success` oppure usare `default=False`:
```python
pt.add_argument("--success", action="store_true", default=False)
pt.add_argument("--failed", action="store_true", default=False)
# poi: success = args.success or not args.failed
```

---

### SEC-03: CORS wildcard `*` su tutte le risposte

**File:** `broker/server.py:105`

```python
handler.send_header("Access-Control-Allow-Origin", "*")
```

**Problema:** Tutte le risposte hanno `Access-Control-Allow-Origin: *`. Accettabile per uso locale, ma per il deploy VPS andrebbe ristretto o reso configurabile.

**Fix suggerito:** Rendere configurabile via env var `BROKER_CORS_ORIGIN` (default `*` per locale, restrittivo per VPS).

---

### PERF-03: Riscrittura completa del file JSON ad ogni upsert

**File:** `broker/adapters/local_cache.py:43-55`

**Problema:** Ogni `upsert()` legge l'intero file JSON, cerca linearmente l'ID, e riscrive l'intero file. O(n) per operazione. Accettabile per un cache locale con pochi record, ma non scala.

**Nota:** Per il ruolo attuale (cache locale non autoritativa) e' ok. Segnalato per awareness.

---

### PERF-04: Memory leak nel rate limiter

**File:** `broker/server.py:46-66`

**Problema:** `_RateLimiter._hits` accumula chiavi per ogni IP client visto. I timestamp vecchi vengono filtrati, ma le chiavi IP non vengono mai rimosse. Leak lento nel tempo.

**Fix suggerito:** Aggiungere cleanup periodico delle chiavi con liste vuote dopo il filtraggio:
```python
hits = [t for t in hits if t > cutoff]
if not hits:
    self._hits.pop(client_ip, None)
    return True
```

---

### ARCH-03: Import lazy di `logging` dentro `clamp_unit()`

**File:** `broker/schema.py:121`

```python
def clamp_unit(value, field_name):
    # ...
    if clamped != value:
        import logging  # import ad ogni warning
        logging.getLogger(__name__).warning(...)
```

**Fix:** Spostare `import logging` a livello di modulo (c'e' gia' `from __future__ import annotations` ma manca `import logging`).

---

### TEST-02: ResourceWarning per socket non chiusi

**File:** output dei test

```
ResourceWarning: unclosed <socket.socket fd=428, ...>
ResourceWarning: Implicitly cleaning up <HTTPError 429: 'Too Many Requests'>
```

**Problema:** I server HTTP di test non chiudono completamente i socket. Le risposte di errore HTTP non vengono chiuse con `with` statement.

**Fix suggerito:** Aggiungere `server.server_close()` dopo `server.shutdown()` nei `tearDownClass`. Nei test che aspettano errori HTTP, usare context manager.

---

## INFO

### ARCH-04: Mapping implicito chiavi JSON → attributi Python

**File:** `broker/config.py:126`

Il loop che mappa i backend config mixa chiavi JSON (`localCache`) con attributi Python (`local_cache`). Se un backend manca dal JSON, il default e' `BackendConfig(enabled=True)`, che potrebbe sorprendere.

---

### ARCH-05: Interfaccia adapter implicita (duck typing)

**File:** tutti gli adapter in `broker/adapters/`

Nessuna classe base astratta o `Protocol` definisce il contratto degli adapter. Tutti devono implementare `upsert(record) -> dict` e `retrieve(scope, user_id, workspace_id, limit) -> list[dict]`, ma questo e' imposto solo per convenzione.

**Nota:** Per un progetto con 3 adapter e' accettabile. Se il numero cresce, considera un `typing.Protocol`:
```python
class BackendProtocol(Protocol):
    name: str
    def upsert(self, record: MemoryRecord) -> dict[str, Any]: ...
    def retrieve(self, scope, user_id, workspace_id, limit) -> list[dict[str, Any]]: ...
```

---

## Riepilogo priorita' fix

### Pre-VPS deployment (bloccanti)
1. **SEC-01** — Limite dimensione body HTTP
2. **BUG-04** — Gestione ValueError per enum invalidi (400 invece di 500)
3. **SEC-02** — Clamping su `/upsert`
4. **SEC-03** — CORS configurabile

### Prossimo sprint (miglioramenti significativi)
5. **BUG-02** — Propagare query ai backend (feature gap critica)
6. **BUG-01** — Fix metrics status tracking
7. **ARCH-01** — Rimuovere singleton mutabili dal modulo
8. **PERF-02** — Filtraggio SQL in ruflo adapter

### Nice-to-have
9. **PERF-01** — PRAGMA una volta sola
10. **PERF-04** — Cleanup rate limiter
11. **DOC-01** — Aggiornare README test count
12. Tutto il resto LOW/INFO

---

## Note positive

- **Architettura solida:** La separazione schema/policy/engine/adapters e' pulita e segue il principio di singola responsabilita'.
- **Zero dipendenze esterne:** Solo stdlib Python. Notevole per un progetto con HTTP server, SQLite, e REST client.
- **Graceful degradation:** Il backend Supermemory funziona come no-op senza API key. Design eccellente per progressive enhancement.
- **Test copertura buona:** 38 test coprono normalizzazione, policy, round-trip su tutti i backend, HTTP, auth, rate limiting, hooks. Rari per un MVP.
- **Config flessibile:** Catena .env → JSON → env var override e' ben implementata.
- **Dry-run mode:** Permette di testare il flow senza side effects. Molto utile.
- **CLI completa:** `arbiter serve|dry-run|capture|retrieve|status` copre tutti gli use case base.

---

_Review generata dal hive-mind `hive-1775804308630-m4eq2j` — 5 specialist (security, architecture, bugs, performance, testing) con consenso Raft._
