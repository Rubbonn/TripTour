# Documento di Specifiche Tecniche (V8): TripTour

Questo documento descrive le specifiche di sviluppo di **TripTour**, un'applicazione desktop che trasforma raccolte non strutturate di foto in tour virtuali narrati. L'applicazione utilizza un'interfaccia utente sviluppata in **Svelte (SPA)** ospitata all'interno di un contenitore **PySide6 (Qt)**, comunicando tramite un bridge IPC bidirezionale (`QWebChannel`).

TripTour utilizza un'**architettura AI ibrida**:
- I **Transformer locali** sono usati solo per gli embedding delle immagini (supporto a deduplicazione e clustering).
- **LangChain/LangGraph + API compatibili OpenAI** sono usati per l'arricchimento multimodale e la sintesi narrativa finale.
- L'utente configura URL endpoint, chiave API e scelta dei modelli (modello vision + modello testuale) al primo avvio e successivamente nelle Impostazioni.

---

## 1. Architettura del Sistema & Bridge IPC

L'applicazione combina le prestazioni di un backend Python nativo con l'interattività di un frontend Svelte moderno.

```
┌─────────────────────────────────────────────────────────────┐
│                 TRIPTOUR UI (Svelte SPA)                    │
├─────────────────────────────────────────────────────────────┤
│ QWebChannel (JS Client)                                     │
└──────────────────────────────▲──────────────────────────────┘
                               │ IPC Bridge (QWebChannel)
┌──────────────────────────────▼──────────────────────────────┐
│ PySide6 WebEngineView & QWebChannel (Python Server)          │
├─────────────────────────────────────────────────────────────┤
│                     PYTHON BACKEND CONTROLLER               │
└─────────────────────────────────────────────────────────────┘
```

* **PySide6 `QWebEngineView`**: renderizza la SPA Svelte compilata in un bundle locale leggero.
* **`QWebChannel`**: espone un oggetto controller Python al contesto JavaScript globale della pagina web. Il frontend Svelte può invocare metodi Python in modo asincrono (es. `pybridge.select_folder().then(...)`).

---

## 2. Flusso Utente & Pipeline di Elaborazione Dettagliata

```
[ Avvio App ]
    │
    ├──► [ Configurazione AI richiesta? ] -- sì --> [ Configurazione AI al primo avvio ]
    │                                          (URL Base + Chiave API + Selezione Modello)
    │
    └──► no / completata
            │
            └──► [ Homepage ] ──► [ Carica Tour Precedente ]
                      │
                      └──► [ Nuovo Tour ]
                              │
                              ├──► Seleziona file/cartelle, Lingua e Nome Tour (PySide6 Dialog & Svelte)
                              │
                              ├──► FASE 0: Ordinamento Multi-Livello (EXIF → Regex → mtime → Ordine di Importazione)
                              │
                              ├──► FASE 1: Filtraggio e De-duplicazione (CLIP + Laplacian)
                              │
                              ├──► FASE 2: Arricchimento Basato su Anchor (Punti Anchor + Propagazione Contesto + Modello Vision Remoto)
                              │
                              ├──► FASE 3: Clustering Ibrido (Spazio-Tempo / Tempo+Visivo / Rilevamento Cambiamenti Semantici)
                              │
                              ├──► FASE 4: Editor Storyboard (UI Svelte - Modifiche Manuali)
                              │
                              ├──► FASE 5: Generazione Script (Modello Testuale Remoto + Nome Tour + Tag Inline)
                              │
                              └──► [ Player HTML & Esportazione Pacchetto ]
```

