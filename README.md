# Technical Specifications Document (V9): TripTour

This document outlines the development specifications for **TripTour**, a **web service** that transforms unstructured collections of travel photos into narrated virtual tours. Users upload their photos from the browser; the server sorts, filters, geolocates and describes them, groups them into scenes and writes a narrative script, which a browser-based player reads aloud while showing the photos.

The service is made of a **Python backend** (web framework to be defined) that renders mostly static HTML pages, with **Svelte** components mounted only on the parts of a page that need reactivity. User sessions are kept in **Redis** and persistent data in **MariaDB**.

TripTour uses a **hybrid AI architecture**, entirely server-side:
- A **local Transformers model** on the server computes image embeddings (support for deduplication, position propagation and clustering).
- **LangChain/LangGraph + OpenAI-compatible APIs** are used for multimodal enrichment and final narrative synthesis.
- Endpoint URL, API key and models (vision model + text model) are defined by the **service operator** in the server configuration. Users never deal with AI configuration.

Access to the service requires a user account: each user creates and manages their own tours (see Section 7). Hosting users' tours is a possible future evolution.

---

## 1. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                           BROWSER                           │
│       Static HTML pages + Svelte islands (dynamic UI)       │
└──────────────────────────────▲──────────────────────────────┘
                               │ HTTPS: HTML pages + JSON API
┌──────────────────────────────▼──────────────────────────────┐
│             WEB BACKEND (Python, framework TBD)             │
│         Pages · JSON API · Sessions · Uploads · Jobs        │
└───────┬──────────────────────┬──────────────────────┬───────┘
        │                      │                      │
┌───────▼───────┐   ┌──────────▼──────────┐   ┌───────▼───────┐
│     Redis     │   │  PIPELINE WORKER(S) │   │    MariaDB    │
│    sessions   │   │ LangGraph workflows │   │   persistent  │
│ (+ job queue) │   │ + SigLIP 2 embedder │   │      data     │
└───────────────┘   └──────────┬──────────┘   └───────────────┘
                               │
               ┌───────────────┴───────────────┐
  ┌────────────▼────────────┐     ┌────────────▼────────────┐
  │      Photo storage      │     │    External services    │
  │     uploads, exports    │     │ AI endpoint, Nominatim, │
  │                         │     │        Wikipedia        │
  └─────────────────────────┘     └─────────────────────────┘
```

* **Frontend — static pages + Svelte islands**: pages are rendered by the backend as plain HTML. Elements that need no reactivity (header, footer, navigation, static content) stay static; **Svelte components** are mounted only on the dynamic parts of a page — photo upload, pipeline progress, storyboard editor, tour player — and talk to the backend through the JSON API.
* **Web backend (Python, framework to be defined)**: renders the pages, exposes the JSON API used by the Svelte components, receives uploads, manages user sessions and dispatches pipeline jobs. The processing code in `app/` is used by the backend as a library.
* **Pipeline workers**: the processing phases (Section 2) take from seconds to many minutes — embedding inference, one vision-model call per photo, external API calls — so they run outside the HTTP request cycle, in background workers fed by a job queue (Redis can double as the broker; the queue library is to be defined). The frontend follows the progress of each job (polling, SSE or WebSocket, to be defined). Workers share MariaDB and the photo storage with the backend.
* **Redis**: stores user sessions; it can also act as job-queue broker and as a cache for external API results (reverse geocoding, Wikipedia).
* **MariaDB**: stores persistent data (users, tours, images, scenes), accessed through the SQLAlchemy ORM.
* **Photo storage**: uploaded photos and exported packages are kept in server-side storage (local volume or S3-compatible object storage, to be defined); the database only stores their location.
* **External services**: the OpenAI-compatible AI endpoint configured by the operator, OpenStreetMap Nominatim (reverse geocoding) and the Wikipedia API (contextual articles).

---

## 2. User Flow & Detailed Processing Pipeline

```
[ Sign Up / Log In ]
    │
    └──► [ Homepage ]
            │
            ├──► [ My Tours ] ──► [ Open a Previous Tour (Storyboard / Player) ]
            │
            └──► [ New Tour ]
                    │
                    ├──► Upload photos, choose Language and Tour Name (browser)
                    │
                    ├──► PHASE 0: Metadata Extraction & Multi-Level Sorting (EXIF → Filename Regex → File Date → Upload Order)
                    │
                    ├──► PHASE 1: Filtering and De-duplication (SigLIP 2 Embeddings + Laplacian Variance)
                    │
                    ├──► PHASE 2: Anchor-Based Enrichment (Anchor Points + Position Propagation + Remote Vision Model)
                    │
                    ├──► PHASE 3: Hybrid Clustering (Space-Time / Time+Visual / Semantic Change Detection)
                    │
                    ├──► PHASE 4: Storyboard Editor (Svelte Component - Manual Edits)
                    │
                    ├──► PHASE 5: Script Generation (Remote Text Model + Tour Name + Inline Tags)
                    │
                    └──► [ Browser Player & Package Export ]
