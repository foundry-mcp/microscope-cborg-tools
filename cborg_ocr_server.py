"""MCP server exposing CBORG on-prem vision/OCR models as a tool.

Runs OCR against LBL's CBORG platform (free, on-prem, no token cost) and
returns plain text. All retry/fallback logic lives here so callers spend
zero reasoning effort on the mechanics of getting a reading.
"""
import base64
import os
from pathlib import Path

import openai
from mcp.server.mcpserver import MCPServer

client = openai.OpenAI(
    api_key=os.environ.get("CBORG_API_KEY"),
    base_url="https://api.cborg.lbl.gov",
)

mcp = MCPServer("cborg-ocr")

# Models to try in order. Primary is the accurate OCR model; fast is a
# cheaper fallback if the primary returns something unusable.
MODELS = ("lbl/cborg-ocr", "lbl/cborg-ocr-fast")


def encode_file(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def looks_valid(text: str | None) -> bool:
    """Cheap sanity check: non-empty and not an obvious refusal/error."""
    if not text or not text.strip():
        return False
    lowered = text.lower()
    bad_markers = ("i cannot", "i can't", "unable to process", "error")
    return not any(marker in lowered for marker in bad_markers)


def call_cborg(path: Path, prompt: str, model: str) -> str:
    encoded = encode_file(path)
    mime_type = f"image/{path.suffix.lstrip('.').lower() or 'png'}"
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
                ],
            }
        ],
        temperature=0.0,
        stream=False,
    )
    return response.choices[0].message.content or ""


@mcp.tool()
def ocr_screenshot(path: str, prompt: str = "Describe the picture.") -> str:
    """Read text/values off a screenshot using LBL's on-prem CBORG OCR model.

    Tries lbl/cborg-ocr first, falls back to lbl/cborg-ocr-fast if the
    primary result looks empty or like a refusal. Free to call (on-prem,
    no token cost) so callers should feel free to retry with a different
    prompt if the returned text doesn't answer what they need.

    Args:
        path: Absolute path to the screenshot image file.
        prompt: What to extract, e.g. "Read the stage X/Y coordinates
            shown in the status bar." Defaults to a general description.
    """
    file_path = Path(path)
    if not file_path.is_file():
        return f"Error: file not found: {path}"

    last_result = ""
    for model in MODELS:
        try:
            last_result = call_cborg(file_path, prompt, model)
        except Exception as exc:
            last_result = f"Error calling {model}: {exc}"
            continue
        if looks_valid(last_result):
            return last_result

    return last_result


if __name__ == "__main__":
    mcp.run()