### Fase 0: Avvio, Inizializzazione e Ordinamento Multi-Livello (Sanitizzazione)
1.  **Gate di Configurazione Pre-Homepage**: all'avvio, prima che sia mostrata la homepage e prima che l'utente possa caricare/avviare qualsiasi tour, TripTour verifica se esiste una configurazione AI.
2.  **Wizard Obbligatorio di Configurazione AI al Primo Avvio**: al primo avvio (o ogni volta che la configurazione è assente), TripTour apre un flusso di setup obbligatorio in cui l'utente fornisce:
    * **URL Base** di un endpoint compatibile OpenAI (esempi: OpenAI, OpenRouter, vLLM locale, gateway compatibile Ollama).
    * **Chiave API** (o token equivalente) per l'endpoint selezionato.
    * **Modello di Arricchimento** (deve supportare input immagine / vision).
    * **Modello Narrativo** (modello testuale per la generazione finale del tour).
    
    La configurazione viene validata con una chiamata di test leggera e poi persistita localmente tramite **PySide6 QSettings**. Le stesse impostazioni possono essere modificate successivamente da una sezione dedicata **Impostazioni > Provider AI**.
3.  **Homepage**: dopo che la configurazione è valida, l'utente può riprendere un tour precedentemente salvato dal database SQLite locale o avviarne uno nuovo.
4.  **Inizializzazione & Selezione**:
    * L'utente seleziona file o una cartella tramite dialog nativi PySide6 (`QFileDialog`). Le foto importate possono essere in un ordine completamente non strutturato.
    * L'utente seleziona la lingua del tour.
    * **Nome Tour (Novità)**: l'utente inserisce un titolo descrittivo per il tour (es. *"Visita ai Musei Vaticani"* oppure *"Vacanze in Toscana 2026"*). Questo nome viene salvato nel database e **diventa un metadato cruciale** passato ai modelli AI nelle fasi successive per guidarne la comprensione dei contesti storici, geografici e artistici.
5.  **Strategia di Ordinamento Multi-Livello**: prima che venga eseguita qualunque analisi, il backend applica una pipeline di sanitizzazione a cascata per stabilire il miglior ordine cronologico possibile. A ogni foto viene assegnato un timestamp usando la prima fonte disponibile nella seguente catena di priorità:

    | Priorità | Fonte | Descrizione |
    |----------|--------|-------------|
    | **1 (Più Alta)** | `EXIF DateTimeOriginal` | Estratto dai metadati EXIF interni dell'immagine — il vero timestamp di scatto. |
    | **2** | **Parsing Regex sul Filename** | Una regex scandisce il filename alla ricerca di timestamp incorporati (es. `IMG_20260725_143052.jpg`, `2026-07-25 14.30.45.png`, `VID-20260725-WA0001.jpeg`). I pattern comuni includono `YYYYMMDD_HHMMSS`, `YYYY-MM-DD HH.MM.SS` e prefissi stile WhatsApp `YYYYMMDD`. |
    | **3** | **Tempo di Modifica del Filesystem (`mtime`/`ctime`)** | Se non è possibile estrarre un timestamp da EXIF o filename, il backend usa come fallback il tempo di ultima modifica del file (o tempo di creazione sui filesystem supportati). |
    | **4 (Più Bassa)** | **Ordine Nativo di Importazione** | Se tutti i metodi precedenti falliscono (es. file con nomi generici e metadati corrotti), viene preservato come ultima risorsa l'ordine originale con cui i file sono stati selezionati/importati. |

    *Ogni foto registra nel database un campo `sort_source` che indica quale livello di priorità è stato usato, abilitando trasparenza e potenziale correzione manuale nello Storyboard Editor.*

### Fase 1: Filtraggio & Rimozione Duplicati (Deduplicazione)
Usando la sequenza appena ordinata, per prevenire ridondanza visiva (come più scatti dello stesso soggetto):
1.  Il backend carica un modello locale leggero di embedding immagini (es. `laion/CLIP-ViT-B-32-laion2B-s34B-b79K` tramite Transformers).
2.  Genera vettori (embedding) per ogni foto. **Questi embedding vengono persistiti** (memorizzati nella colonna `embedding` della tabella `media`) per il riuso nella Fase 2.3 (tie-breaking di affinità visiva CLIP) e nella Fase 3 (clustering Tempo+Visivo e Rilevamento Cambiamenti Semantici), evitando ricaricamenti ridondanti del modello.
3.  Calcola la similarità coseno tra foto adiacenti cronologicamente.
4.  **Risoluzione Duplicati**: se due o più foto adiacenti superano una soglia di similarità predefinita (es. > 0.85):
    * Viene calcolata la **varianza del Laplaciano** per ogni foto, per misurarne la nitidezza (sfocatura).
    * Viene mantenuta la foto più nitida (varianza più alta); le altre vengono rimosse dalla sequenza attiva del tour o nascoste.

