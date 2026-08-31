# Technical Specifications Document (V8): TripTour

This document outlines the development specifications for **TripTour**, a desktop application that transforms unstructured collections of photos into narrated virtual tours. The application utilizes a user interface developed in **Svelte (SPA)** hosted inside a **PySide6 (Qt)** container, communicating via a bidirectional IPC bridge (`QWebChannel`).

TripTour uses a **hybrid AI architecture**:
- **Local Transformers** are used only for image embeddings (deduplication and clustering support).
- **LangChain/LangGraph + OpenAI-compatible APIs** are used for multimodal enrichment and final narrative synthesis.
- The user configures endpoint URL, API key, and model choices (vision model + text model) at first launch and later in Settings.

---

## 1. System Architecture & IPC Bridge

The application combines the performance of a native Python backend with the interactivity of a modern Svelte frontend.

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

* **PySide6 `QWebEngineView`**: Renders the Svelte SPA compiled into a lightweight local bundle.
* **`QWebChannel`**: Exposes a Python controller object to the global JavaScript context of the webpage. The Svelte frontend can invoke Python methods asynchronously (e.g., `pybridge.select_folder().then(...)`).

---

## 2. User Flow & Detailed Processing Pipeline

```
[ App Start ]
    │
    ├──► [ AI Setup Required? ] -- yes --> [ First-Run AI Setup ]
    │                                         (Base URL + API Key + Model Selection)
    │
    └──► no / completed
            │
            └──► [ Homepage ] ──► [ Load Previous Tour ]
                      │
                      └──► [ New Tour ]
                              │
                              ├──► Select files/folders, Language, and Tour Name (PySide6 Dialog & Svelte)
                              │
                              ├──► PHASE 0: Multi-Level Sorting (EXIF → Regex → mtime → Import Order)
                              │
                              ├──► PHASE 1: Filtering and De-duplication (CLIP + Laplacian)
                              │
                              ├──► PHASE 2: Anchor-Based Enrichment (Anchor Points + Context Propagation + Remote Vision Model)
                              │
                              ├──► PHASE 3: Hybrid Clustering (Space-Time / Time+Visual / Semantic Change Detection)
                              │
                              ├──► PHASE 4: Storyboard Editor (Svelte UI - Manual Edits)
                              │
                              ├──► PHASE 5: Script Generation (Remote Text Model + Tour Name + Inline Tags)
                              │
                              └──► [ HTML Player & Package Export ]
```

### Phase 0: Startup, Initialization, and Multi-Level Sorting (Sanitization)
1.  **Pre-Homepage Configuration Gate**: At startup, before the homepage is shown and before the user can load/start any tour, TripTour checks whether AI configuration exists.
2.  **First-Launch AI Configuration Wizard**: On first run (or whenever config is missing), TripTour opens a required setup flow where the user provides:
    * **Base URL** of an OpenAI-compatible endpoint (examples: OpenAI, OpenRouter, local vLLM, Ollama-compatible gateway).
    * **API Key** (or equivalent token) for the selected endpoint.
    * **Enrichment Model** (must support image input / vision).
    * **Narrative Model** (text model for final tour generation).
    
    Configuration is validated with a lightweight test call and then persisted locally using **PySide6 QSettings**. The same settings can be changed later from a dedicated **Settings > AI Providers** section.
3.  **Homepage**: After configuration is valid, the user can resume a previously saved tour from the local SQLite database or start a new one.
4.  **Initialization & Selection**:
    * The user selects files or a folder using native PySide6 dialogs (`QFileDialog`). Imported photos may be in a completely unstructured order.
    * The user selects the language for the tour.
    * **Tour Name (New)**: The user inputs a descriptive title for the tour (e.g., *"Vatican Museums Visit"* or *"Tuscany Holidays 2026"*). This name is stored in the database and **becomes a crucial piece of metadata** passed to the AI models in subsequent stages to guide their understanding of historical, geographical, and artistic contexts.
