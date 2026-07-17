# Technical Specifications Document (V7): TripTour

This document outlines the development specifications for **TripTour**, a *100% offline, private, and local* desktop application that transforms unstructured collections of photos into narrated virtual tours. The application utilizes a user interface developed in **Svelte (SPA)** hosted inside a **PySide6 (Qt)** container, communicating via a bidirectional IPC bridge (`QWebChannel`). 

All intelligent processing — duplicate filtering, sequential visual tagging, clustering, and final narrative synthesis — runs entirely locally on the user's machine using the Python **Hugging Face `transformers`** library with aggressive memory optimizations.

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
[ Homepage ] ──► [ Load Previous Tour ]
     │
     └──► [ New Tour ]
              │
              ├──► Select files/folders, Language, and Tour Name (PySide6 Dialog & Svelte)
              │
              ├──► PHASE 0: Preventive Sorting (Date/Time or Filename)
              │
              ├──► PHASE 1: Filtering and De-duplication (CLIP + Laplacian)
              │
              ├──► PHASE 2: Photo Enrichment (EXIF + Local VLM with Context & Tour Name)
              │
              ├──► PHASE 3: Clustering and Storyboard (Time/Space)
              │
              ├──► PHASE 4: Storyboard Editor (Svelte UI - Manual Edits)
              │
              ├──► PHASE 5: Script Generation (Local LLM + Tour Name + Inline Tags)
              │
              └──► [ HTML Player & Package Export ]
```

### Phase 0: Startup, Initialization, and Preventive Sorting
1.  **Homepage**: The user can resume a previously saved tour from the local SQLite database or start a new one.
2.  **Initialization & Selection**:
    * The user selects files or a folder using native PySide6 dialogs (`QFileDialog`). Imported photos may be in a completely unstructured order.
    * The user selects the language for the tour.
    * **Tour Name (New)**: The user inputs a descriptive title for the tour (e.g., *"Vatican Museums Visit"* or *"Tuscany Holidays 2026"*). This name is stored in the database and **becomes a crucial piece of metadata** passed to the AI models in subsequent stages to guide their understanding of historical, geographical, and artistic contexts.
3.  **Preventive Sorting**: Before any analysis is performed, the backend sorts the photos chronologically:
    * It attempts to extract the date and time of capture from the EXIF metadata (`DateTimeOriginal`).
    * If one or more photos lack temporal metadata, the system falls back to sorting them alphabetically by filename (e.g., `IMG_001.jpg`, `IMG_002.jpg`).

### Phase 1: Filtering & Duplicate Removal (Deduplication)
Using the newly sorted sequence, to prevent visual redundancy (such as multiple shots of the same subject):
1.  The backend loads a lightweight local image embedding model (e.g., `laion/CLIP-ViT-B-32-laion2B-s34B-b79K` via Transformers).
2.  It generates vectors (embeddings) for each photo.
3.  It calculates the cosine similarity between chronologically adjacent photos.
4.  **Duplicate Resolution**: If two or more adjacent photos exceed a predefined similarity threshold (e.g., > 0.85):
    * The **Laplacian variance** is calculated for each photo to measure its sharpness (blurriness).
    * The sharpest photo (highest variance) is retained; the others are removed from the active tour sequence or hidden.

```python
import cv2

def calculate_sharpness(image_path: str) -> float:
    # Load the image in grayscale to calculate blur
    image = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if image is None:
        return 0.0
    # Returns the Laplacian variance (higher = sharper)
    return cv2.Laplacian(image, cv2.CV_64F).var()
```

### Phase 2: Photo Enrichment (Triple Context Window + Tour Name)
For each remaining photo, the backend initiates the analysis and tagging process. To prevent isolated or inaccurate descriptions of close-up details, the backend utilizes a **sliding triple-context window** enriched by the global tour context:

1.  **EXIF Metadata**: Extraction of GPS coordinates, if present.
2.  **Reverse Geocoding**: Conversion of GPS coordinates into human-readable addresses or points of interest. If GPS is missing, the photo is temporarily marked as "location unknown".
3.  **Contextual Description Generation (VLM)**: 
    * To analyze the current image N, the Python backend passes to the local Vision-Language Model (VLM, e.g., `Moondream2` or `Qwen2-VL-2B` loaded via `transformers`):
        * The **Current Image N**.
        * The **Previous Image N-1** coupled with its **already generated description** (if N > 1).
        * The **Next Image N+1** as pure visual context (if N < total number of photos).
        * The **Tour Name** provided by the user.
    * The prompt instructs the model to recognize logical continuity and to use the tour title to deduce details that might otherwise not be obvious:
      > *"The user is currently on a tour titled: **[Tour Name]**. I am showing you the current image (Photo B), embedded within this chronological sequence. I am also providing the previous photo (Photo A), described as '[Description A]', and the next photo (Photo C). Describe what Photo B depicts, taking into account the context of the tour '[Tour Name]' and the adjacent photos. If Photo B shows a close-up detail of a subject visible in Photo A or leading up to Photo C, explicitly state this in the description (e.g., 'This is a close-up detail of the left column of the church portico we just saw...')."*

### Phase 3: Logical Grouping (Clustering & Storyboard)
The backend organizes the sorted sequence of photos into logical "Sections":
1.  **Clustering Algorithm**: Groups photos together if they were taken in the same place (within a radius of ~100 meters) and within a continuous, narrow time window (e.g., within a few minutes of each other).
2.  Each group defines a **Tour Section** (e.g., "Monumental Entrance", "Altar and Interiors").
3.  A preliminary automatic section description is generated by merging the tags and contextualized descriptions of its constituent photos.

### Phase 4: Storyboard Editor (User Interface)
The Svelte frontend receives the storyboard structure from the backend and displays an interactive UI:
* Photos are visually grouped into the calculated sections/stages.
* **GPS / Location Error Management**: Photos lacking coordinates are highlighted in red. The user can manually type a location for the stage or drag and drop photos into an existing stage.
* **Full Interactivity**: Users can drag photos to reorder them across sections, create new empty sections, rename them, delete unwanted shots, or manually edit descriptions.
* **Bulk Editing**: Ability to select multiple photos at once to assign them the same location or tags in a single click.
* **Recalculate**: A button allows users to re-run Phase 3 if they want to reset automatic grouping after making manual adjustments to order or metadata.

### Phase 5: Local Narrative Synthesis and Temporal Tagging
Once the user confirms the edited storyboard:
1.  The Python backend unloads the Phase 2 local VLM from memory (if needed) and initializes a **local text-only LLM** (e.g., `meta-llama/Meta-Llama-3-8B-Instruct` or `Qwen/Qwen2.5-3B-Instruct` quantized to 4-bit) via `transformers`.
2.  All storyboard information (locations, detailed and contextualized descriptions, chronological order) along with the **Tour Name** and **Target Language** are bundled and sent to the local LLM.
3.  The LLM processes this structural text and the tour name (e.g., *"Rome Vacation 2026"*) and generates the final narrative script directly in the target language. This allows the model to draw historical or stylistic inferences thanks to the provided title.
4.  **Synchronization**: The LLM embeds special inline tags into the text to indicate exactly when the interface should transition to the next photo.

* *Example of LLM output:*
    > `[photo_001.jpg] Welcome to Palazzo Vecchio, one of the iconic symbols of Florence. [photo_002.jpg] As we approach the main portal, the majestic copy of Michelangelo's David stands out. [photo_003.jpg] If we look closely at the carved stone details on the left...`