### Fase 2: Arricchimento Basato su Anchor (Punti Anchor + Propagazione Contesto + Modello Vision)
La fase di arricchimento segue una strategia **Anchor-Based**: le foto con metadati completi (GPS + timestamp) fungono da **Anchor Points**, e le loro informazioni contestuali vengono propagate avanti e indietro verso le foto vicine prive di metadati. Questo garantisce la massima copertura anche quando GPS o timestamp sono parziali o assenti.

#### Step 2.1: Classificazione e Identificazione Anchor
Ogni foto nella sequenza ordinata viene classificata in base alla completezza dei suoi metadati:

| Classe | GPS | Timestamp | Ruolo |
|-------|-----|-----------|------|
| **Anchor (A)** | ✓ Presente | ✓ Presente | Punto di riferimento per geolocalizzazione e contesto temporale |
| **Solo-Tempo (T)** | ✗ Assente | ✓ Presente | Posizionata cronologicamente; posizione ereditata dagli anchor più vicini |
| **Nuda (B)** | ✗ Assente | ✗ Assente | Nessun metadato; si affida completamente all'affinità visiva con gli anchor più vicini |

#### Step 2.2: Estrazione EXIF & Reverse Geocoding (Solo Anchor)
Per le **foto Anchor soltanto**, il backend esegue un'estrazione completa dei metadati:
1.  **Metadati EXIF**: estrazione coordinate GPS (`GPSLatitude`, `GPSLongitude`, `GPSLatitudeRef`, `GPSLongitudeRef`).
2.  **Reverse Geocoding (Nominatim)**: le coordinate vengono convertite in dati di posizione leggibili (città, regione, paese) usando OpenStreetMap Nominatim (`https://nominatim.openstreetmap.org/reverse`). In questa versione non è definito alcun provider di fallback.

#### Step 2.3: Propagazione del Contesto (Avanti & Indietro)
Una volta che gli Anchor sono identificati e arricchiti, il contesto viene propagato alle foto non-anchor:

1.  **Passata in Avanti**: per ogni foto senza GPS, il backend percorre in avanti la sequenza ordinata per trovare l'Anchor più vicino e ne eredita la posizione geocodificata. Questo modella l'assunzione realistica che una foto scattata poco dopo una posizione nota sia probabilmente ancora in quella posizione.
2.  **Passata all'Indietro**: in modo analogo, il backend percorre all'indietro per propagare il contesto di posizione dagli Anchor successivi alle foto precedenti che li precedono.
3.  **Tie-Breaking per Affinità Visiva**: quando una foto Nuda (Classe B, senza alcun metadato) si trova tra due Anchor con posizioni *diverse*, il sistema calcola la **similarità coseno CLIP** tra la foto Nuda e ciascun Anchor candidato. La foto Nuda eredita la posizione dell'Anchor con similarità visiva più alta.

#### Step 2.4: Generazione di Descrizioni Contestuali (LangChain/LangGraph + Modello Vision)
Per ogni foto (indipendentemente dalla classe), il backend genera un tag descrittivo usando il **modello multimodale remoto configurato** con la **finestra contestuale tripla scorrevole**, ora arricchita dal contesto propagato dagli Anchor.

* Per analizzare l'immagine corrente N, il backend Python costruisce una chiamata LangChain/LangGraph all'endpoint chat-completions compatibile OpenAI configurato, passando:
    * l'**Immagine Corrente N**.
    * l'**Immagine Precedente N-1** insieme alla sua **descrizione già generata** (se N > 1).
    * l'**Immagine Successiva N+1** come puro contesto visivo (se N < numero totale di foto).
    * il **Nome Tour** fornito dall'utente.
    * la **Posizione Ereditata** (dalla propagazione Anchor o geocodifica GPS diretta).