```

Phases 0–3 and 5 run as background jobs on the pipeline workers; Phase 4 is the interactive step in the browser.

### Phase 0: Tour Creation, Upload and Multi-Level Sorting (Sanitization)
1.  **Tour Creation**: from the homepage the user starts a new tour, choosing:
    * The **Language** of the tour (stored as a code, e.g. `it`, `en`), used for the photo descriptions and for the final narration.
    * The **Tour Name**: a descriptive title (e.g. *"Vatican Museums Visit"* or *"Tuscany Holidays 2026"*). This name is stored in the database and **becomes a crucial piece of metadata** passed to the AI models in subsequent stages to guide their understanding of historical, geographical and artistic contexts.
2.  **Photo Upload**: the user selects files or a whole folder from the browser (file picker or drag & drop). Supported formats are JPEG, PNG and WebP. Files are uploaded **unmodified**, so that their EXIF metadata reaches the server intact. Together with each file the browser sends its `lastModified` timestamp, the only file date available in a web context (on the server, the file dates would only reflect the upload). Imported photos may be in a completely unstructured order.
3.  **Metadata Extraction**: for each photo the backend detects the MIME type and extracts:
    * **GPS coordinates** from the EXIF `GPSInfo` block (`GPSLatitude`, `GPSLongitude`, `GPSLatitudeRef`, `GPSLongitudeRef`). The coordinates `0, 0`, written by some devices when they have no GPS fix, are discarded.
    * **Address**, by reverse geocoding the coordinates (see Step 2.2).
    * **Capture date**, following the multi-level strategy below.
    * **Sharpness**, as the variance of the Laplacian computed on a grayscale copy downscaled to 1024 px with a light Gaussian blur (used in Phase 1).
4.  **Multi-Level Date Strategy**: before any analysis is performed, each photo is timestamped using the first available source in the following priority chain. The level used is recorded in the `date_confidence` column, enabling transparency and manual correction in the Storyboard Editor:

    | `date_confidence` | Source | Description |
    |----------|--------|-------------|
    | **1 (Highest)** | **EXIF** | `DateTimeOriginal`, then `DateTimeDigitized`, then `DateTime` — the true capture timestamp. |
    | **2** | **Regex Parsing on Filename** | A set of regexes recognizes the timestamps embedded by cameras and apps: `IMG_20260725_143012` (also `VID_` and `MVIMG_`), `PXL_20260725_143012123` (optional milliseconds), `20260725_143012`, `2026-07-25_14-30-12` / `2026-07-25 14.30.12`, `Screenshot_20260725-143012`, `Screenshot 2026-07-25 at 14.30.12`, `signal-2026-07-25-143012`. |
    | **3** | **File Date** | The file's `lastModified` timestamp, as reported by the browser at upload time. |
    | **4 (Lowest)** | **None** | No date available: the photo keeps its position in the upload order. |

5.  **Sorting**: dated photos are sorted chronologically, while photos without a date keep their original position in the sequence.
6.  **Position Confidence Levels**: besides `date_confidence`, each photo records `gps_confidence` and `address_confidence`, with the following levels:

    | Level | `gps_confidence` / `address_confidence` |
    |-------|------------------------------------------|
    | **1** | Own EXIF coordinates / reverse geocoding of the photo's own coordinates |
    | **2** | Inherited from an anchor — high confidence (Step 2.3) |
    | **3** | Inherited from an anchor — low confidence (Step 2.3) |
    | **4** | Not available |

### Phase 1: Filtering & Duplicate Removal (Deduplication)
Using the newly sorted sequence, to prevent visual redundancy (such as multiple shots of the same subject):
1.  The worker loads a local image embedding model, `google/siglip2-base-patch16-512` (SigLIP 2) via Transformers, once per process.
2.  It generates a vector (embedding) for each photo. **These embeddings are persisted** (stored in the `embedding` column of the `images` table) for reuse in Step 2.3 (visual affinity tie-breaking) and Phase 3 (Time+Visual and Semantic Change Detection clustering), avoiding redundant inference.
3.  It calculates the cosine similarity between **every pair** of photos of the tour, not only the adjacent ones, so that near-identical shots are caught even when they are not consecutive.
4.  **Duplicate Resolution**: when two photos exceed the similarity threshold (**> 0.95**), the one with the lower Laplacian variance (the blurrier one) is removed from the tour sequence. The check is repeated until no pair exceeds the threshold.

### Phase 2: Anchor-Based Enrichment (Anchor Points + Position Propagation + Vision Model)
The enrichment phase follows an **Anchor-Based** strategy: photos whose position and time are both certain serve as **Anchor Points**, and their location is propagated to the neighboring photos that lack GPS. This ensures maximum coverage even when GPS or timestamps are partial or absent.

#### Step 2.1: Anchor Identification
A photo is an **Anchor** when both its GPS coordinates and its date come from EXIF (`gps_confidence = 1` and `date_confidence = 1`). Photos with their own EXIF coordinates but a less reliable date keep their coordinates, but are not used as anchors. Photos without coordinates are candidates for position propagation.

#### Step 2.2: Reverse Geocoding (Nominatim)
The photos with their own coordinates are reverse geocoded with OpenStreetMap Nominatim (`https://nominatim.openstreetmap.org/reverse`, `zoom=18`, `layer=poi`, with address details and extra tags). The full human-readable address of the nearest point of interest (`display_name`) is stored in the `address` column. If geocoding fails, the address stays empty (`address_confidence = 4`). No fallback provider is defined in this version.