5.  **Multi-Level Sorting Strategy**: Before any analysis is performed, the backend applies a cascading sanitization pipeline to establish the best possible chronological order. Each photo is timestamped using the first available source in the following priority chain:

    | Priority | Source | Description |
    |----------|--------|-------------|
    | **1 (Highest)** | `EXIF DateTimeOriginal` | Extracted from the image's internal EXIF metadata — the true capture timestamp. |
    | **2** | **Regex Parsing on Filename** | A regex scans the filename for embedded timestamps (e.g., `IMG_20260725_143052.jpg`, `2026-07-25 14.30.45.png`, `VID-20260725-WA0001.jpeg`). Common patterns include `YYYYMMDD_HHMMSS`, `YYYY-MM-DD HH.MM.SS`, and WhatsApp-style `YYYYMMDD` prefixes. |
    | **3** | **Filesystem Modification Time (`mtime`/`ctime`)** | If no timestamp can be extracted from EXIF or the filename, the backend falls back to the file's last modification time (or creation time on supported filesystems). |
    | **4 (Lowest)** | **Native Import Order** | If all previous methods fail (e.g., files with generic names and corrupted metadata), the original order in which files were selected/imported is preserved as the last-resort fallback. |

    *Each photo records a `sort_source` field in the database indicating which priority level was used, enabling transparency and potential manual correction in the Storyboard Editor.*

### Phase 1: Filtering & Duplicate Removal (Deduplication)
Using the newly sorted sequence, to prevent visual redundancy (such as multiple shots of the same subject):
1.  The backend loads a lightweight local image embedding model (e.g., `laion/CLIP-ViT-B-32-laion2B-s34B-b79K` via Transformers).
2.  It generates vectors (embeddings) for each photo. **These embeddings are persisted** (stored in the `embedding` column of the `media` table) for reuse in Phase 2.3 (CLIP visual affinity tie-breaking) and Phase 3 (Time+Visual and Semantic Change Detection clustering), avoiding redundant model reloads.
3.  It calculates the cosine similarity between chronologically adjacent photos.
4.  **Duplicate Resolution**: If two or more adjacent photos exceed a predefined similarity threshold (e.g., > 0.85):
    * The **Laplacian variance** is calculated for each photo to measure its sharpness (blurriness).
    * The sharpest photo (highest variance) is retained; the others are removed from the active tour sequence or hidden.

### Phase 2: Anchor-Based Enrichment (Anchor Points + Context Propagation + Vision Model)
The enrichment phase follows an **Anchor-Based** strategy: photos with complete metadata (GPS + timestamp) serve as **Anchor Points**, and their contextual information is propagated forward and backward to neighboring photos that lack metadata. This ensures maximum coverage even when GPS or timestamps are partial or absent.

#### Step 2.1: Classification and Anchor Identification
Each photo in the sorted sequence is classified based on its metadata completeness:

| Class | GPS | Timestamp | Role |
|-------|-----|-----------|------|
| **Anchor (A)** | ✓ Present | ✓ Present | Reference point for geolocation and temporal context |
| **Time-Only (T)** | ✗ Missing | ✓ Present | Positioned chronologically; location inherited from nearest anchors |
| **Bare (B)** | ✗ Missing | ✗ Missing | No metadata; relies entirely on visual affinity to nearest anchors |

#### Step 2.2: EXIF Extraction & Reverse Geocoding (Anchors Only)
For **Anchor photos only**, the backend performs full metadata extraction:
1.  **EXIF Metadata**: Extraction of GPS coordinates (`GPSLatitude`, `GPSLongitude`, `GPSLatitudeRef`, `GPSLongitudeRef`).
2.  **Reverse Geocoding (Nominatim)**: Coordinates are converted into human-readable location data (city, region, country) using OpenStreetMap Nominatim (`https://nominatim.openstreetmap.org/reverse`). No fallback provider is defined in this version.

#### Step 2.3: Context Propagation (Forward & Backward)
Once Anchors are identified and enriched, context is propagated to non-anchor photos:

1.  **Forward Pass**: For each photo without GPS, the backend walks forward through the sorted sequence to find the nearest Anchor and inherits its geocoded location. This models the realistic assumption that a photo taken shortly after a known location is likely still at that location.
2.  **Backward Pass**: Similarly, the backend walks backward to propagate location context from later Anchors to earlier photos that precede them.
3.  **Visual Affinity Tie-Breaking**: When a Bare photo (Class B, no metadata at all) sits between two Anchors with *different* locations, the system computes the **CLIP cosine similarity** between the Bare photo and each candidate Anchor. The Bare photo inherits the location of the Anchor with the highest visual similarity.

#### Step 2.4: Contextual Description Generation (LangChain/LangGraph + Vision Model)
For each photo (regardless of class), the backend generates a descriptive tag using the configured **remote multimodal model** with the **sliding triple-context window**, now enriched by the propagated Anchor context.

* To analyze the current image N, the Python backend builds a LangChain/LangGraph call to the configured OpenAI-compatible chat-completions endpoint, passing:
    * The **Current Image N**.
    * The **Previous Image N-1** coupled with its **already generated description** (if N > 1).
    * The **Next Image N+1** as pure visual context (if N < total number of photos).
    * The **Tour Name** provided by the user.
    * The **Inherited Location** (from Anchor propagation or direct GPS geocoding).
* The selected enrichment model **must support images**. The setup wizard and Settings validation reject non-vision models for this role.
* The prompt instructs the model to recognize logical continuity, use the location context, and leverage the tour title:
  > *"The user is currently on a tour titled: **[Tour Name]**. The estimated location is: **[Location]**. I am showing you the current image (Photo B), embedded within this chronological sequence. I am also providing the previous photo (Photo A), described as '[Description A]', and the next photo (Photo C). Describe what Photo B depicts, taking into account the tour context '[Tour Name]', the location '[Location]', and the adjacent photos. If Photo B shows a close-up detail of a subject visible in Photo A or leading up to Photo C, explicitly state this in the description (e.g., 'This is a close-up detail of the left column of the church portico we just saw...')."*
* **Tool Usage Policy (LangGraph)**: tools are not toggled individually in settings. They are automatically available when execution conditions are met. Example: Wikipedia article/context retrieval is invoked only when internet connectivity is available, so the model receives broader factual context to interpret what it is seeing.

### Phase 3: Hybrid Clustering & Storyboard Generation
The backend organizes the sorted sequence of photos into logical **Sections/Scenes** using a **Hybrid Clustering** strategy. Because real-world photo collections have varying levels of metadata completeness, the system applies the most appropriate clustering algorithm on a per-photo basis, falling back gracefully when GPS or timestamps are unavailable.

#### Clustering Strategy Hierarchy

The backend attempts each strategy in priority order per adjacent photo pair. The first strategy with sufficient data for both photos is used:

| Priority | Strategy | Requirements | Method |
|----------|----------|-------------|--------|
| **1** | **Space-Time Clustering** | Both photos have GPS + Timestamp | ~100m radius, ~15 min sliding window |
| **2** | **Time + Visual Clustering** | Both photos have Timestamp (no GPS) | Temporal window + CLIP cosine similarity |
| **3** | **Semantic Change Detection** | No GPS, no Timestamp (Bare photos) | CLIP cosine similarity drops between adjacent photos |

#### Strategy 1: Space-Time Clustering (GPS + Timestamp)
The ideal clustering method. Two adjacent photos are grouped into the same section if:
- Their capture times are within **15 minutes** of each other.
- Their GPS coordinates are within **~100 meters** of each other (using the Haversine formula).

A new section is created when either the temporal gap exceeds the threshold or the spatial distance indicates a significant location change.