* Il modello di arricchimento selezionato **deve supportare immagini**. Il wizard di setup e la validazione nelle Impostazioni rifiutano modelli non vision per questo ruolo.
* Il prompt istruisce il modello a riconoscere la continuità logica, usare il contesto di posizione e sfruttare il titolo del tour:
  > *"L'utente è attualmente in un tour intitolato: **[Nome Tour]**. La posizione stimata è: **[Posizione]**. Ti sto mostrando l'immagine corrente (Foto B), inserita in questa sequenza cronologica. Ti fornisco anche la foto precedente (Foto A), descritta come '[Descrizione A]', e la foto successiva (Foto C). Descrivi cosa raffigura la Foto B, tenendo conto del contesto del tour '[Nome Tour]', della posizione '[Posizione]' e delle foto adiacenti. Se la Foto B mostra un dettaglio ravvicinato di un soggetto visibile nella Foto A o che porta alla Foto C, dichiaralo esplicitamente nella descrizione (es., 'Questo è un dettaglio ravvicinato della colonna sinistra del portico della chiesa che abbiamo appena visto...')."*
* **Policy di Utilizzo Tool (LangGraph)**: i tool non vengono attivati singolarmente nelle impostazioni. Sono automaticamente disponibili quando le condizioni di esecuzione sono soddisfatte. Esempio: il recupero di articoli/contesto da Wikipedia viene invocato solo quando è disponibile la connettività internet, così il modello riceve un contesto fattuale più ampio per interpretare ciò che sta vedendo.

### Fase 3: Clustering Ibrido & Generazione Storyboard
Il backend organizza la sequenza ordinata di foto in **Sezioni/Scene** logiche usando una strategia di **Clustering Ibrido**. Poiché le raccolte di foto reali hanno livelli diversi di completezza dei metadati, il sistema applica l'algoritmo di clustering più appropriato per foto, con fallback graduale quando GPS o timestamp non sono disponibili.

#### Gerarchia delle Strategie di Clustering

Il backend prova ogni strategia in ordine di priorità per ciascuna coppia di foto adiacenti. Viene usata la prima strategia con dati sufficienti per entrambe le foto:

| Priorità | Strategia | Requisiti | Metodo |
|----------|----------|-------------|--------|
| **1** | **Clustering Spazio-Tempo** | Entrambe le foto hanno GPS + Timestamp | raggio ~100m, finestra scorrevole ~15 min |
| **2** | **Clustering Tempo + Visivo** | Entrambe le foto hanno Timestamp (senza GPS) | finestra temporale + similarità coseno CLIP |
| **3** | **Rilevamento Cambiamenti Semantici** | Nessun GPS, nessun Timestamp (foto Nude) | cali di similarità coseno CLIP tra foto adiacenti |

#### Strategia 1: Clustering Spazio-Tempo (GPS + Timestamp)
Il metodo di clustering ideale. Due foto adiacenti vengono raggruppate nella stessa sezione se:
- I loro orari di scatto sono entro **15 minuti** uno dall'altro.
- Le loro coordinate GPS sono entro **~100 metri** una dall'altra (usando la formula di Haversine).

Una nuova sezione viene creata quando il gap temporale supera la soglia o la distanza spaziale indica un cambio significativo di posizione.

#### Strategia 2: Clustering Tempo + Visivo (Solo Timestamp, Senza GPS)
Quando le foto hanno timestamp ma non coordinate GPS, il sistema combina prossimità temporale e similarità visiva CLIP:
- Due foto adiacenti vengono raggruppate se il loro delta temporale è entro **30 minuti**.
- Se il delta temporale è borderline (tra 15–120 minuti), un controllo di **similarità coseno CLIP** agisce da tie-breaker: foto con alta similarità visiva (> 0.7) restano insieme anche con un gap temporale più lungo (es. scatti interni dello stesso museo distribuiti nel tempo), mentre foto visivamente dissimili attivano una separazione di sezione.