#### Step 2.3: Position Propagation
For each photo without coordinates, the worker looks for the nearest Anchor **before** and **after** it in the sorted sequence, and decides whether to inherit the position of one of them using two thresholds: **150 m** (Haversine distance) and **1 hour**. A date is considered *reliable* when `date_confidence ≤ 2` (EXIF or filename).

| Situation | Rule | Resulting confidence |
|-----------|------|----------------------|
| Only one Anchor (before or after) | Inherit its position if the photo's date is not reliable, or if it is within 1 hour of the Anchor | 3 |
| Two Anchors, date not reliable | Only the order is meaningful: inherit from the Anchor that is **visually most similar** (SigLIP 2 cosine similarity) | 2 if the Anchors are within 150 m and 1 hour of each other, otherwise 3 |
| Two Anchors, reliable date, both within 1 hour | Assume **uniform motion** between the Anchors: the displacement from the Anchor nearest in time is estimated as `distance × nearest gap / total gap`; inherit from that Anchor | 2 if the estimated displacement is ≤ 150 m, otherwise 3 |
| Two Anchors, reliable date, only one within 1 hour, or Anchors within 150 m of each other | Inherit from the Anchor nearest in time | 3 |
| Any other case | No inheritance: the photo stays without a position | 4 |

When a position is inherited, the Anchor's address is inherited too, with the same confidence level. Photos left without a position are flagged in the Storyboard Editor (Phase 4).

#### Step 2.4: Contextual Description Generation (LangChain/LangGraph + Vision Model)
For each photo without a description, the worker generates a factual description using the configured **remote multimodal model** with the **sliding triple-context window**, enriched by the propagated position. The model runs as a LangChain agent, with automatic retries of failed tool calls.

* To analyze the current image N, the worker calls the configured OpenAI-compatible chat-completions endpoint, passing:
    * The **Current Image N**, with its filename (which may contain hints, e.g. `colosseum_night.jpg`).
    * The **Previous Image N-1** coupled with its **already generated description** (if N > 1).
    * The **Next Image N+1** as pure visual context (if N < total number of photos).
    * The **Tour Name** provided by the user and the **description language**.
    * The **GPS position**, **address** and **date**, each marked as *estimated* when it does not come from the photo's own metadata.
    * The **Wikipedia articles about places near the GPS position** (geosearch, up to 3 articles converted to Markdown, without sections such as references, bibliography and external links).
