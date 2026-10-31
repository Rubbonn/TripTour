# Documento di Specifiche Tecniche (V9): TripTour

Questo documento descrive le specifiche di sviluppo di **TripTour**, un **servizio web** che trasforma raccolte non strutturate di foto di viaggio in tour virtuali narrati. Gli utenti caricano le foto dal browser; il server le ordina, le filtra, le geolocalizza e le descrive, le raggruppa in scene e scrive uno script narrativo, che un player nel browser legge ad alta voce mentre mostra le foto.

Il servizio è composto da un **backend Python** (framework web da definire) che renderizza pagine HTML in gran parte statiche, con componenti **Svelte** montati solo sulle parti della pagina che hanno bisogno di reattività. Le sessioni utente sono conservate in **Redis** e i dati persistenti in **MariaDB**.

TripTour utilizza un'**architettura AI ibrida**, interamente lato server:
- Un **modello Transformers locale** sul server calcola gli embedding delle immagini (supporto a deduplicazione, propagazione delle posizioni e clustering).
- **LangChain + API compatibili OpenAI** sono usati per l'arricchimento multimodale e la sintesi narrativa finale.
- URL endpoint, chiave API e modelli (modello vision + modello testuale) sono definiti dall'**operatore del servizio** nella configurazione del server. Gli utenti non si occupano mai della configurazione AI.

L'accesso al servizio richiede un account utente: ogni utente crea e gestisce i propri tour (vedi Sezione 7). L'hosting dei tour degli utenti è una possibile evoluzione futura.

---

## 1. Architettura del Sistema

```
┌─────────────────────────────────────────────────────────────┐
│                           BROWSER                           │
│      Pagine HTML statiche + isole Svelte (UI dinamica)      │
└──────────────────────────────▲──────────────────────────────┘
                               │ HTTPS: pagine HTML + API JSON
┌──────────────────────────────▼──────────────────────────────┐
│         WEB BACKEND (Python, framework da definire)         │
│         Pagine · API JSON · Sessioni · Upload · Job         │
└───────┬──────────────────────┬──────────────────────┬───────┘
        │                      │                      │
┌───────▼───────┐   ┌──────────▼──────────┐   ┌───────▼───────┐
│     Redis     │   │   WORKER PIPELINE   │   │    MariaDB    │
│    sessioni   │   │   agenti LangChain  │   │      dati     │
│  (+ coda job) │   │ + embedder SigLIP 2 │   │  persistenti  │
└───────────────┘   └──────────┬──────────┘   └───────────────┘
                               │
               ┌───────────────┴───────────────┐
  ┌────────────▼────────────┐     ┌────────────▼────────────┐
  │       Storage foto      │     │     Servizi esterni     │
  │      upload, export     │     │ endpoint AI, Nominatim, │
  │                         │     │        Wikipedia        │
  └─────────────────────────┘     └─────────────────────────┘
```

* **Frontend — pagine statiche + isole Svelte**: le pagine sono renderizzate dal backend come semplice HTML. Gli elementi che non hanno bisogno di reattività (header, footer, navigazione, contenuti statici) restano statici; i **componenti Svelte** vengono montati solo sulle parti dinamiche della pagina — upload delle foto, avanzamento della pipeline, Storyboard Editor, player del tour — e comunicano con il backend tramite l'API JSON.
* **Web backend (Python, framework da definire)**: renderizza le pagine, espone l'API JSON usata dai componenti Svelte, riceve gli upload, gestisce le sessioni utente e accoda i job della pipeline. Il codice di elaborazione in `app/` viene usato dal backend come libreria.
* **Worker della pipeline**: le fasi di elaborazione (Sezione 2) durano da pochi secondi a molti minuti — inferenza degli embedding, una chiamata al modello vision per ogni foto, chiamate ad API esterne — quindi vengono eseguite fuori dal ciclo della richiesta HTTP, in worker in background alimentati da una coda di job (Redis può fare anche da broker; la libreria per la coda è da definire). Il frontend segue l'avanzamento di ogni job (polling, SSE o WebSocket, da definire). I worker condividono con il backend MariaDB e lo storage delle foto.
* **Redis**: conserva le sessioni utente; può fare anche da broker della coda di job e da cache dei risultati delle API esterne (reverse geocoding, Wikipedia).
* **MariaDB**: conserva i dati persistenti (utenti, tour, immagini, scene), a cui si accede tramite l'ORM SQLAlchemy.
* **Storage foto**: le foto caricate e i pacchetti esportati sono conservati in uno storage lato server (volume locale o object storage compatibile S3, da definire); il database ne memorizza solo la posizione.
* **Servizi esterni**: l'endpoint AI compatibile OpenAI configurato dall'operatore, OpenStreetMap Nominatim (reverse geocoding) e l'API di Wikipedia (articoli di contesto).