#### Strategia 3: Rilevamento Cambiamenti Semantici (Nessun GPS, Nessun Timestamp — Foto Nude)
Quando le foto non hanno né GPS né timestamp affidabili, il clustering si basa puramente sulla semantica visiva. Il sistema calcola embedding CLIP per tutte le coppie di foto adiacenti e rileva **Punti di Cambiamento Semantico** — posizioni in cui la similarità coseno cala bruscamente, indicando una probabile transizione di scena/capitolo.

L'algoritmo:
1. Calcola la similarità coseno CLIP per ogni coppia adiacente $(i, i+1)$.
2. Identifica **minimi locali** nella curva di similarità dove $\text{sim}(i, i+1) < \mu - k \cdot \sigma$ (cioè la similarità scende significativamente sotto la media mobile).
3. Posiziona i confini di sezione in questi punti di cambiamento rilevati.

#### Entry Point Unificato di Clustering Ibrido
La funzione di clustering top-level attraversa la sequenza ordinata di foto e seleziona automaticamente la strategia migliore in base ai metadati disponibili:
- Se più del 50% delle foto ha coordinate GPS → **Clustering Spazio-Tempo** (Strategia 1).
- Se più del 50% ha timestamp (ma non GPS) → **Clustering Tempo + Visivo** (Strategia 2).
- Altrimenti → **Rilevamento Cambiamenti Semantici** (Strategia 3).

> **Filosofia Plug & Play**: questo approccio ibrido incarna il principio di design centrale di TripTour — l'utente carica semplicemente le sue foto, e il sistema svolge automaticamente il miglior lavoro possibile. Lo Storyboard Editor (Fase 4) diventa quindi un'esperienza di rifinitura piacevole invece che un passaggio obbligato di correzione.

#### Generazione Metadati di Sezione
Dopo il clustering, ogni sezione viene automaticamente arricchita:
1.  Viene sintetizzato un **titolo di sezione** dai tag più frequenti e dalla posizione dominante (es. "Ingresso Monumentale — Piazza del Duomo").
2.  Viene generata una **auto-descrizione preliminare** fondendo le descrizioni contestualizzate delle foto costituenti la sezione.
3.  Le foto senza coordinate ereditate vengono segnalate nella UI (evidenziazione rossa) per la correzione manuale nella Fase 4.

### Fase 4: Storyboard Editor (Interfaccia Utente)
Il frontend Svelte riceve dal backend la struttura dello storyboard e mostra una UI interattiva:
* Le foto sono raggruppate visivamente nelle sezioni/fasi calcolate.
* **Trasparenza Anchor & Metadati**: ogni foto mostra un piccolo badge che indica la sua classificazione (🟢 Anchor / 🟡 Solo-Tempo / 🔴 Nuda) e la fonte di ordinamento usata nella Fase 0 (EXIF, regex filename, filesystem o ordine di importazione). Questo consente agli utenti di capire subito quali foto hanno metadati affidabili e quali sono state posizionate euristicamente.
* **Gestione Errori GPS / Posizione**: le foto senza coordinate (classi Nuda e Solo-Tempo con posizione ereditata non risolta) sono evidenziate in rosso. L'utente può digitare manualmente una posizione per la fase o trascinare foto in una fase esistente.
* **Interattività Completa**: gli utenti possono trascinare foto per riordinarle tra sezioni, creare nuove sezioni vuote, rinominarle, eliminare scatti indesiderati o modificare manualmente descrizioni e posizioni ereditate.
* **Modifica in Blocco**: possibilità di selezionare più foto contemporaneamente per assegnare loro la stessa posizione o gli stessi tag con un solo clic.
* **Ricalcola**: un pulsante consente di rieseguire la Fase 3 (Clustering Ibrido) se gli utenti vogliono reimpostare il raggruppamento automatico dopo aver effettuato modifiche manuali a ordine o metadati.