* **Tool Usage (LangChain agent)**: the model can call the **`wikipedia_search_keyword`** tool (full-text search on English Wikipedia) to identify or confirm a specific subject — a monument, a church, an artwork, a square — that the provided articles don't cover, with at most 3 searches.
* The system prompt instructs the model to:
    * start from what is actually visible: main subject, type of shot (panorama, facade, interior, close-up detail, people, food, ...) and notable elements (architecture, artworks, inscriptions, landscape);
    * identify the place or subject by combining the image with the metadata and the articles, stating it when the identification is likely but not certain (*"probably ..."*), and never inventing names, dates or historical facts;
    * add at most one or two brief historical or artistic facts, only about what the photo shows;
    * trust the image over estimated metadata that contradicts it;
    * use the adjacent photos only as context, without describing them (e.g. to recognize that the photo is a close-up detail of a subject seen in the previous one, or an overview of what comes next);
    * answer with the description only: 3 to 6 sentences in the requested language, without titles, preambles, lists or markdown.
* The operator must configure a model that **supports image input** for this role.

### Phase 3: Hybrid Clustering & Storyboard Generation
The worker organizes the sorted sequence of photos into logical **Sections/Scenes** using a **Hybrid Clustering** strategy. Because real-world photo collections have varying levels of metadata completeness, the system applies the most appropriate clustering algorithm to each adjacent photo pair, falling back gracefully when GPS or timestamps are unavailable.

#### Clustering Strategy Hierarchy

The worker attempts each strategy in priority order per adjacent photo pair. The first strategy with sufficient data for both photos is used:

| Priority | Strategy | Requirements | Method |
|----------|----------|-------------|--------|
| **1** | **Space-Time Clustering** | Both photos have GPS + Timestamp | ~100m radius, ~15 min sliding window |
| **2** | **Time + Visual Clustering** | Both photos have Timestamp (no GPS) | Temporal window + embedding cosine similarity |
| **3** | **Semantic Change Detection** | No GPS, no Timestamp | Embedding cosine similarity drops between adjacent photos |

#### Strategy 1: Space-Time Clustering (GPS + Timestamp)
The ideal clustering method. Two adjacent photos are grouped into the same section if:
- Their capture times are within **15 minutes** of each other.
- Their GPS coordinates are within **~100 meters** of each other (using the Haversine formula).

A new section is created when either the temporal gap exceeds the threshold or the spatial distance indicates a significant location change.

#### Strategy 2: Time + Visual Clustering (Timestamp Only, No GPS)
When photos have timestamps but lack GPS coordinates, the system combines temporal proximity with visual similarity of the embeddings:
- Two adjacent photos are grouped if their time delta is within **30 minutes**.
- If the time delta is borderline (between 15–120 minutes), a **cosine similarity check** acts as a tie-breaker: photos with high visual similarity (> 0.7) are kept together even with a longer temporal gap (e.g., interior shots of the same museum spread over time), while visually dissimilar photos trigger a section break.

#### Strategy 3: Semantic Change Detection (No GPS, No Timestamp)
When photos have neither GPS nor reliable timestamps, clustering relies purely on visual semantics. The system uses the persisted embeddings of all adjacent photo pairs and detects **Semantic Change Points** — positions where the cosine similarity drops sharply, indicating a likely scene/chapter transition.

The algorithm:
1. Computes the cosine similarity for every adjacent pair $(i, i+1)$.
2. Identifies **local minima** in the similarity curve where $\text{sim}(i, i+1) < \mu - k \cdot \sigma$ (i.e., similarity falls significantly below the rolling mean).
3. Places section boundaries at these detected change points.

#### Per-Pair Strategy Selection
The clustering function traverses the sorted photo sequence and, for each adjacent pair, uses the first strategy of the hierarchy whose requirements both photos meet. The goal is to find the **dividing lines between events and attractions**: each pair either stays in the same section or marks a section boundary. In a collection with mixed metadata, different stretches of the same tour can therefore be split by different strategies.

> **Plug & Play Philosophy**: This hybrid approach embodies the core design principle of TripTour — the user simply uploads their photos, and the system automatically does the best possible job. The Storyboard Editor (Phase 4) then becomes a pleasant refining experience rather than a forced correction step.

