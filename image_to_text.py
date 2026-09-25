import argparse
import base64
import os
from pathlib import Path

import openai

client = openai.OpenAI(
    api_key=os.environ.get('CBORG_API_KEY'),
    base_url="https://api.cborg.lbl.gov"
)


def encode_file(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Describe an image using the CBORG vision API.")
    parser.add_argument("file", type=Path, help="Path to the image file")
    parser.add_argument("-p", "--prompt", default="Describe the picture.", help="Prompt to send with the image")
    parser.add_argument(
        "-m", "--model", default="lbl/cborg-ocr",
        help="Model to use (e.g. lbl/cborg-ocr, lbl/cborg-vision, lbl/cborg-ocr-fast)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.file.is_file():
        raise SystemExit(f"File not found: {args.file}")

    encoded = encode_file(args.file)
    mime_type = f"image/{args.file.suffix.lstrip('.').lower() or 'png'}"

    response = client.chat.completions.create(
        model=args.model,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": args.prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}},
                ],
            }
        ],
        temperature=0.0,
        stream=False,
    )

    print(response.choices[0].message.content)


if __name__ == "__main__":
    main()
