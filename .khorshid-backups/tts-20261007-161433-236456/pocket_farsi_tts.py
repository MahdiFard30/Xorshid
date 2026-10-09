from __future__ import annotations

import os
import subprocess
import sys

import torch
from transformers import AutoTokenizer, T5ForConditionalGeneration

from normalize_fa import normalize_for_model

ROOT = os.path.dirname(os.path.abspath(__file__))
TEXT = sys.argv[1]
OUT = sys.argv[2]

G2P = "mehdi-hf/Homo-GE2PE-Persian-HF"
VOICE = os.path.join(ROOT, "my_voice_prompt.wav")
POCKET = os.path.join(ROOT, ".tts-venv", "bin", "pocket-tts")

TO_PHONEMES = str.maketrans({
    "/": "a",
    "a": "A",
    "@": "?",
    "$": "S",
    "c": "C",
})

def phonemise(text: str) -> str:
    tok = AutoTokenizer.from_pretrained(G2P)
    g2p = T5ForConditionalGeneration.from_pretrained(G2P).eval()

    norm = normalize_for_model(text)
    norm = norm.replace("؟", "").replace("?", "")

    enc = tok([norm], add_special_tokens=False, return_tensors="pt")
    with torch.no_grad():
        out = g2p.generate(
            **enc,
            num_beams=5,
            max_length=512,
            early_stopping=True,
        )

    raw = tok.batch_decode(out, skip_special_tokens=True)[0].strip()
    return raw.translate(TO_PHONEMES).replace("1", "")

if not os.path.isfile(VOICE):
    raise SystemExit(f"Voice prompt not found: {VOICE}")

phonemes = phonemise(TEXT)

subprocess.run(
    [
        POCKET,
        "generate",
        "--config",
        "hf://mehdi-hf/pocket-tts-farsi-v2/model.yaml",
        "--voice",
        VOICE,
        "--text",
        phonemes,
        "--output-path",
        OUT,
        "--device",
        "cpu",
        "--quiet",
    ],
    cwd=ROOT,
    check=True,
)