### Fase 5: Sintesi Narrativa e Tagging Temporale (LangChain/LangGraph)
Una volta che l'utente conferma lo storyboard modificato:
1.  Il backend Python costruisce una pipeline di generazione con LangChain/LangGraph usando il **modello narrativo** configurato (focalizzato sul testo).
2.  Tutte le informazioni dello storyboard (posizioni, descrizioni dettagliate e contestualizzate, ordine cronologico), insieme a **Nome Tour** e **Lingua di Destinazione**, vengono aggregate e inviate all'endpoint selezionato dall'utente.
3.  Il modello elabora questo testo strutturale e il nome del tour (es. *"Vacanza a Roma 2026"*) e genera lo script narrativo finale direttamente nella lingua di destinazione.
4.  **Sincronizzazione**: il modello incorpora nel testo tag inline speciali per indicare esattamente quando l'interfaccia deve passare alla foto successiva.

* *Esempio di output LLM:*
    > `[photo_001.jpg] Benvenuti a Palazzo Vecchio, uno dei simboli iconici di Firenze. [photo_002.jpg] Avvicinandoci al portale principale, risalta la maestosa copia del David di Michelangelo. [photo_003.jpg] Se osserviamo da vicino i dettagli in pietra scolpita sulla sinistra...`

---

## 3. Architettura di Orchestrazione AI

TripTour separa l'indicizzazione visiva locale dall'orchestrazione dei modelli:

### 3.1 Layer Locale di Embedding (Transformers)
Solo i carichi di lavoro di embedding passano attraverso modelli `transformers` locali di Hugging Face:
1.  **Fase 1 (Deduplicazione)**: embedding CLIP + punteggio qualità Laplaciano.
2.  **Fase 2.3 (Tie-Breaking)**: riuso degli embedding CLIP persistiti per la disambiguazione anchor.
3.  **Fase 3 (Clustering)**: riuso degli embedding CLIP persistiti per Tempo+Visivo e Rilevamento Cambiamenti Semantici.

### 3.2 Layer di Inferenza Remota (LangChain/LangGraph)
Tutte le attività generative/orchestrazione modello vengono eseguite tramite un'astrazione client compatibile OpenAI:
1.  **Modello Multimodale di Arricchimento**: usato in Fase 2, deve accettare input immagine.
2.  **Modello di Generazione Narrativa**: usato in Fase 5, ottimizzato per output testuali long-form.
3.  **Agnosticismo Endpoint**: può essere configurato qualsiasi endpoint compatibile (OpenAI, OpenRouter, gateway vLLM self-hosted, bridge compatibili Ollama, ecc.).

### 3.3 Lifecycle Primo Avvio e Impostazioni
1.  Se manca la configurazione AI, l'avvio viene reindirizzato a una schermata di setup obbligatoria.
2.  L'app salva URL endpoint, credenziali API cifrate/offuscate e identificatori modello tramite **PySide6 QSettings**.
3.  Un pannello impostazioni dedicato consente di aggiornare in qualsiasi momento le mappature provider/modello.
4.  Le regole di validazione impongono che il modello di arricchimento sia vision-capable.

---

## 4. Gestione Database SQLite & Percorso Persistente