#### Section Metadata Generation
After clustering, each section is automatically enriched:
1.  A **section title** is synthesized from the photo descriptions and the dominant location (e.g. "Monumental Entrance — Piazza del Duomo").
2.  A **preliminary auto-description** is generated by merging the contextualized descriptions of the section's constituent photos.
3.  Photos without a position (`gps_confidence = 4`) are flagged in the UI (red highlight) for manual correction in Phase 4.

### Phase 4: Storyboard Editor (User Interface)
The Storyboard Editor is a Svelte component mounted in the tour page: it loads the storyboard structure from the JSON API and saves every change back through it.
* Photos are visually grouped into the calculated sections/stages.
* **Anchor & Metadata Transparency**: each photo displays small badges for its Anchor status and for the confidence of its date, position and address (🟢 level 1, own metadata / 🟡 levels 2–3, estimated / 🔴 level 4, missing), together with the date source used in Phase 0 (EXIF, filename, file date or none). This lets users instantly understand which photos have reliable metadata and which were positioned heuristically.
* **GPS / Location Error Management**: photos without a position are highlighted in red. The user can manually type a location for the stage or drag and drop photos into an existing stage.
* **Full Interactivity**: users can drag photos to reorder them across sections, create new empty sections, rename them, delete unwanted shots, or manually edit descriptions and inherited locations.
* **Bulk Editing**: ability to select multiple photos at once to assign them the same location in a single click.
* **Recalculate**: a button allows users to re-run Phase 3 (Hybrid Clustering), as a new background job, if they want to reset automatic grouping after making manual adjustments to order or metadata.

### Phase 5: Narrative Synthesis and Temporal Tagging (LangChain/LangGraph)
Once the user confirms the edited storyboard:
1.  The worker builds a generation pipeline with LangChain/LangGraph using the **narrative model** (text-focused) configured on the server.
2.  All storyboard information (locations, detailed and contextualized descriptions, chronological order) along with the **Tour Name** and **Target Language** are bundled and sent to the configured endpoint.
3.  The model processes this structural text and the tour name (e.g., *"Rome Vacation 2026"*) and generates the final narrative script directly in the target language.
4.  **Synchronization**: The model embeds special inline tags into the text to indicate exactly when the player should transition to the next photo.

* *Example of LLM output:*
    > `[photo_001.jpg] Welcome to Palazzo Vecchio, one of the iconic symbols of Florence. [photo_002.jpg] As we approach the main portal, the majestic copy of Michelangelo's David stands out. [photo_003.jpg] If we look closely at the carved stone details on the left...`

---

## 3. AI Orchestration Architecture

TripTour separates local vision indexing from model orchestration. Both run on the server, inside the pipeline workers.

### 3.1 Local Embedding Layer (Transformers)
Only embedding workloads run through a local Hugging Face `transformers` model: `google/siglip2-base-patch16-512` (SigLIP 2). Its weights are cached in `.model_cache`, it is loaded once per worker process and runs on CPU or on a CUDA GPU depending on the installed PyTorch build (`pytorch-cpu.txt` / `pytorch-cuda.txt`). It is used in:
1.  **Phase 1 (Deduplication)**: embeddings + Laplacian quality scoring.
2.  **Step 2.3 (Tie-Breaking)**: reuse of the persisted embeddings to choose between two Anchors.
3.  **Phase 3 (Clustering)**: reuse of the persisted embeddings for Time+Visual and Semantic Change Detection.

### 3.2 Remote Inference Layer (LangChain/LangGraph)
All generative/model-orchestration tasks run through an OpenAI-compatible client abstraction:
1.  **Multimodal Enrichment Model**: used in Phase 2, must accept image inputs.
2.  **Narrative Generation Model**: used in Phase 5, optimized for long-form text output.
3.  **Endpoint Agnosticism**: any compatible endpoint can be configured (OpenAI, OpenRouter, self-hosted vLLM gateways, Ollama-compatible bridges, etc.).

### 3.3 Workflow Orchestration (LangGraph)
The pipeline phases are modeled as LangGraph `StateGraph` workflows, executed by the pipeline workers:
1.  **`PreFilterWorkflow`**: date sorting → duplicate removal (Phases 0–1).
2.  **`EnrichmentWorkflow`**: position propagation → description generation (Phase 2).
3.  Clustering (Phase 3) and narrative synthesis (Phase 5) are modeled as workflows in the same way.

