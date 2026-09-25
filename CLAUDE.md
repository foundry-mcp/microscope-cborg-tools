# microscope-cborg-tools

MCP servers giving Claude Code "eyes" on an electron microscope, using
LBL's free on-prem CBORG models. See README.md for the user-facing overview
of the two tools. This file is for future development sessions.

## Architecture

- `cborg_ocr_server.py` — MCP server, tool `ocr_screenshot(path, prompt)`.
  Reads GUI screenshots via `lbl/cborg-ocr`, falls back to
  `lbl/cborg-ocr-fast` if the result looks empty/refused.
- `cborg_vision_server.py` — MCP server, tool
  `describe_microscope_image(path, prompt)`. Loads acquired image data
  (`.emd`/`.ser`/`.dm3`/`.dm4`) via `ncempy.read()`, downscales to ~256px,
  and describes it via `lbl/cborg-vision` with FOV/pixel-size context
  baked into the prompt.
- `.claude/agents/microscope-ocr.md`, `microscope-vision.md` — Haiku
  subagents, each scoped to exactly one of the above tools. They own the
  prompt-crafting and retry judgment so the main session only sees a
  short final answer, not the back-and-forth. **Always prefer routing
  through these subagents over calling the MCP tools directly** — that's
  the whole point of the split (keeps the main driving session's context
  clean).
- `.mcp.json` — registers both servers with relative paths (`.venv/bin/python`)
  so this works from any checkout location. Requires `CBORG_API_KEY` in
  the environment.
- `image_to_text.py` — original standalone script this project grew out
  of. Not used by the MCP servers; kept as a minimal reference/fallback
  CLI.

## Design decisions worth knowing before changing things

- **Separate MCP servers, not merged into `team05-mcp-server/mcp_library.py`**
  (the microscope's ZMQ-based instrument-control MCP server). Reasons:
  that server's `__init__` calls `exit()` if the instrument PCs aren't
  reachable — bundling would make OCR/vision unusable whenever hardware is
  offline. Different dependency stacks (zmq/h5py/beacon_client vs.
  openai/ncempy). Different runtime (persistent SSE server on the scope
  network vs. local stdio process). Multiple MCP servers already
  contribute to one flat tool pool for Claude, so no merge is needed for
  cross-tool workflows (e.g. call `acquire_image` then
  `describe_microscope_image` in the same turn).
- **Retry/fallback logic lives in the tool, not the subagent**, for OCR's
  model fallback — it's mechanical, not a judgment call. The subagent's
  retries are about prompt phrasing/interpretation, a different kind of
  retry.
- **CBORG calls are free (on-prem, no token cost)** — both tools and
  their subagents are written to retry liberally rather than accept a
  bad/ambiguous first answer. Don't add caching or rate-limiting to
  "save cost" — there isn't any.
- **Noise/blank-acquisition guard in `cborg_vision_server.py`**
  (`NOISE_STD_THRESHOLD`): a beam-off acquisition is pure detector noise,
  and the vision model will confidently hallucinate sample features from
  it (e.g. described noise as a "periodic nanodot array" before this
  check existed). The check short-circuits before calling CBORG at all if
  intensity std is below threshold. Calibrated from observed data: noise
  files had std ~17–49 across very different intensity offsets (~1600 vs
  ~14300 mean), real sample images had std in the thousands (~2500–10000).
  100 sits well clear of both clusters. If you see a real low-contrast
  sample incorrectly flagged as noise, that's the number to revisit —
  don't just delete the check.
- **`microscope-vision.md` is deliberately scoped to sample
  type/morphology only** (particles, wires, faceted crystals, arrays,
  etc), not image/focus quality. The user does not want automated
  focus/astigmatism judgment from this tool — the ~256px downscale makes
  such judgments unreliable anyway. If asked to add quality assessment
  back in, push back / clarify first rather than just adding it.
- **`microscope-ocr.md`'s "Known fields" table** has a `Plausible bounds`
  column that is a hard sanity-check ceiling to catch bad OCR reads
  (wrong units, misread digits) — it is NOT a "this is the expected/normal
  range" check. Several fields (lens %, defocus) swing widely by
  instrument mode; an unusual-but-in-bounds value should be reported as-is,
  never second-guessed against "normal" values. Bounds marked `(?)` are
  placeholders — replace with real instrument limits as they're learned,
  don't leave fabricated numbers unmarked.
- Defocus display switches units (nm below 1 µm, µm at/above 1 µm) —
  documented in the OCR table. Screen current is always displayed in nA
  with a display floor of 0.039 nA.

## Environment notes

- Dev/test happened on Linux (WSL) at `/home/percius/scripting/image_to_text`,
  using a local `.venv` (created via `uv`, no system `pip` in the venv —
  use `uv pip install --python .venv/bin/python <pkg>`).
- Target deployment is the microscope control PC, which per
  `team05-mcp-server/mcp_library.py` looks like Windows (`D:/user_data/...`
  paths). If deploying there, `.mcp.json`'s `.venv/bin/python` will need
  to become `.venv\Scripts\python.exe` (not yet done/tested).
- `requirements.txt` lists direct deps only (`mcp`, `openai`, `pillow`,
  `ncempy`) — `ncempy` pulls in `h5py`, `scipy`, `matplotlib`, etc.
  transitively.
- Test data (`.emd`, `.ser`, `.png`, `.jpg`, `.dm3`, `.dm4`) is
  intentionally gitignored — real screenshots/acquisitions from the
  instrument, not meant to live in the repo. When testing changes, check
  what test files currently exist in the working directory rather than
  assuming any are tracked/present.

## Testing pattern used so far

No formal test suite yet — verification has been done by calling the
tool functions directly against real acquired files placed in the working
directory, e.g.:

```bash
.venv/bin/python -c "
from cborg_vision_server import describe_microscope_image
print(describe_microscope_image('some_file.emd', 'What is the sample morphology?'))
"
```

and by invoking the subagents directly via the Agent tool once
`.mcp.json` is registered (requires a Claude Code session restart after
`.mcp.json` or agent files change).