---

## 3. AI Model Architecture & Memory Management (Transformers)

To run both the vision model and the text LLM on consumer-grade computers (e.g., a PC with 16GB RAM or a GPU with 6/8GB VRAM), the backend implements **lazy loading** and **4-bit quantization** using the `bitsandbytes` library.

### Memory Optimization and Offloading
During the app flow, we never keep both models in RAM/VRAM simultaneously to prevent system memory saturation:
1.  **Phase 1 (Deduplication)**: Load CLIP -> Extract Embeddings -> Offload CLIP.
2.  **Phase 2 (Enrichment)**: Load VLM (Moondream/Qwen) -> Analyze Photos with Triple Window -> Offload VLM.
3.  **Phase 5 (Narrative Synthesis)**: Load LLM (Llama-3-8B or Qwen-2.5-3B) -> Generate Script -> Offload LLM.

### Conceptual Load Code with 4-bit Quantization
```python
import gc
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

class LocalAIEngine:
    def __init__(self):
        self.model = None
        self.tokenizer = None
        
        # 4-bit quantization configuration for RAM/VRAM savings
        self.bnb_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_use_double_quant=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_compute_dtype=torch.float16
        )

    def load_text_llm(self, model_id="Qwen/Qwen2.5-3B-Instruct"):
        """Loads the text LLM for Phase 5."""
        self.free_memory()
        
        self.tokenizer = AutoTokenizer.from_pretrained(model_id)
        self.model = AutoModelForCausalLM.from_pretrained(
            model_id,
            quantization_config=self.bnb_config,
            device_map="auto"
        )

    def free_memory(self):
        """Frees RAM/VRAM by deleting unused models and tokenizers."""
        if self.model is not None:
            del self.model
            self.model = None
        if self.tokenizer is not None:
            del self.tokenizer
            self.tokenizer = None
        
        # Force Python garbage collection and empty PyTorch cache
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
```

---

## 4. SQLite Database Management & Persistent Path

To ensure data persistence and portability (preventing data loss if the application binary is updated or moved), the database file `triptour.db` **is not saved next to the executable**. Instead, it is written to a dedicated system application data folder belonging to the user, handled in a cross-platform manner.

### Dynamic Path Resolution in Python
The Python backend calculates the appropriate path at application startup. Standard paths for each operating system are used:
* **Windows**: `%APPDATA%/TripTour/triptour.db`
* **macOS**: `~/Library/Application Support/TripTour/triptour.db`
* **Linux**: `~/.local/share/triptour/triptour.db`

```python
import os
import sys

def get_db_path() -> str:
    """Returns the absolute, persistent path for the SQLite database."""
    app_name = "TripTour"
    
    if sys.platform == "win32":
        # Windows: AppData/Roaming
        base_dir = os.environ.get("APPDATA") or os.path.expanduser("~/AppData/Roaming")
    elif sys.platform == "darwin":
        # macOS: Library/Application Support
        base_dir = os.path.expanduser("~/Library/Application Support")
    else:
        # Linux and other Unix-likes: .local/share (XDG)
        base_dir = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    
    # Create application directory if it doesn't exist
    app_dir = os.path.join(base_dir, app_name)
    os.makedirs(app_dir, exist_ok=True)
    
    return os.path.join(app_dir, "triptour.db")
```

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
    latitude REAL,                -- Latitude (EXIF)
    longitude REAL,               -- Longitude (EXIF)
    local_tags TEXT,              -- JSON tags extracted by local VLM (Phase 2)
    local_description TEXT,       -- Contextualized description of the photo (Phase 2)
    display_order INTEGER,        -- Calculated or manual order of display
    FOREIGN KEY(tour_id) REFERENCES tours(id) ON DELETE CASCADE
);

-- Generated Stages/Scenes Table
CREATE TABLE scenes (
    id TEXT PRIMARY KEY,
    tour_id TEXT NOT NULL,
    title TEXT NOT NULL,          -- Scene title (e.g. "The Main Altar")
    narrative_text TEXT,          -- Final script text generated by the local LLM
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