### 3.4 Server-Side AI Configuration
1.  Endpoint URL, API key and model identifier of the enrichment model and of the narrative model are defined by the operator in the server configuration (environment variables / `.env` file). They are never stored in the database nor sent to the browser.
2.  Users configure nothing: there is no setup wizard and no AI settings page.
3.  At startup the service validates the configuration with a lightweight test call and checks that the enrichment model is vision-capable.

---

## 4. Data Storage

| Component | Content |
|-----------|---------|
| **MariaDB** | Persistent data: users, tours, images, scenes |
| **Redis** | User sessions; optionally job queue and cache of external API results |
| **Photo storage** | Uploaded photos and exported packages |

### 4.1 User Sessions (Redis)
Sessions are server-side and identify the logged-in user (Section 7.1): the browser only holds an opaque session cookie (`HttpOnly`, `Secure`, `SameSite`), while session data lives in Redis with an expiration time. This keeps the backend stateless, so that multiple backend instances can serve the same user.

### 4.2 Photo Storage
Uploaded photos are saved by the backend in server-side storage. The `images.path` column holds the location of the stored file, while `filename` keeps the original file name, used as a hint in Phase 2 and in the narrative tags of Phase 5. Storage paths are always generated by the server, never taken from the client.

### 4.3 Database Schema
The schema is defined by the SQLAlchemy models in `app/models.py` and created from them (`Base.metadata.create_all`). The DDL below is generated from the current models:

```sql
-- Virtual Tours Table
CREATE TABLE tours (
    id INTEGER NOT NULL,                 -- Auto-increment primary key
    title VARCHAR NOT NULL,              -- Tour name, also passed to the AI models
    language VARCHAR NOT NULL,           -- Tour language code (e.g. "it", "en")
    created_at DATETIME NOT NULL,        -- Set by the ORM on insert
    PRIMARY KEY (id)
);

-- Generated Stages/Scenes Table
CREATE TABLE scenes (
    id INTEGER NOT NULL,                 -- Auto-increment primary key
    id_tour INTEGER NOT NULL,            -- Tour the scene belongs to
    position INTEGER NOT NULL,           -- Order of the scene in the tour (from 0)
    title VARCHAR NOT NULL,              -- Scene title
    PRIMARY KEY (id),
    FOREIGN KEY(id_tour) REFERENCES tours (id)
);

-- Photos Table
CREATE TABLE images (
    id INTEGER NOT NULL,                 -- Auto-increment primary key
    id_tour INTEGER NOT NULL,            -- Tour the photo belongs to
    id_scene INTEGER,                    -- Scene the photo belongs to (empty until Phase 3)
    position INTEGER,                    -- Order of the photo in its scene (from 0)
    path VARCHAR NOT NULL,               -- Location of the stored file
    filename VARCHAR NOT NULL,           -- Original file name
    mime VARCHAR NOT NULL,               -- MIME type (e.g. "image/jpeg")
    latitude DOUBLE,                     -- Own or inherited latitude
    longitude DOUBLE,                    -- Own or inherited longitude
    gps_confidence INTEGER NOT NULL,     -- 1 = EXIF, 2-3 = inherited, 4 = none
    address VARCHAR,                     -- Reverse-geocoded or inherited address
    address_confidence INTEGER NOT NULL, -- 1 = geocoded, 2-3 = inherited, 4 = none
    date DATETIME,                       -- Capture date
    date_confidence INTEGER NOT NULL,    -- 1 = EXIF, 2 = filename, 3 = file date, 4 = none
    description VARCHAR,                 -- Description generated in Phase 2
    laplacian_variance DOUBLE NOT NULL,  -- Sharpness score (Phase 1)
    embedding JSON,                      -- SigLIP 2 embedding, stored through TensorJSON
    PRIMARY KEY (id),
    FOREIGN KEY(id_tour) REFERENCES tours (id),
    FOREIGN KEY(id_scene) REFERENCES scenes (id)
);
```

