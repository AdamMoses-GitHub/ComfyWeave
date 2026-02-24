# ComfyWeave

*Because tweaking ComfyUI nodes by hand is like tuning a guitar by swapping out the whole neck.*

![Version](https://img.shields.io/badge/version-1.0.0-blue) ![Python](https://img.shields.io/badge/python-3.13-blue) ![License](https://img.shields.io/badge/license-MIT-green)

![App Screenshot](INSERT_IMAGE_URL_HERE)

---

## About

Running experiments in ComfyUI means endless manual node rewiring — change a sampler, Save API Format, submit, repeat. Testing three samplers × four prompts × two LoRAs means 24 separate manual runs, each one a small exercise in tedium.

**ComfyWeave** turns that into a form. Load your API-format workflow, set multiple values on any input field, and ComfyWeave computes every combination and queues them all in one click. It connects directly to your running ComfyUI instance over HTTP and WebSocket — no plugins, no ComfyUI modifications required.

**Repository:** [https://github.com/AdamMoses-GitHub/ComfyWeave](https://github.com/AdamMoses-GitHub/ComfyWeave)

---

## What It Does

### The Main Features

- **Workflow form editor** — load any ComfyUI API-format JSON and get an instant, editable input form for every recognised node (samplers, text encoders, checkpoint/LoRA/VAE loaders, latent image nodes, and more)
- **Multi-value batch sweeps** — assign multiple values to any field; ComfyWeave computes the Cartesian product and submits every permutation as individual jobs
- **Multi-LoRA sweep mode** — pick any number of LoRAs from a searchable checklist; one generation job is queued per LoRA automatically
- **Live generation feedback** — real-time step progress bar and latent preview images streamed directly from ComfyUI's WebSocket
- **Image grid viewer** — scrollable thumbnail grid with per-job metadata overlays (LoRA name, batch position, generation group colour-coding) and a full-resolution detail view with zoom/pan
- **Persistent session state** — last workflow path, all field overrides, window layout, and settings survive restarts

### The Nerdy Stuff

- `qasync` bridges Python `asyncio` with the Qt event loop — no threads, no polling
- Persistent WebSocket with exponential-backoff reconnect (delays: 1 → 2 → 4 → 8 → 16 → 30 s)
- Cartesian-product job scheduler with a user-configurable loop-order dialog (slowest-varying → fastest-varying dimension)
- Per-field reusable text block library persisted to `config/text_blocks.json`
- Workflow validation catches the common mistake of loading UI-format JSON instead of API-format, with a clear fix instruction

---

## Quick Start (TL;DR)

See [INSTALL_AND_USAGE.md](INSTALL_AND_USAGE.md) for the full guide.

```bash
git clone https://github.com/AdamMoses-GitHub/ComfyWeave.git
cd ComfyWeave
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
python main.py
```

---

## Tech Stack

| Component | Purpose | Why This One |
|---|---|---|
| [PySide6](https://pypi.org/project/PySide6/) `6.8.x` | Desktop GUI framework | Official Qt6 bindings; excellent Windows DPI support |
| [httpx](https://www.python-httpx.org/) `0.27+` | Async HTTP client (REST API calls) | Native async, HTTP/2 support, clean timeout control |
| [websockets](https://websockets.readthedocs.io/) `12+` | ComfyUI WebSocket stream | Lightweight, asyncio-native; no framework overhead |
| [qasync](https://github.com/CabbageDevelopment/qasync) `0.27+` | asyncio ↔ Qt event loop bridge | Makes Qt+asyncio coexist without threads |

---

## License

MIT — see [LICENSE](LICENSE). Copyright © 2026 Adam Moses.

## Contributing

PRs welcome. Open an issue first for anything non-trivial.

---

<sub>comfyui gui client, comfyui desktop app, comfyui batch, comfyui automation, stable diffusion batch, stable diffusion workflow, pyside6 comfyui, comfyui python, image generation automation, prompt permutation, lora sweep, comfyui api, comfyui workflow editor, sd batch generation, comfyui frontend, comfyweave, stable diffusion experiment, comfyui multi-lora, ai image batch, comfyui tool</sub>

