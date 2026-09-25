"""MCP server exposing the CBORG on-prem vision model as a tool.

Describes microscope images acquired via mcp_library.py's acquire_image
(and similar) tools, which write image data to an EMD (.emd) or SER (.ser)
file. This server loads the raw image data and pixel calibration with
ncempy, downscales the image, and asks lbl/cborg-vision to describe it with
field-of-view and pixel size context so the model knows what to expect at
the given magnification.
"""
import base64
import io
import os
from pathlib import Path

import ncempy.io as ncio
import numpy as np
import openai
from mcp.server.mcpserver import MCPServer
from PIL import Image

client = openai.OpenAI(
    api_key=os.environ.get("CBORG_API_KEY"),
    base_url="https://api.cborg.lbl.gov",
)

mcp = MCPServer("cborg-vision")

MODEL = "lbl/cborg-vision"
TARGET_SIZE = 256

# Below this intensity standard deviation, an image is almost certainly a
# blank/no-beam acquisition (pure detector noise) rather than real signal.
# Observed noise floor (beam off) has std ~17; real sample images seen so
# far have std in the thousands. 100 leaves comfortable margin on both
# sides without being anywhere near real signal levels.
NOISE_STD_THRESHOLD = 100.0


def looks_valid(text: str | None) -> bool:
    """Cheap sanity check: non-empty and not an obvious refusal/error."""
    if not text or not text.strip():
        return False
    lowered = text.lower()
    bad_markers = ("i cannot", "i can't", "unable to process", "error")
    return not any(marker in lowered for marker in bad_markers)


def load_microscope_image(path: Path) -> dict:
    """Load image data and pixel calibration from an EMD or SER file using
    ncempy. Returns the dict from ncempy.read(), with 'data' (ndarray),
    'pixelSize' (per-axis calibration), and 'pixelUnit' (unit name)."""
    return ncio.read(path)


def to_downscaled_png_bytes(image: np.ndarray, target_size: int = TARGET_SIZE) -> bytes:
    """Normalize a raw microscope image to 8-bit grayscale and downscale it
    to roughly target_size on the long edge for the vision model."""
    image = image.astype(np.float64)
    lo, hi = image.min(), image.max()
    if hi > lo:
        scaled = (image - lo) / (hi - lo) * 255.0
    else:
        scaled = np.zeros_like(image)
    img = Image.fromarray(scaled.astype(np.uint8), mode="L")

    width, height = img.size
    long_edge = max(width, height)
    if long_edge > target_size:
        scale = target_size / long_edge
        new_size = (max(1, round(width * scale)), max(1, round(height * scale)))
        img = img.resize(new_size, resample=Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def call_cborg(image_bytes: bytes, prompt: str, model: str) -> str:
    encoded = base64.b64encode(image_bytes).decode("utf-8")
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{encoded}"}},
                ],
            }
        ],
        temperature=0.0,
        stream=False,
    )
    return response.choices[0].message.content or ""


@mcp.tool()
def describe_microscope_image(
    path: str,
    prompt: str = "Describe what is visible in this image.",
) -> str:
    """Describe a microscope image using LBL's on-prem CBORG vision model.

    Loads the raw image data and pixel calibration from an EMD, SER, or
    DM3/DM4 file (as returned by acquire_image and similar tools in
    mcp_library.py, or produced by other instruments in the experiment),
    downscales it to about 256 pixels on the long edge, and asks the vision
    model to describe it. The prompt sent to the model is augmented with
    the field of view and pixel size so it knows what scale of feature to
    expect at the current magnification. Free to call (on-prem, no token
    cost) so feel free to retry with a different prompt if the description
    isn't specific enough.

    Args:
        path: Path to a .emd, .ser, .dm3, or .dm4 file.
        prompt: What to ask about the image, e.g. "Is the sample in focus?"
            or "Describe any visible defects or contamination."
    """
    file_path = Path(path)
    if not file_path.is_file():
        return f"Error: file not found: {path}"

    try:
        loaded = load_microscope_image(file_path)
    except Exception as exc:
        return f"Error loading image data: {exc}"

    image = loaded["data"]

    std = float(np.std(image))
    if std < NOISE_STD_THRESHOLD:
        return (
            f"This image looks like a blank/no-beam acquisition (intensity "
            f"std={std:.1f}, below the noise threshold of "
            f"{NOISE_STD_THRESHOLD:.0f}), not a real sample image. Skipping "
            f"the vision model call. If the beam was on and a real feature "
            f"was expected, re-acquire the image."
        )

    pixel_size = loaded.get("pixelSize") or [1.0, 1.0]
    pixel_unit = loaded.get("pixelUnit") or ["px", "px"]
    # Last two dims are (y, x) per ncempy convention.
    caly, calx = pixel_size[-2], pixel_size[-1]
    unit_y, unit_x = pixel_unit[-2], pixel_unit[-1]

    height, width = image.shape[-2:]
    fov_x = width * calx
    fov_y = height * caly

    context = (
        f"This image was acquired on an electron microscope. "
        f"Field of view: {fov_x:.3g} {unit_x} x {fov_y:.3g} {unit_y}. "
        f"Pixel size: {calx:.3g} {unit_x}/pixel x {caly:.3g} {unit_y}/pixel. "
        f"Image is {width}x{height} pixels, downscaled for this request. "
    )
    full_prompt = context + prompt

    png_bytes = to_downscaled_png_bytes(image)

    try:
        result = call_cborg(png_bytes, full_prompt, MODEL)
    except Exception as exc:
        return f"Error calling {MODEL}: {exc}"

    return result


if __name__ == "__main__":
    mcp.run()