---

## 2. Flusso Utente & Pipeline di Elaborazione Dettagliata

```
[ Registrazione / Login ]
    │
    └──► [ Homepage ]
            │
            ├──► [ I Miei Tour ] ──► [ Apri un Tour Precedente (Storyboard / Player) ]
            │
            └──► [ Nuovo Tour ]
                    │
                    ├──► Carica le foto, scegli Lingua e Nome Tour (browser)
                    │
                    ├──► FASE 0: Estrazione Metadati & Ordinamento Multi-Livello (EXIF → Regex sul Filename → Data File → Ordine di Upload)
                    │
                    ├──► FASE 1: Filtraggio e De-duplicazione (Embedding SigLIP 2 + Varianza del Laplaciano)
                    │
                    ├──► FASE 2: Arricchimento Basato su Anchor (Punti Anchor + Propagazione Posizioni + Modello Vision Remoto)
                    │
                    ├──► FASE 3: Clustering Ibrido (Spazio-Tempo / Tempo+Visivo / Rilevamento Cambiamenti Semantici)
                    │
                    ├──► FASE 4: Storyboard Editor (Componente Svelte - Modifiche Manuali)
                    │
                    ├──► FASE 5: Generazione Script (Modello Testuale Remoto + Nome Tour + Tag Inline)
                    │
                    └──► [ Player nel Browser & Esportazione Pacchetto ]
```

Le Fasi 0–3 e 5 vengono eseguite come job in background sui worker della pipeline; la Fase 4 è il passaggio interattivo nel browser.

### Fase 0: Creazione del Tour, Upload e Ordinamento Multi-Livello (Sanitizzazione)
1.  **Creazione del Tour**: dalla homepage l'utente avvia un nuovo tour, scegliendo:
    * la **Lingua** del tour (salvata come codice, es. `it`, `en`), usata per le descrizioni delle foto e per la narrazione finale.
    * il **Nome Tour**: un titolo descrittivo (es. *"Visita ai Musei Vaticani"* oppure *"Vacanze in Toscana 2026"*). Questo nome viene salvato nel database e **diventa un metadato cruciale** passato ai modelli AI nelle fasi successive per guidarne la comprensione dei contesti storici, geografici e artistici.
2.  **Upload delle Foto**: l'utente seleziona dal browser dei file o un'intera cartella (selettore file o drag & drop). I formati supportati sono JPEG, PNG e WebP. I file vengono caricati **senza modifiche**, così che i loro metadati EXIF arrivino intatti al server. Insieme a ogni file il browser invia il suo timestamp `lastModified`, l'unica data del file disponibile in un contesto web (sul server, le date del file rifletterebbero solo l'upload). Le foto importate possono essere in un ordine completamente non strutturato.
3.  **Estrazione dei Metadati**: per ogni foto il backend rileva il MIME type ed estrae:
    * le **coordinate GPS** dal blocco EXIF `GPSInfo` (`GPSLatitude`, `GPSLongitude`, `GPSLatitudeRef`, `GPSLongitudeRef`). Le coordinate `0, 0`, scritte da alcuni dispositivi quando non hanno agganciato il segnale GPS, vengono scartate.
    * l'**indirizzo**, tramite reverse geocoding delle coordinate (vedi Step 2.2).
    * la **data di scatto**, seguendo la strategia multi-livello descritta sotto.
    * la **nitidezza**, come varianza del Laplaciano calcolata su una copia in scala di grigi ridotta a 1024 px con una leggera sfocatura gaussiana (usata nella Fase 1).
4.  **Strategia Multi-Livello per la Data**: prima che venga eseguita qualunque analisi, a ogni foto viene assegnato un timestamp usando la prima fonte disponibile nella seguente catena di priorità. Il livello usato viene registrato nella colonna `date_confidence`, abilitando trasparenza e correzione manuale nello Storyboard Editor:

    | `date_confidence` | Fonte | Descrizione |
    |----------|--------|-------------|
    | **1 (Più Alta)** | **EXIF** | `DateTimeOriginal`, poi `DateTimeDigitized`, poi `DateTime` — il vero timestamp di scatto. |
    | **2** | **Parsing Regex sul Filename** | Un insieme di regex riconosce i timestamp inseriti da fotocamere e app: `IMG_20260725_143012` (anche `VID_` e `MVIMG_`), `PXL_20260725_143012123` (millisecondi opzionali), `20260725_143012`, `2026-07-25_14-30-12` / `2026-07-25 14.30.12`, `Screenshot_20260725-143012`, `Screenshot 2026-07-25 at 14.30.12`, `signal-2026-07-25-143012`. |
    | **3** | **Data del File** | Il timestamp `lastModified` del file, così come riportato dal browser al momento dell'upload. |
    | **4 (Più Bassa)** | **Nessuna** | Nessuna data disponibile: la foto mantiene la sua posizione nell'ordine di upload. |