#### Strategy 2: Time + Visual Clustering (Timestamp Only, No GPS)
When photos have timestamps but lack GPS coordinates, the system combines temporal proximity with CLIP visual similarity:
- Two adjacent photos are grouped if their time delta is within **30 minutes**.
- If the time delta is borderline (between 15–120 minutes), a **CLIP cosine similarity check** acts as a tie-breaker: photos with high visual similarity (> 0.7) are kept together even with a longer temporal gap (e.g., interior shots of the same museum spread over time), while visually dissimilar photos trigger a section break.

#### Strategy 3: Semantic Change Detection (No GPS, No Timestamp — Bare Photos)
When photos have neither GPS nor reliable timestamps, clustering relies purely on visual semantics. The system computes CLIP embeddings for all adjacent photo pairs and detects **Semantic Change Points** — positions where the cosine similarity drops sharply, indicating a likely scene/chapter transition.

The algorithm:
1. Computes the CLIP cosine similarity for every adjacent pair $(i, i+1)$.
2. Identifies **local minima** in the similarity curve where $\text{sim}(i, i+1) < \mu - k \cdot \sigma$ (i.e., similarity falls significantly below the rolling mean).
3. Places section boundaries at these detected change points.

#### Unified Hybrid Clustering Entry Point
The top-level clustering function traverses the sorted photo sequence and automatically selects the best strategy based on the available metadata:
- If more than 50% of photos have GPS coordinates → **Space-Time Clustering** (Strategy 1).
- If more than 50% have timestamps (but not GPS) → **Time + Visual Clustering** (Strategy 2).
- Otherwise → **Semantic Change Detection** (Strategy 3).

> **Plug & Play Philosophy**: This hybrid approach embodies the core design principle of TripTour — the user simply loads their photos, and the system automatically does the best possible job. The Storyboard Editor (Phase 4) then becomes a pleasant refining experience rather than a forced correction step.

#### Section Metadata Generation
After clustering, each section is automatically enriched:
1.  A **section title** is synthesized from the most frequent tags and the dominant location (e.g., "Monumental Entrance — Piazza del Duomo").
2.  A **preliminary auto-description** is generated by merging the contextualized descriptions of the section's constituent photos.
3.  Photos without inherited coordinates are flagged in the UI (red highlight) for manual correction in Phase 4.

### Phase 4: Storyboard Editor (User Interface)
The Svelte frontend receives the storyboard structure from the backend and displays an interactive UI:
* Photos are visually grouped into the calculated sections/stages.
* **Anchor & Metadata Transparency**: Each photo displays a small badge indicating its classification (🟢 Anchor / 🟡 Time-Only / 🔴 Bare) and the sort source used in Phase 0 (EXIF, filename regex, filesystem, or import order). This lets users instantly understand which photos have reliable metadata and which were positioned heuristically.
* **GPS / Location Error Management**: Photos lacking coordinates (Bare and Time-Only classes with unresolved inherited locations) are highlighted in red. The user can manually type a location for the stage or drag and drop photos into an existing stage.
* **Full Interactivity**: Users can drag photos to reorder them across sections, create new empty sections, rename them, delete unwanted shots, or manually edit descriptions and inherited locations.
* **Bulk Editing**: Ability to select multiple photos at once to assign them the same location or tags in a single click.
* **Recalculate**: A button allows users to re-run Phase 3 (Hybrid Clustering) if they want to reset automatic grouping after making manual adjustments to order or metadata.

### Phase 5: Narrative Synthesis and Temporal Tagging (LangChain/LangGraph)
Once the user confirms the edited storyboard:
1.  The Python backend builds a generation pipeline with LangChain/LangGraph using the configured **narrative model** (text-focused).
2.  All storyboard information (locations, detailed and contextualized descriptions, chronological order) along with the **Tour Name** and **Target Language** are bundled and sent to the endpoint selected by the user.
3.  The model processes this structural text and the tour name (e.g., *"Rome Vacation 2026"*) and generates the final narrative script directly in the target language.
4.  **Synchronization**: The model embeds special inline tags into the text to indicate exactly when the interface should transition to the next photo.

