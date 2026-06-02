# ComfyWeave — Installation & Usage

## What ComfyWeave Lets You Do

- Connect to any running ComfyUI instance (local or remote) via its HTTP + WebSocket API
- Load an API-format workflow JSON **or a ComfyUI-generated PNG** and edit all recognised node inputs via a form UI
- Assign **multiple values** to any field to auto-generate every permutation as a batch
- Run a **Multi-LoRA sweep** — one job per LoRA, submitted automatically
- Watch live step progress and latent preview images during generation
- Browse generated images in a scrollable grid with metadata overlays; zoom/pan in a detail view with keyboard navigation
- Extract the embedded workflow from any generated image and reload it with one click
- Copy images to the clipboard directly from the detail view
- Stop, clear, retry, and batch-cancel jobs without leaving the app
- Save reusable text blocks per prompt field for prompt snippets you use repeatedly
- Persist all settings, field overrides, and window layout between sessions

---

## Prerequisites

- **Python 3.10 or later** (tested on 3.13)
- A running [ComfyUI](https://github.com/comfyanonymous/ComfyUI) instance (default: `http://127.0.0.1:8188`)
- Windows, macOS, or Linux with a display

---

## Installation

### Method A — Recommended (conda environment)

The repository ships with a pre-configured conda environment in `.conda/`. If you have [Miniconda](https://docs.conda.io/en/latest/miniconda.html) or Anaconda:

```bash
git clone https://github.com/AdamMoses-GitHub/ComfyWeave.git
cd ComfyWeave

# Activate the bundled env
conda activate ./.conda

# Install Python dependencies into it
pip install -r requirements.txt --no-user
```

Run:
```bash
.conda/python.exe main.py          # Windows
# or
.conda/bin/python main.py          # macOS / Linux
```

---

### Method B — Quick (pip + virtualenv)

```bash
git clone https://github.com/AdamMoses-GitHub/ComfyWeave.git
cd ComfyWeave

python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python main.py
```

> **Windows note:** If you see a `DLL load failed` error on `PySide6`, ensure you are using `PySide6 6.8.x`. The `requirements.txt` already pins the safe range (`>=6.7.0,<6.9.0`).

---

## Running the App

```bash
python main.py
```

### Environment variable overrides (session-only, non-persistent)

| Variable | Effect | Example |
|---|---|---|
| `COMFYUI_SERVER` | Override the server URL | `http://192.168.1.50:8188` |
| `COMFYUI_AUTO_CONNECT` | Connect immediately on startup | `1` |
| `COMFYUI_THEME` | Force a theme | `dark` or `light` |

```bash
COMFYUI_SERVER=http://192.168.1.50:8188 COMFYUI_AUTO_CONNECT=1 python main.py
```

---

## Usage Workflows

### 1. Single Workflow Run

**Scenario:** You finished a ComfyUI workflow and want to run it with tweaked settings without opening the browser.

1. Start ComfyUI, then start ComfyWeave.
2. In the connection bar, confirm the server URL and click **Connect**.
3. Load your workflow using one of three methods:
   - **Load Workflow…** — select an API-format `.json` file.
     > The file must be saved via ComfyUI → Settings → Enable Dev Mode → *Save (API Format)*. Standard workflow files are rejected with a clear error message.
   - **From Image…** — select any ComfyUI-generated PNG; the embedded workflow is extracted automatically.
   - **Load Workflow** button in the image detail view — one click re-loads the workflow from whichever image is currently open (see [Workflow #4](#4-image-viewer--export) below).
4. The left panel populates with editable nodes (KSampler, CLIP text encoders, checkpoint loader, etc.). Edit any values you want.
5. Set **Batch Count** (how many times to repeat this exact set of inputs) and click **Generate**.
6. Watch progress in the progress bar at the bottom. Generated images appear in the image grid on the right.

---

### 2. Multi-Value Batch Sweep

**Scenario:** You want to compare `euler` vs `dpm_2` vs `dpm_2_ancestral` samplers across 4 different CFG values — 48 total jobs — without touching a single node.

1. Connect and load your workflow (see Workflow #1 above).
2. In the **KSampler** node section, find the `sampler_name` dropdown. Enable its **multi-value mode** (toggle next to the field) and select all three samplers.
3. Do the same for the `cfg` field — enter `4, 6, 8, 10` as comma-separated values.
4. Click **Generate**. ComfyWeave detects multiple active dimensions and opens the **Generation Order** dialog.
5. Drag the rows to set which dimension varies slowest (outer loop) and which varies fastest (inner loop). The total job count is shown live.
6. Click OK. All 12 combinations are queued. Monitor them in the **Queue** panel at the bottom-left.

*Example use case:* You have a portrait LoRA that looks great on euler but muddy on DPM. Run the sweep, flip through the image grid (images are colour-grouped by generation run), and pick the winner.

---

### 3. Multi-LoRA Sweep

**Scenario:** You have 8 style LoRAs and want to see which one fits a prompt best, using otherwise identical settings.

1. Connect and load your workflow.
2. Find the **LoraLoader** node section. Check the **Multi-LoRA Mode** checkbox beneath the LoRA dropdown.
3. The dropdown is replaced by a **Select LoRAs…** button. Click it to open the searchable checklist.
4. Search and tick all 8 LoRAs. Click OK. The button updates to show "8 LoRAs selected".
5. Click **Generate**. ComfyWeave queues one job per LoRA. Each job in the Queue panel shows the LoRA name in the *LoRA* column.
6. In the image grid, each LoRA's output gets a distinct background colour for quick visual grouping. Click any thumbnail to open the detail view, which shows the LoRA name badge in the top-right corner.

---

### 4. Image Viewer & Export

**Scenario:** A sweep just finished — 24 images. You want to find the best one, save it, and reload its workflow for a follow-up run.

1. The image grid on the right auto-populates as jobs complete. Images are grouped by `generation_group_id` (distinct background colour per group).
2. Click any thumbnail to open the detail view. Use the **←** / **→** buttons, arrow keys, or swipe to step through images. Press **Escape** to return to the grid.
3. The badge strip (top-right) shows:
   - **LoRA** name (if a multi-LoRA sweep)
   - **Batch** position (X / Y within this group)
   - **All** position (X of Y across everything)
   > All three badges can be individually toggled in **Settings → Single Image View**.
4. Use the scroll wheel or drag to zoom/pan in the detail view.
5. Click **Save As…** to save the current image to disk. The last-used directory is remembered.
6. Click **Copy** to copy the current image directly to the clipboard.
7. Click **Load Workflow** to extract the embedded workflow from the image and reload it into the left panel — useful for tweaking a previous run without hunting for the original JSON.
8. Click **Clear Images** (toolbar, grid view) to wipe the grid and start fresh.
9. In the Queue panel, click **View** on any completed job to jump to that job's images in the grid.

---

### Generation Controls

Four buttons sit below the **Generate** button and manage in-flight and queued jobs:

| Button | Effect |
|---|---|
| **Stop Current** | Interrupt the job currently being processed (queued jobs continue). |
| **Clear Queue** | Remove all pending jobs; the running job finishes normally. |
| **Stop + Clear** | Interrupt the current job *and* wipe the entire queue in one click. |
| **↺ Retry** | Re-submit the last completed or failed job with exactly the same settings. |

---

### Prompt Text Blocks

Text fields (e.g. CLIP Text Encode prompt inputs) have a **Blocks** button. Click it to save the current text as a reusable snippet or insert a previously saved one. Blocks are stored per field key in `config/text_blocks.json` and persist between sessions.

---

## Project Structure

```
ComfyWeave/
├── main.py                    # Entry point — Qt + qasync bootstrap
├── requirements.txt
├── LICENSE
│
├── core/                      # ComfyUI communication layer
│   ├── api_client.py          # Async HTTP client (REST endpoints)
│   ├── websocket_client.py    # Persistent WS connection; emits Qt signals
│   ├── workflow.py            # Workflow loader, validator, payload builder
│   └── exceptions.py
│
├── models/                    # Data models
│   ├── config_model.py        # AppConfig dataclass (all persisted settings)
│   └── job.py                 # Job dataclass + JobStatus enum
│
├── ui/                        # PySide6 UI layer
│   ├── main_window.py         # Top-level window; orchestrates all panels
│   ├── connection_bar.py      # Server URL + connect/disconnect bar
│   ├── workflow_panel.py      # Editable workflow form, batch logic, LoRA picker
│   ├── multi_dim_order_dialog.py  # Cartesian-product loop-order dialog
│   ├── queue_panel.py         # Job queue table
│   ├── image_viewer.py        # Thumbnail grid + zoomable detail view
│   ├── progress_bar.py        # Live step progress bar
│   └── settings_dialog.py     # Settings UI
│
├── utils/
│   ├── config_manager.py      # Load/save AppConfig ↔ config/settings.json
│   ├── image_utils.py         # bytes → QPixmap helpers, thumbnail scaling
│   └── text_block_manager.py  # Per-field prompt snippet library
│
├── config/
│   ├── settings.json          # Persisted app settings (auto-generated)
│   └── text_blocks.json       # Persisted prompt text blocks (auto-generated)
│
├── assets/
│   ├── icon.png               # Application icon (256×256)
│   └── icon.ico               # Multi-size ICO (16–256 px)
│
└── tools/
    └── generate_icon.py       # Icon generation script (run once)
```

---

## Requirements

| Package | Version | Purpose |
|---|---|---|
| `PySide6` | `>=6.7.0, <6.9.0` | Qt6 GUI framework |
| `httpx[http2]` | `>=0.27.0` | Async HTTP client for ComfyUI REST API |
| `websockets` | `>=12.0` | ComfyUI WebSocket stream |
| `qasync` | `>=0.27.1` | asyncio ↔ Qt event loop bridge |

Optional (only needed to regenerate the `.ico` file):

| Package | Purpose |
|---|---|
| `Pillow` | Multi-size ICO generation in `tools/generate_icon.py` |