5.  **Ordinamento**: le foto con una data vengono ordinate cronologicamente, mentre le foto senza data mantengono la loro posizione originale nella sequenza.
6.  **Livelli di Confidenza della Posizione**: oltre a `date_confidence`, ogni foto registra `gps_confidence` e `address_confidence`, con i seguenti livelli:

    | Livello | `gps_confidence` / `address_confidence` |
    |---------|------------------------------------------|
    | **1** | Coordinate EXIF proprie / reverse geocoding delle coordinate proprie della foto |
    | **2** | Ereditata da un Anchor — confidenza alta (Step 2.3) |
    | **3** | Ereditata da un Anchor — confidenza bassa (Step 2.3) |
    | **4** | Non disponibile |

### Fase 1: Filtraggio & Rimozione Duplicati (Deduplicazione)
Usando la sequenza appena ordinata, per prevenire ridondanza visiva (come più scatti dello stesso soggetto):
1.  Il worker carica un modello locale di embedding immagini, `google/siglip2-base-patch16-512` (SigLIP 2) tramite Transformers, una sola volta per processo.
2.  Genera un vettore (embedding) per ogni foto. **Questi embedding vengono persistiti** (memorizzati nella colonna `embedding` della tabella `images`) per il riuso nello Step 2.3 (tie-breaking per affinità visiva) e nella Fase 3 (clustering Tempo+Visivo e Rilevamento Cambiamenti Semantici), evitando inferenze ridondanti.
3.  Calcola la similarità coseno tra **tutte le coppie** di foto del tour, non solo tra quelle adiacenti, così da individuare scatti quasi identici anche quando non sono consecutivi.
4.  **Risoluzione Duplicati**: quando due foto superano la soglia di similarità (**> 0.95**), quella con la varianza del Laplaciano più bassa (la più sfocata) viene rimossa dalla sequenza del tour. Il controllo viene ripetuto finché nessuna coppia supera la soglia.

### Fase 2: Arricchimento Basato su Anchor (Punti Anchor + Propagazione Posizioni + Modello Vision)
La fase di arricchimento segue una strategia **Anchor-Based**: le foto di cui sono certi sia la posizione sia l'orario fungono da **Anchor Points**, e la loro posizione viene propagata alle foto vicine prive di GPS. Questo garantisce la massima copertura anche quando GPS o timestamp sono parziali o assenti.

#### Step 2.1: Identificazione degli Anchor
Una foto è un **Anchor** quando sia le coordinate GPS sia la data provengono da EXIF (`gps_confidence = 1` e `date_confidence = 1`). Le foto con coordinate EXIF proprie ma una data meno affidabile mantengono le loro coordinate, ma non vengono usate come Anchor. Le foto senza coordinate sono candidate alla propagazione della posizione.

