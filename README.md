# Microscope CBORG Tools

MCP servers that give Claude Code eyes on an electron microscope's control
software and acquired data, using LBL's on-premises CBORG models
(`lbl/cborg-ocr`, `lbl/cborg-vision`). These models are free/no-cost to
call, so both tools are built to retry liberally rather than accept a bad
first answer.

Each tool is paired with a small Haiku subagent (`.claude/agents/`) that
does the light reasoning around it — crafting a good prompt, judging
whether the raw result is usable, retrying if not — so the main session
driving the microscope only sees a short, final answer instead of the
back-and-forth.

## Tools

### `cborg-ocr` — read values off the instrument GUI

`cborg_ocr_server.py` exposes `ocr_screenshot(path, prompt)`. Given a
screenshot of the microscope control software, it reads text/values off
the screen (stage position, lens %, FEG current, etc). Tries
`lbl/cborg-ocr` first and automatically falls back to `lbl/cborg-ocr-fast`
if the primary result looks empty or like a refusal.

Paired subagent: **`microscope-ocr`**. It phrases the extraction prompt
using the actual on-screen label for the requested field (see the "Known
fields" table in `.claude/agents/microscope-ocr.md`, which also documents
expected units and plausible-value bounds per field, used to catch bad
OCR reads), and retries with a clarified prompt if the result looks wrong.

### `cborg-vision` — describe what's on the sample

`cborg_vision_server.py` exposes `describe_microscope_image(path, prompt)`.
Given a path to an acquired image (`.emd`, `.ser`, `.dm3`, `.dm4`), it
loads the raw data and pixel calibration with `ncempy`, downscales the
image to ~256px on the long edge, and asks `lbl/cborg-vision` to describe
it. The field of view and pixel size are always included in the prompt so
the model's size/spacing estimates are scale-aware.

Paired subagent: **`microscope-vision`**. Scoped to sample type and
morphology only — particles, nanowires, faceted crystals, amorphous
blobs, arrays, etc, with size/spacing estimates — not image/focus quality,
which the aggressive downscaling makes unreliable to judge anyway.

## Setup

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
export CBORG_API_KEY=...   # your LBL CBORG API key
```

Both servers are registered in `.mcp.json` (relative paths, so this works
from any checkout location) and picked up automatically by Claude Code on
session start in this directory.

## Usage

From a Claude Code session in this directory, delegate to the subagents
rather than calling the MCP tools directly, so the reasoning/retry loop
stays out of the main session's context:

```
Agent(subagent_type: "microscope-ocr", prompt: "read the FEG IGP current from /path/to/screenshot.png")
Agent(subagent_type: "microscope-vision", prompt: "what is the sample morphology in /path/to/acquired_image.emd")
```
