import torch
import scipy.io.wavfile
from transformers import AutoTokenizer, T5ForConditionalGeneration
from pocket_tts import TTSModel
from normalize_fa import normalize_for_model

TEXT = "سلام، من خورشید هستم. الان دارم با صدای طبیعی شما صحبت می‌کنم."
VOICE = "./my_voice_prompt.wav"

G2P = "mehdi-hf/Homo-GE2PE-Persian-HF"

print("Loading G2P...")
tok = AutoTokenizer.from_pretrained(G2P)
g2p = T5ForConditionalGeneration.from_pretrained(G2P).eval()

TO_PHONEMES = str.maketrans({
    "/": "a",
    "a": "A",
    "@": "?",
    "$": "S",
    "c": "C",
})

def phonemise(text: str) -> str:
    text = normalize_for_model(text)
    text = text.replace("؟", "").replace("?", "")
    enc = tok([text], add_special_tokens=False, return_tensors="pt")
    with torch.no_grad():
        out = g2p.generate(
            **enc,
            num_beams=5,
            max_length=512,
            early_stopping=True
        )
    raw = tok.batch_decode(out, skip_special_tokens=True)[0].strip()
    return raw.translate(TO_PHONEMES).replace("1", "")

phonemes = phonemise(TEXT)
print("PHONEMES =", phonemes)

print("Loading Pocket-TTS Farsi v2...")
tts = TTSModel.load_model("hf://mehdi-hf/pocket-tts-farsi-v2/model.yaml")

print("Loading your voice...")
voice_state = tts.get_state_for_audio_prompt(VOICE)

print("Generating...")
audio = tts.generate_audio(voice_state, phonemes)

scipy.io.wavfile.write(
    "my_voice_v2.wav",
    tts.sample_rate,
    audio.numpy()
)

print("Saved: my_voice_v2.wav")