* *Example of LLM output:*
    > `[photo_001.jpg] Welcome to Palazzo Vecchio, one of the iconic symbols of Florence. [photo_002.jpg] As we approach the main portal, the majestic copy of Michelangelo's David stands out. [photo_003.jpg] If we look closely at the carved stone details on the left...`

---

## 3. AI Orchestration Architecture

TripTour separates local vision indexing from model orchestration:

### 3.1 Local Embedding Layer (Transformers)
Only embedding workloads run through local Hugging Face `transformers` models:
1.  **Phase 1 (Deduplication)**: CLIP embeddings + Laplacian quality scoring.
2.  **Phase 2.3 (Tie-Breaking)**: Reuse persisted CLIP embeddings for anchor disambiguation.
3.  **Phase 3 (Clustering)**: Reuse persisted CLIP embeddings for Time+Visual and Semantic Change Detection.

### 3.2 Remote Inference Layer (LangChain/LangGraph)
All generative/model-orchestration tasks run through an OpenAI-compatible client abstraction:
1.  **Multimodal Enrichment Model**: Used in Phase 2, must accept image inputs.
2.  **Narrative Generation Model**: Used in Phase 5, optimized for long-form text output.
3.  **Endpoint Agnosticism**: Any compatible endpoint can be configured (OpenAI, OpenRouter, self-hosted vLLM gateways, Ollama-compatible bridges, etc.).

### 3.3 First-Run and Settings Lifecycle
1.  If AI configuration is missing, startup is redirected to a mandatory setup screen.
2.  The app stores endpoint URL, encrypted/obfuscated API credentials, and model identifiers via **PySide6 QSettings**.
3.  A dedicated settings panel allows updating provider/model mappings at any time.
4.  Validation rules enforce that the enrichment model is vision-capable.

---

## 4. SQLite Database Management & Persistent Path

To ensure data persistence and portability (preventing data loss if the application binary is updated or moved), the database file `triptour.db` **is not saved next to the executable**. Instead, it is written to a dedicated system application data folder belonging to the user, handled in a cross-platform manner.

### Dynamic Path Resolution in Python
The Python backend calculates the appropriate path at application startup. Standard paths for each operating system are used:
* **Windows**: `%APPDATA%/TripTour/triptour.db`
* **macOS**: `~/Library/Application Support/TripTour/triptour.db`
* **Linux**: `~/.local/share/triptour/triptour.db`

### Local Database Schema