* **Relationships**: a tour has many images and many scenes; each photo belongs to at most one scene, and a scene contains many photos.
* **Ordering**: the `position` columns are kept up to date by SQLAlchemy ordering lists (`ordering_list`): the in-memory order of a tour's scenes and of a scene's photos is what gets saved, and moving a photo or a scene renumbers the positions. The full sequence of the tour is given by the photos of each scene, scene by scene.
* **`embedding`**: the custom `TensorJSON` type converts a `torch.Tensor` into a JSON array of `float32` values (preserving its shape) and back.
* **Confidence columns**: the meaning of the levels is described in Phase 0 and Step 2.3.

---

## 5. Tour Player & Package Export

Once the narrative is generated, the tour can be played directly in the browser, in the player page of the service, or exported as a self-contained package.

### Exported Package Structure
The package is downloaded as a ZIP archive, designed to be self-contained, interactive and easily playable on any browser:
```text
[Tour_Name]/
├── index.html          # Interactive player (HTML5 + CSS + Compiled JS)
├── tour_data.json      # Narrative text, image mapping, and metadata
├── css/
│   └── style.css       # Layout styles and transitions (cinematic Ken Burns effect)
└── images/
    ├── photo_001.jpg   # Optimized tour images (resized, without EXIF metadata)
    ├── photo_002.jpg
    └── ...
```

### Player Features
1.  **Narrated Reading (TTS)**: leverages the browser's native and free **Web Speech API** to read the active scene's text aloud in the tour language, with no server-side speech synthesis. The available voices depend on the browser and operating system.
2.  **Synchronized Photo Transitions**: a lightweight JS parser scans the narrative text for tags like `[photo_001.jpg]`. As the Speech Synthesis engine advances through the spoken sentences, it triggers visual transitions to keep the active photo in perfect sync.
3.  **Cinematic Transitions (Ken Burns Effect)**: photos are displayed full-screen with smooth, CSS-driven pan and zoom animations, simulating a high-quality documentary. This maintains viewer engagement without sudden map jumps or coordinate discrepancies.

---

## 6. Operational and Compatibility Notes

1.  **External dependencies**: enrichment and narration rely on the AI endpoint configured by the operator, reverse geocoding on Nominatim and contextual articles on the Wikipedia API.
2.  **Endpoint agnosticism**: compatibility is based on OpenAI-style API behavior (chat/completions, multimodal support for the enrichment model). The operator can use a commercial provider or a self-hosted gateway (vLLM, Ollama-compatible) on their own infrastructure.
3.  **Third-party usage policies**: the public Nominatim instance allows at most 1 request per second and requires an identifying User-Agent; the Wikipedia API also requires one and applies rate limits (requests are retried, honoring `Retry-After` on HTTP 429). With many concurrent users, requests must be throttled and cached (e.g. in Redis), or moved to a self-hosted or commercial geocoder.
4.  **Location metadata on upload**: some mobile browsers and OS photo pickers strip location data from photos before uploading them. Those photos reach the server without GPS and rely on position propagation (Step 2.3).
5.  **AI costs**: since AI is configured server-side, every enrichment and narration call is billed to the operator; per-user limits are therefore needed (Section 7.1).

---

## 7. User Accounts & Future Evolution

### 7.1 User Accounts
The service is available only to registered users.
* **Registration and login**: apart from the sign-up and login pages, every page and every API call requires an authenticated session, stored in Redis (Section 4.1).
* **Tour ownership**: each tour belongs to the user who created it; the data model is extended with a `users` table and a `tours.id_user` foreign key. The homepage lists the user's tours, which can be reopened at any time in the Storyboard Editor or in the player.
* **Quotas**: per-user limits on photos per tour, storage space and AI calls, to keep the operator's costs under control.

### 7.2 Future Evolution: Tour Hosting
Users may publish a finished tour, playable at a public URL served by the platform, as an alternative to the package export. Each tour has a visibility level (private, link-only, public); published photos are resized and stripped of their EXIF metadata, so that the GPS coordinates of the originals are not exposed.

---

## 8. Development Utility: Fill Settings

The script `scripts/fill_settings.py` is a development-only helper to quickly populate the AI settings from terminal prompts.

Run it from the project root as a Python module:

```bash
python -m scripts.fill_settings
```

Use module execution (`-m`) instead of running the file directly, so Python resolves package imports correctly (for example `from app.settings import ...`).

## License

GNU GPLv3
