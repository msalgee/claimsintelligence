"""Generate a high-fidelity ``damage_photo.png`` for the
``claim_collision_commercial_hint`` sample using GPT-image.

Two backends are auto-detected (in this order):

1. **Azure OpenAI** — requires ``AZURE_OPENAI_ENDPOINT`` (e.g.
   ``https://<account>.openai.azure.com/``) and a ``gpt-image-1``
   deployment in that account. Authentication uses
   ``DefaultAzureCredential`` (no API keys), so the calling identity must
   have the ``Cognitive Services OpenAI User`` role on the account.

2. **OpenAI public API** — requires ``OPENAI_API_KEY``. Useful when the
   tenant's Foundry/AOAI account does not yet have ``gpt-image-1``
   deployed and you only want to refresh the sample asset locally.

The script writes ``damage_photo.png`` (and, optionally, a tighter
crop ``damage_photo_alt.png`` when ``--alt`` is passed) into this folder,
overwriting the PIL fallback from ``generate_pdfs.py``.

Usage::

    # Azure OpenAI (preferred, passwordless)
    az login
    $env:AZURE_OPENAI_ENDPOINT = "https://<account>.openai.azure.com/"
    $env:AZURE_OPENAI_IMAGE_DEPLOYMENT = "gpt-image-1"      # optional override
    python src/ContentProcessorAPI/samples/claim_collision_commercial_hint/generate_image.py

    # OpenAI public API (fallback)
    $env:OPENAI_API_KEY = "sk-..."
    python src/ContentProcessorAPI/samples/claim_collision_commercial_hint/generate_image.py
"""
from __future__ import annotations

import argparse
import base64
import os
import sys
from pathlib import Path

OUT_DIR = Path(__file__).parent

PRIMARY_PROMPT = (
    "Photorealistic DSLR-style inspection photograph of a midnight-blue "
    "metallic 2022 Toyota Camry SE sedan parked at night in an "
    "airport-area cell-phone waiting lot, three-quarter front-driver view. "
    "The vehicle has just sustained a low-speed front-end collision: "
    "front bumper cover crumpled centre-left, hood buckled at the "
    "leading edge, left headlamp assembly cracked with visible fracture "
    "lines, radiator support bent, AC condenser leaking a small puddle "
    "of coolant under the front bumper. "
    "Subtle commercial-use cues are visible but never spelled out: a "
    "small removable suction-base rooftop placard mount sits on the roof "
    "above the windshield (placard itself not displayed); a partially "
    "removed adhesive trade-dress decal leaves a faint round residue "
    "ring on the lower-left rear quarter window glass; through the "
    "driver-side window, two phone-mount cradles are visible on the "
    "dashboard (one oriented to the driver, one toward the rear seat); "
    "a small windshield-mounted dashcam is also visible. "
    "Background: wet asphalt with reflections, distant warm sodium-vapour "
    "terminal lights, an overhead lamp pool casting a soft highlight on "
    "the vehicle. Sharp focus, realistic materials, no text overlays, no "
    "watermarks, no people, no logos."
)

ALT_PROMPT = (
    "Tight close-up photorealistic photograph of the rear quarter "
    "panel and rear quarter window of a midnight-blue metallic 2022 "
    "Toyota Camry SE at night in a wet airport-area parking lot. "
    "A faint round adhesive residue ring (about 12 cm diameter) from a "
    "partially-removed trade-dress decal is clearly visible on the lower "
    "rear quarter window glass. Slight reflection of overhead sodium-vapour "
    "lighting on the wet paint. Inspection-photo aesthetic, sharp focus, "
    "no text, no watermarks, no people, no logos."
)


def _save_b64_png(b64: str, out_path: Path) -> None:
    out_path.write_bytes(base64.b64decode(b64))


def _generate_azure_openai(prompt: str, out_path: Path, size: str) -> None:
    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
    from openai import AzureOpenAI

    endpoint = os.environ["AZURE_OPENAI_ENDPOINT"].rstrip("/")
    deployment = os.environ.get("AZURE_OPENAI_IMAGE_DEPLOYMENT", "gpt-image-1")
    api_version = os.environ.get(
        "AZURE_OPENAI_IMAGE_API_VERSION", "2025-04-01-preview"
    )

    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    client = AzureOpenAI(
        azure_endpoint=endpoint,
        azure_ad_token_provider=token_provider,
        api_version=api_version,
    )
    print(f"  azure-openai deployment={deployment} size={size}")
    resp = client.images.generate(
        model=deployment,
        prompt=prompt,
        size=size,
        n=1,
    )
    _save_b64_png(resp.data[0].b64_json, out_path)


def _generate_openai(prompt: str, out_path: Path, size: str) -> None:
    from openai import OpenAI

    model = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
    client = OpenAI()
    print(f"  openai model={model} size={size}")
    resp = client.images.generate(
        model=model,
        prompt=prompt,
        size=size,
        n=1,
    )
    _save_b64_png(resp.data[0].b64_json, out_path)


def _generate(prompt: str, out_path: Path, size: str) -> None:
    if os.environ.get("AZURE_OPENAI_ENDPOINT"):
        _generate_azure_openai(prompt, out_path, size)
    elif os.environ.get("OPENAI_API_KEY"):
        _generate_openai(prompt, out_path, size)
    else:
        sys.exit(
            "ERROR: set AZURE_OPENAI_ENDPOINT (with az login + RBAC) or "
            "OPENAI_API_KEY before running this script."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--alt",
        action="store_true",
        help="Also generate the tighter rear-quarter close-up "
             "(damage_photo_alt.png) showing the decal residue.",
    )
    parser.add_argument(
        "--size",
        default="1536x1024",
        help="Image size (gpt-image-1 supports 1024x1024, 1024x1536, "
             "1536x1024). Default: 1536x1024.",
    )
    args = parser.parse_args()

    OUT_DIR.mkdir(exist_ok=True)

    main_path = OUT_DIR / "damage_photo.png"
    print(f"generating {main_path.name}")
    _generate(PRIMARY_PROMPT, main_path, args.size)
    print(f"  wrote {main_path.name} ({main_path.stat().st_size // 1024} KB)")

    if args.alt:
        alt_path = OUT_DIR / "damage_photo_alt.png"
        print(f"generating {alt_path.name}")
        _generate(ALT_PROMPT, alt_path, args.size)
        print(f"  wrote {alt_path.name} ({alt_path.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