#### Step 2.2: Reverse Geocoding (Nominatim)
Le foto con coordinate proprie vengono geocodificate con OpenStreetMap Nominatim (`https://nominatim.openstreetmap.org/reverse`, `zoom=18`, `layer=poi`, con dettagli dell'indirizzo e tag extra). L'indirizzo completo e leggibile del punto di interesse più vicino (`display_name`) viene salvato nella colonna `address`. Se il geocoding fallisce, l'indirizzo resta vuoto (`address_confidence = 4`). In questa versione non è definito alcun provider di fallback.

#### Step 2.3: Propagazione delle Posizioni
Per ogni foto senza coordinate, il worker cerca l'Anchor più vicino **prima** e **dopo** di essa nella sequenza ordinata, e decide se ereditare la posizione di uno dei due usando due soglie: **150 m** (distanza di Haversine) e **1 ora**. Una data è considerata *affidabile* quando `date_confidence ≤ 2` (EXIF o filename).

| Situazione | Regola | Confidenza risultante |
|------------|--------|-----------------------|
| Un solo Anchor (prima o dopo) | Eredita la sua posizione se la data della foto non è affidabile, oppure se dista al massimo 1 ora dall'Anchor | 3 |
| Due Anchor, data non affidabile | Conta solo l'ordine: eredita dall'Anchor **visivamente più simile** (similarità coseno SigLIP 2) | 2 se gli Anchor distano tra loro al massimo 150 m e 1 ora, altrimenti 3 |
| Due Anchor, data affidabile, entrambi entro 1 ora | Si assume un **moto uniforme** tra gli Anchor: lo spostamento dall'Anchor più vicino nel tempo è stimato come `distanza × gap più vicino / gap totale`; eredita da quell'Anchor | 2 se lo spostamento stimato è ≤ 150 m, altrimenti 3 |
| Due Anchor, data affidabile, solo uno entro 1 ora, oppure Anchor entro 150 m tra loro | Eredita dall'Anchor più vicino nel tempo | 3 |
| Ogni altro caso | Nessuna eredità: la foto resta senza posizione | 4 |

Quando una posizione viene ereditata, viene ereditato anche l'indirizzo dell'Anchor, con lo stesso livello di confidenza. Le foto rimaste senza posizione vengono segnalate nello Storyboard Editor (Fase 4).

#### Step 2.4: Generazione di Descrizioni Contestuali (LangChain + Modello Vision)
Per ogni foto senza descrizione, il worker genera una descrizione fattuale usando il **modello multimodale remoto configurato** con la **finestra contestuale tripla scorrevole**, arricchita dalla posizione propagata. Il modello viene eseguito come agente LangChain, con ritentativi automatici delle chiamate ai tool fallite.

* Per analizzare l'immagine corrente N, il worker chiama l'endpoint chat-completions compatibile OpenAI configurato, passando:
    * l'**Immagine Corrente N**, con il suo nome file (che può contenere indizi, es. `colosseum_night.jpg`).
    * l'**Immagine Precedente N-1** insieme alla sua **descrizione già generata** (se N > 1).
    * l'**Immagine Successiva N+1** come puro contesto visivo (se N < numero totale di foto).
    * il **Nome Tour** fornito dall'utente e la **lingua della descrizione**.
    * la **posizione GPS**, l'**indirizzo** e la **data**, ciascuno segnalato come *stimato* quando non proviene dai metadati propri della foto.
    * gli **articoli Wikipedia sui luoghi vicini alla posizione GPS** (geosearch, fino a 3 articoli convertiti in Markdown, senza sezioni come note, bibliografia e collegamenti esterni).
* **Utilizzo dei Tool (agente LangChain)**: il modello può chiamare il tool **`wikipedia_search_keyword`** (ricerca full-text su Wikipedia in inglese) per identificare o confermare un soggetto specifico — un monumento, una chiesa, un'opera d'arte, una piazza — non coperto dagli articoli forniti, con al massimo 3 ricerche.
* Il prompt di sistema istruisce il modello a:
    * partire da ciò che è effettivamente visibile: soggetto principale, tipo di inquadratura (panorama, facciata, interno, dettaglio ravvicinato, persone, cibo, ...) ed elementi notevoli (architettura, opere d'arte, iscrizioni, paesaggio);
    * identificare il luogo o il soggetto combinando l'immagine con i metadati e gli articoli, dichiarandolo quando l'identificazione è probabile ma non certa (*"probabilmente ..."*), e senza mai inventare nomi, date o fatti storici;
    * aggiungere al massimo uno o due brevi fatti storici o artistici, solo su ciò che la foto mostra;
    * fidarsi dell'immagine quando contraddice i metadati stimati;
    * usare le foto adiacenti solo come contesto, senza descriverle (es. per riconoscere che la foto è un dettaglio ravvicinato di un soggetto visto nella precedente, o una panoramica di ciò che segue);
    * rispondere solo con la descrizione: da 3 a 6 frasi nella lingua richiesta, senza titoli, preamboli, elenchi o markdown.
* Per questo ruolo l'operatore deve configurare un modello che **supporti input immagine**.

### Fase 3: Clustering Ibrido & Generazione Storyboard
Il worker organizza la sequenza ordinata di foto in **Sezioni/Scene** logiche usando una strategia di **Clustering Ibrido**. Poiché le raccolte di foto reali hanno livelli diversi di completezza dei metadati, il sistema applica l'algoritmo di clustering più appropriato a ciascuna coppia di foto adiacenti, con fallback graduale quando GPS o timestamp non sono disponibili.

#### Gerarchia delle Strategie di Clustering

Il worker prova ogni strategia in ordine di priorità per ciascuna coppia di foto adiacenti. Viene usata la prima strategia con dati sufficienti per entrambe le foto:

| Priorità | Strategia | Requisiti | Metodo |
|----------|----------|-------------|--------|
| **1** | **Clustering Spazio-Tempo** | Entrambe le foto hanno GPS + Timestamp | raggio ~100m, finestra scorrevole ~15 min |
| **2** | **Clustering Tempo + Visivo** | Entrambe le foto hanno Timestamp (senza GPS) | finestra temporale + similarità coseno degli embedding |
| **3** | **Rilevamento Cambiamenti Semantici** | Nessun GPS, nessun Timestamp | cali di similarità coseno degli embedding tra foto adiacenti |

#### Strategia 1: Clustering Spazio-Tempo (GPS + Timestamp)
Il metodo di clustering ideale. Due foto adiacenti vengono raggruppate nella stessa sezione se:
- I loro orari di scatto sono entro **15 minuti** uno dall'altro.
- Le loro coordinate GPS sono entro **~100 metri** una dall'altra (usando la formula di Haversine).

Una nuova sezione viene creata quando il gap temporale supera la soglia o la distanza spaziale indica un cambio significativo di posizione.

#### Strategia 2: Clustering Tempo + Visivo (Solo Timestamp, Senza GPS)
Quando le foto hanno timestamp ma non coordinate GPS, il sistema combina prossimità temporale e similarità visiva degli embedding:
- Due foto adiacenti vengono raggruppate se il loro delta temporale è entro **30 minuti**.
- Se il delta temporale è borderline (tra 15–120 minuti), un controllo di **similarità coseno** agisce da tie-breaker: foto con alta similarità visiva (> 0.7) restano insieme anche con un gap temporale più lungo (es. scatti interni dello stesso museo distribuiti nel tempo), mentre foto visivamente dissimili attivano una separazione di sezione.

#### Strategia 3: Rilevamento Cambiamenti Semantici (Nessun GPS, Nessun Timestamp)
Quando le foto non hanno né GPS né timestamp affidabili, il clustering si basa puramente sulla semantica visiva. Il sistema usa gli embedding persistiti di tutte le coppie di foto adiacenti e rileva **Punti di Cambiamento Semantico** — posizioni in cui la similarità coseno cala bruscamente, indicando una probabile transizione di scena/capitolo.

L'algoritmo:
1. Calcola la similarità coseno per ogni coppia adiacente $(i, i+1)$.
2. Identifica **minimi locali** nella curva di similarità dove $\text{sim}(i, i+1) < \mu - k \cdot \sigma$ (cioè la similarità scende significativamente sotto la media mobile).
3. Posiziona i confini di sezione in questi punti di cambiamento rilevati.

#### Scelta della Strategia per Coppia
La funzione di clustering attraversa la sequenza ordinata di foto e, per ogni coppia adiacente, usa la prima strategia della gerarchia di cui entrambe le foto soddisfano i requisiti. Lo scopo è trovare le **linee di separazione tra eventi e attrazioni**: ogni coppia resta nella stessa sezione oppure segna un confine di sezione. In una raccolta con metadati misti, tratti diversi dello stesso tour possono quindi essere separati da strategie diverse.

> **Filosofia Plug & Play**: questo approccio ibrido incarna il principio di design centrale di TripTour — l'utente carica semplicemente le sue foto, e il sistema svolge automaticamente il miglior lavoro possibile. Lo Storyboard Editor (Fase 4) diventa quindi un'esperienza di rifinitura piacevole invece che un passaggio obbligato di correzione.

#### Generazione Metadati di Sezione
Dopo il clustering, ogni sezione viene automaticamente arricchita:
1.  Viene sintetizzato un **titolo di sezione** dalle descrizioni delle foto e dalla posizione dominante (es. "Ingresso Monumentale — Piazza del Duomo").
2.  Viene generata una **auto-descrizione preliminare** fondendo le descrizioni contestualizzate delle foto costituenti la sezione.
3.  Le foto senza posizione (`gps_confidence = 4`) vengono segnalate nella UI (evidenziazione rossa) per la correzione manuale nella Fase 4.

### Fase 4: Storyboard Editor (Interfaccia Utente)
Lo Storyboard Editor è un componente Svelte montato nella pagina del tour: carica la struttura dello storyboard dall'API JSON e salva ogni modifica tramite la stessa API.
* Le foto sono raggruppate visivamente nelle sezioni/fasi calcolate.
* **Trasparenza Anchor & Metadati**: ogni foto mostra piccoli badge che indicano se è un Anchor e la confidenza di data, posizione e indirizzo (🟢 livello 1, metadati propri / 🟡 livelli 2–3, stimati / 🔴 livello 4, assenti), insieme alla fonte della data usata nella Fase 0 (EXIF, filename, data del file o nessuna). Questo consente agli utenti di capire subito quali foto hanno metadati affidabili e quali sono state posizionate euristicamente.
* **Gestione Errori GPS / Posizione**: le foto senza posizione sono evidenziate in rosso. L'utente può digitare manualmente una posizione per la fase o trascinare foto in una fase esistente.
* **Interattività Completa**: gli utenti possono trascinare foto per riordinarle tra sezioni, creare nuove sezioni vuote, rinominarle, eliminare scatti indesiderati o modificare manualmente descrizioni e posizioni ereditate.
* **Modifica in Blocco**: possibilità di selezionare più foto contemporaneamente per assegnare loro la stessa posizione con un solo clic.
* **Ricalcola**: un pulsante consente di rieseguire la Fase 3 (Clustering Ibrido), come nuovo job in background, se gli utenti vogliono reimpostare il raggruppamento automatico dopo aver effettuato modifiche manuali a ordine o metadati.

### Fase 5: Sintesi Narrativa e Tagging Temporale (LangChain)
Una volta che l'utente conferma lo storyboard modificato:
1.  Il worker costruisce una pipeline di generazione con LangChain usando il **modello narrativo** (focalizzato sul testo) configurato sul server.
2.  Tutte le informazioni dello storyboard (posizioni, descrizioni dettagliate e contestualizzate, ordine cronologico), insieme a **Nome Tour** e **Lingua di Destinazione**, vengono aggregate e inviate all'endpoint configurato.
3.  Il modello elabora questo testo strutturale e il nome del tour (es. *"Vacanza a Roma 2026"*) e genera lo script narrativo finale direttamente nella lingua di destinazione.
4.  **Sincronizzazione**: il modello incorpora nel testo tag inline speciali per indicare esattamente quando il player deve passare alla foto successiva.

* *Esempio di output LLM:*
    > `[photo_001.jpg] Benvenuti a Palazzo Vecchio, uno dei simboli iconici di Firenze. [photo_002.jpg] Avvicinandoci al portale principale, risalta la maestosa copia del David di Michelangelo. [photo_003.jpg] Se osserviamo da vicino i dettagli in pietra scolpita sulla sinistra...`

---

## 3. Architettura di Orchestrazione AI

TripTour separa l'indicizzazione visiva locale dall'orchestrazione dei modelli. Entrambe vengono eseguite sul server, all'interno dei worker della pipeline.

### 3.1 Layer Locale di Embedding (Transformers)
Solo i carichi di lavoro di embedding passano attraverso un modello `transformers` locale di Hugging Face: `google/siglip2-base-patch16-512` (SigLIP 2). I suoi pesi sono in cache in `.model_cache`, viene caricato una sola volta per processo worker e gira su CPU o su GPU CUDA a seconda della build di PyTorch installata (`pytorch-cpu.txt` / `pytorch-cuda.txt`). Viene usato in:
1.  **Fase 1 (Deduplicazione)**: embedding + punteggio qualità Laplaciano.
2.  **Step 2.3 (Tie-Breaking)**: riuso degli embedding persistiti per scegliere tra due Anchor.
3.  **Fase 3 (Clustering)**: riuso degli embedding persistiti per Tempo+Visivo e Rilevamento Cambiamenti Semantici.

### 3.2 Layer di Inferenza Remota (LangChain)
Tutte le attività generative/orchestrazione modello vengono eseguite tramite un'astrazione client compatibile OpenAI:
1.  **Modello Multimodale di Arricchimento**: usato in Fase 2, deve accettare input immagine.
2.  **Modello di Generazione Narrativa**: usato in Fase 5, ottimizzato per output testuali long-form.
3.  **Agnosticismo Endpoint**: può essere configurato qualsiasi endpoint compatibile (OpenAI, OpenRouter, gateway vLLM self-hosted, bridge compatibili Ollama, ecc.).

### 3.3 Configurazione AI Lato Server
1.  URL endpoint, chiave API e identificativo del modello di arricchimento e del modello narrativo sono definiti dall'operatore nella configurazione del server (variabili d'ambiente / file `.env`). Non vengono mai salvati nel database né inviati al browser.
2.  Gli utenti non configurano nulla: non esistono un wizard di setup né una pagina di impostazioni AI.
3.  All'avvio il servizio valida la configurazione con una chiamata di test leggera e verifica che il modello di arricchimento sia vision-capable.

---

## 4. Archiviazione dei Dati

| Componente | Contenuto |
|------------|-----------|
| **MariaDB** | Dati persistenti: utenti, tour, immagini, scene |
| **Redis** | Sessioni utente; opzionalmente coda di job e cache dei risultati delle API esterne |
| **Storage foto** | Foto caricate e pacchetti esportati |

### 4.1 Sessioni Utente (Redis)
Le sessioni sono lato server e identificano l'utente autenticato (Sezione 7.1): il browser conserva solo un cookie di sessione opaco (`HttpOnly`, `Secure`, `SameSite`), mentre i dati di sessione risiedono in Redis con una scadenza. In questo modo il backend resta stateless, e più istanze del backend possono servire lo stesso utente.

### 4.2 Storage delle Foto
Le foto caricate vengono salvate dal backend in uno storage lato server. La colonna `images.path` contiene la posizione del file salvato, mentre `filename` conserva il nome originale del file, usato come indizio nella Fase 2 e nei tag narrativi della Fase 5. I percorsi nello storage sono sempre generati dal server, mai presi dal client.

### 4.3 Schema del Database
Lo schema è definito dai modelli SQLAlchemy in `app/models.py` e creato a partire da essi (`Base.metadata.create_all`). Il DDL seguente è generato dai modelli attuali:

```sql
-- Tabella Tour Virtuali
CREATE TABLE tours (
    id INTEGER NOT NULL,                 -- Chiave primaria auto-incrementale
    title VARCHAR NOT NULL,              -- Nome del tour, passato anche ai modelli AI
    language VARCHAR NOT NULL,           -- Codice lingua del tour (es. "it", "en")
    created_at DATETIME NOT NULL,        -- Impostata dall'ORM all'inserimento
    PRIMARY KEY (id)
);

-- Tabella Fasi/Scene Generate
CREATE TABLE scenes (
    id INTEGER NOT NULL,                 -- Chiave primaria auto-incrementale
    id_tour INTEGER NOT NULL,            -- Tour a cui appartiene la scena
    position INTEGER NOT NULL,           -- Ordine della scena nel tour (da 0)
    title VARCHAR NOT NULL,              -- Titolo della scena
    PRIMARY KEY (id),
    FOREIGN KEY(id_tour) REFERENCES tours (id)
);

-- Tabella Foto
CREATE TABLE images (
    id INTEGER NOT NULL,                 -- Chiave primaria auto-incrementale
    id_tour INTEGER NOT NULL,            -- Tour a cui appartiene la foto
    id_scene INTEGER,                    -- Scena a cui appartiene la foto (vuota fino alla Fase 3)
    position INTEGER,                    -- Ordine della foto nella sua scena (da 0)
    path VARCHAR NOT NULL,               -- Posizione del file salvato
    filename VARCHAR NOT NULL,           -- Nome originale del file
    mime VARCHAR NOT NULL,               -- MIME type (es. "image/jpeg")
    latitude DOUBLE,                     -- Latitudine propria o ereditata
    longitude DOUBLE,                    -- Longitudine propria o ereditata
    gps_confidence INTEGER NOT NULL,     -- 1 = EXIF, 2-3 = ereditata, 4 = assente
    address VARCHAR,                     -- Indirizzo geocodificato o ereditato
    address_confidence INTEGER NOT NULL, -- 1 = geocodificato, 2-3 = ereditato, 4 = assente
    date DATETIME,                       -- Data di scatto
    date_confidence INTEGER NOT NULL,    -- 1 = EXIF, 2 = filename, 3 = data file, 4 = assente
    description VARCHAR,                 -- Descrizione generata nella Fase 2
    laplacian_variance DOUBLE NOT NULL,  -- Punteggio di nitidezza (Fase 1)
    embedding JSON,                      -- Embedding SigLIP 2, memorizzato tramite TensorJSON
    PRIMARY KEY (id),
    FOREIGN KEY(id_tour) REFERENCES tours (id),
    FOREIGN KEY(id_scene) REFERENCES scenes (id)
);
```

* **Relazioni**: un tour ha molte immagini e molte scene; ogni foto appartiene al massimo a una scena, e una scena contiene molte foto.
* **Ordinamento**: le colonne `position` sono mantenute aggiornate dalle ordering list di SQLAlchemy (`ordering_list`): viene salvato l'ordine in memoria delle scene di un tour e delle foto di una scena, e spostare una foto o una scena rinumera le posizioni. La sequenza completa del tour è data dalle foto di ogni scena, scena per scena.
* **`embedding`**: il tipo personalizzato `TensorJSON` converte un `torch.Tensor` in un array JSON di valori `float32` (preservandone la forma) e viceversa.
* **Colonne di confidenza**: il significato dei livelli è descritto nella Fase 0 e nello Step 2.3.

---

## 5. Player del Tour & Esportazione del Pacchetto

Una volta generata la narrazione, il tour può essere riprodotto direttamente nel browser, nella pagina player del servizio, oppure esportato come pacchetto auto-contenuto.

### Struttura del Pacchetto Esportato
Il pacchetto viene scaricato come archivio ZIP, progettato per essere auto-contenuto, interattivo e facilmente riproducibile in qualsiasi browser:
```text
[Tour_Name]/
├── index.html          # Player interattivo (HTML5 + CSS + JS compilato)
├── tour_data.json      # Testo narrativo, mapping immagini e metadati
├── css/
│   └── style.css       # Stili layout e transizioni (effetto cinematografico Ken Burns)
└── images/
    ├── photo_001.jpg   # Immagini del tour ottimizzate (ridimensionate, senza metadati EXIF)
    ├── photo_002.jpg
    └── ...
```

### Funzionalità del Player
1.  **Lettura Narrata (TTS)**: sfrutta la **Web Speech API** nativa e gratuita del browser per leggere ad alta voce il testo della scena attiva nella lingua del tour, senza sintesi vocale lato server. Le voci disponibili dipendono dal browser e dal sistema operativo.
2.  **Transizioni Foto Sincronizzate**: un parser JS leggero scandisce il testo narrativo per tag come `[photo_001.jpg]`. Man mano che il motore Speech Synthesis avanza nelle frasi pronunciate, attiva transizioni visive per mantenere la foto attiva in perfetta sincronia.
3.  **Transizioni Cinematografiche (Effetto Ken Burns)**: le foto sono mostrate a schermo intero con animazioni pan e zoom fluide guidate da CSS, simulando un documentario di alta qualità. Questo mantiene alto il coinvolgimento del pubblico senza salti improvvisi sulla mappa o discrepanze nelle coordinate.

---

## 6. Note Operative e di Compatibilità

1.  **Dipendenze esterne**: arricchimento e narrazione si basano sull'endpoint AI configurato dall'operatore, il reverse geocoding su Nominatim e gli articoli di contesto sull'API di Wikipedia.
2.  **Agnosticismo dell'endpoint**: la compatibilità si basa sul comportamento API stile OpenAI (chat/completions, supporto multimodale per il modello di arricchimento). L'operatore può usare un provider commerciale o un gateway self-hosted (vLLM, compatibile Ollama) sulla propria infrastruttura.
3.  **Policy d'uso di terze parti**: l'istanza pubblica di Nominatim consente al massimo 1 richiesta al secondo e richiede uno User-Agent identificativo; anche l'API di Wikipedia lo richiede e applica dei rate limit (le richieste vengono ritentate, rispettando `Retry-After` in caso di HTTP 429). Con molti utenti contemporanei, le richieste vanno limitate e messe in cache (es. in Redis), oppure spostate su un geocoder self-hosted o commerciale.
4.  **Metadati di posizione all'upload**: alcuni browser mobili e selettori di foto del sistema operativo rimuovono i dati di posizione dalle foto prima di caricarle. Queste foto arrivano al server senza GPS e si affidano alla propagazione delle posizioni (Step 2.3).
5.  **Costi AI**: poiché l'AI è configurata lato server, ogni chiamata di arricchimento e narrazione è a carico dell'operatore; servono quindi dei limiti per utente (Sezione 7.1).

---

## 7. Account Utente & Evoluzione Futura

### 7.1 Account Utente
Il servizio è disponibile solo per gli utenti registrati.
* **Registrazione e login**: a parte le pagine di registrazione e login, ogni pagina e ogni chiamata API richiede una sessione autenticata, conservata in Redis (Sezione 4.1).
* **Proprietà dei tour**: ogni tour appartiene all'utente che l'ha creato; il modello dati viene esteso con una tabella `users` e una chiave esterna `tours.id_user`. La homepage elenca i tour dell'utente, che possono essere riaperti in qualsiasi momento nello Storyboard Editor o nel player.
* **Quote**: limiti per utente su numero di foto per tour, spazio di archiviazione e chiamate AI, per tenere sotto controllo i costi dell'operatore.

### 7.2 Evoluzione Futura: Hosting dei Tour
Gli utenti potranno pubblicare un tour completato, riproducibile a un URL pubblico servito dalla piattaforma, in alternativa all'esportazione del pacchetto. Ogni tour ha un livello di visibilità (privato, solo con link, pubblico); le foto pubblicate vengono ridimensionate e private dei metadati EXIF, così che le coordinate GPS degli originali non vengano esposte.

---

## Licenza

GNU GPLv3