Per garantire persistenza e portabilità dei dati (prevenendo perdita dati se il binario dell'applicazione viene aggiornato o spostato), il file database `triptour.db` **non viene salvato accanto all'eseguibile**. Invece, viene scritto in una cartella dati applicazione dedicata all'utente, gestita in modo cross-platform.

### Risoluzione Dinamica del Percorso in Python
Il backend Python calcola il percorso appropriato all'avvio dell'applicazione. Vengono usati percorsi standard per ogni sistema operativo:
* **Windows**: `%APPDATA%/TripTour/triptour.db`
* **macOS**: `~/Library/Application Support/TripTour/triptour.db`
* **Linux**: `~/.local/share/triptour/triptour.db`

### Schema del Database Locale

```sql
-- Tabella Tour Virtuali
CREATE TABLE tours (
    id INTEGER PRIMARY KEY,       -- Id intero auto-incrementale
    title TEXT NOT NULL,          -- Titolo del tour
    language TEXT NOT NULL,       -- Lingua selezionata per il tour (es. "it", "en")
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tabella Media/Foto
CREATE TABLE images (
    id INTEGER PRIMARY KEY,       -- Id intero auto-incrementale
    id_tour INTEGER NOT NULL,     -- Chiave esterna collegata al tour
    path TEXT NOT NULL,           -- Percorso immagine su disco
    filename TEXT NOT NULL,       -- Nome file
    latitude REAL,                -- Nullable
    longitude REAL,               -- Nullable
    address TEXT,                 -- Nullable
    date TIMESTAMP,               -- Nullable
    description TEXT,             -- Nullable
    laplacian_variance REAL NOT NULL,
    embedding JSON,               -- Memorizzato tramite TensorJSON
    FOREIGN KEY(id_tour) REFERENCES tours(id)
);

-- Tabella Fasi/Scene Generate
CREATE TABLE scenes (
    id INTEGER PRIMARY KEY,
    id_tour INTEGER NOT NULL,
    title TEXT NOT NULL,
    FOREIGN KEY(id_tour) REFERENCES tours(id)
);

-- Tabella di Giunzione che collega Foto e Scene
CREATE TABLE scene_images (
    id_scene INTEGER NOT NULL,
    id_image INTEGER NOT NULL,
    PRIMARY KEY (id_scene, id_image),
    FOREIGN KEY(id_scene) REFERENCES scenes(id),
    FOREIGN KEY(id_image) REFERENCES images(id)
);
```

---

## 5. Generazione e Struttura del Pacchetto Tour

Al completamento, il tour viene esportato in una cartella strutturata sul disco locale dell'utente, progettata per essere auto-contenuta, interattiva e facilmente riproducibile in qualsiasi browser.

### Struttura della Cartella Esportata:
```text
[Tour_Name]/
├── index.html          # Player interattivo (HTML5 + CSS + JS compilato)
├── tour_data.json      # Testo narrativo, mapping immagini e metadati
├── css/
│   └── style.css       # Stili layout e transizioni (effetto cinematografico Ken Burns)
└── images/
    ├── photo_001.jpg   # Immagini del tour ottimizzate
    ├── photo_002.jpg
    └── ...
```

### Funzionalità del Player Esportato (`index.html`):
1.  **Lettura Narrata (TTS)**: sfrutta la **Web Speech API** nativa del browser, gratuita e offline, per leggere ad alta voce il testo della scena attiva nella lingua scelta dall'utente.
2.  **Transizioni Foto Sincronizzate**: un parser JS leggero scandisce il testo narrativo per tag come `[photo_001.jpg]`. Man mano che il motore Speech Synthesis avanza nelle frasi pronunciate, attiva transizioni visive per mantenere la foto attiva in perfetta sincronia.
3.  **Transizioni Cinematografiche (Effetto Ken Burns)**: le foto sono mostrate a schermo intero con animazioni pan e zoom fluide guidate da CSS, simulando un documentario di alta qualità. Questo mantiene alto il coinvolgimento del pubblico senza salti improvvisi sulla mappa o discrepanze nelle coordinate.

---

## 6. Note su Connettività e Compatibilità

1.  TripTour **non è completamente offline by design** in questa versione perché arricchimento e generazione narrativa si basano su un endpoint compatibile OpenAI configurato dall'utente.
2.  I deployment solo locali restano possibili quando l'utente punta l'app a un endpoint self-hosted/locale (per esempio un gateway locale intorno a Ollama o vLLM).
3.  L'app è agnostica rispetto all'endpoint: la compatibilità si basa sul comportamento API stile OpenAI (chat/completions, supporto multimodale per il modello di arricchimento).

---

## 7. Utility di Sviluppo: Fill Settings

Lo script `scripts/fill_settings.py` è un helper solo sviluppo per popolare rapidamente le impostazioni dell'applicazione da prompt terminale.

Eseguilo dalla root del progetto come modulo Python:

```bash
python -m scripts.fill_settings
```

Usa l'esecuzione come modulo (`-m`) invece di eseguire il file direttamente, così Python risolve correttamente gli import di pacchetto (per esempio `from app.settings import ...`).

## Licenza

GNU GPLv3