```sql
-- Virtual Tours Table
CREATE TABLE tours (
    id TEXT PRIMARY KEY,          -- Unique UUID for the tour
    title TEXT NOT NULL,          -- Title of the tour (e.g. "Rome Vacation")
    language TEXT NOT NULL,       -- Selected language for the tour (e.g. "it", "en")
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Media/Photos Table
CREATE TABLE media (
    id TEXT PRIMARY KEY,          -- Unique UUID or file hash
    tour_id TEXT NOT NULL,        -- Foreign key linking to the tour
    original_path TEXT NOT NULL,  -- Original path on disk
    cached_path TEXT NOT NULL,    -- Path to the optimized image in application cache
    taken_at TIMESTAMP,           -- Capture timestamp (EXIF or fallback)
    sort_source TEXT,             -- Source of the timestamp (Phase 0): 'EXIF DateTimeOriginal' | 'Filename Regex' | 'Filesystem mtime' | 'Import Order Fallback'
    sort_priority INTEGER,        -- Numeric priority of the sort source (1-4), for transparency in the UI
    latitude REAL,                -- Latitude (EXIF) — only for Anchor-class photos
    longitude REAL,               -- Longitude (EXIF) — only for Anchor-class photos
    location_name TEXT,           -- Human-readable place name from configured reverse geocoding provider
    location_city TEXT,           -- City name
    location_region TEXT,         -- Region/State name
    location_country TEXT,        -- Country code (ISO 3166-1 alpha-2)
    wikipedia_context TEXT,       -- Optional contextual content extracted from Wikipedia articles, nullable
    inherited_location TEXT,      -- JSON: location propagated from nearest Anchor (Phase 2.3), NULL for Anchors themselves
    anchor_source TEXT,           -- Propagation direction: 'forward' | 'backward' | 'clip_tie_break' | NULL (for Anchor photos or unassigned)
    anchor_class TEXT,            -- Photo class (Phase 2.1): 'A' (Anchor) | 'T' (Time-Only) | 'B' (Bare)
    embedding BLOB,               -- CLIP embedding vector (binary, stored for Phase 1 dedup & Phase 3 clustering reuse)
    local_tags TEXT,              -- JSON tags extracted by configured multimodal model (Phase 2)
    local_description TEXT,       -- Contextualized description of the photo (Phase 2)
    display_order INTEGER,        -- Calculated or manual order of display
    FOREIGN KEY(tour_id) REFERENCES tours(id) ON DELETE CASCADE
);

-- Generated Stages/Scenes Table
CREATE TABLE scenes (
    id TEXT PRIMARY KEY,
    tour_id TEXT NOT NULL,
    title TEXT NOT NULL,          -- Scene title (e.g. "The Main Altar")
    narrative_text TEXT,          -- Final script text generated by the configured narrative model
    audio_path TEXT,              -- Path to pre-generated offline TTS audio (optional)
    display_order INTEGER,
    FOREIGN KEY(tour_id) REFERENCES tours(id) ON DELETE CASCADE
);

-- Junction Table linking Photos to Scenes
CREATE TABLE scene_media (
    scene_id TEXT,
    media_id TEXT,
    PRIMARY KEY (scene_id, media_id),
    FOREIGN KEY(scene_id) REFERENCES scenes(id) ON DELETE CASCADE,
    FOREIGN KEY(media_id) REFERENCES media(id) ON DELETE CASCADE
);
```

---

## 5. Generation and Structure of the Tour Package

Upon completion, the tour is exported to a structured folder on the user's local disk, designed to be self-contained, interactive, and easily playable on any browser.

### Exported Folder Structure:
```text
[Tour_Name]/
├── index.html          # Interactive player (HTML5 + CSS + Compiled JS)
├── tour_data.json      # Narrative text, image mapping, and metadata
├── css/
│   └── style.css       # Layout styles and transitions (cinematic Ken Burns effect)
└── images/
    ├── photo_001.jpg   # Optimized tour images
    ├── photo_002.jpg
    └── ...
```

### Exported Player (`index.html`) Features:
1.  **Narrated Reading (TTS)**: Leverages the browser's native, free, and offline **Web Speech API** to read the active scene's text aloud in the user's chosen language.
2.  **Synchronized Photo Transitions**: A lightweight JS parser scans the narrative text for tags like `[photo_001.jpg]`. As the Speech Synthesis engine advances through the spoken sentences, it triggers visual transitions to keep the active photo in perfect sync.
3.  **Cinematic Transitions (Ken Burns Effect)**: Photos are displayed full-screen with smooth, CSS-driven pan and zoom animations, simulating a high-quality documentary. This maintains viewer engagement without sudden map jumps or coordinate discrepancies.

---

## 6. Connectivity and Compatibility Notes

1.  TripTour is **not full offline by design** in this version because enrichment and narrative generation rely on a user-configured OpenAI-compatible endpoint.
2.  Local-only deployments are still possible when the user points the app to a self-hosted/local endpoint (for example a local gateway around Ollama or vLLM).
3.  The app is endpoint-agnostic: compatibility is based on OpenAI-style API behavior (chat/completions, multimodal support for enrichment model).

---

## 7. Development Utility: Fill Settings

The script `scripts/fill_settings.py` is a development-only helper to quickly populate application settings from terminal prompts.

Run it from the project root as a Python module:

```bash
python -m scripts.fill_settings
```

Use module execution (`-m`) instead of running the file directly, so Python resolves package imports correctly (for example `from app.settings import ...`).

## License

GNU GPLv3
