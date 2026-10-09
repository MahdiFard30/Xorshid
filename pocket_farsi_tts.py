"""Bounded Persian G2P + short-token Pocket generation; one model load per reply."""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from tts_text import sentence_pieces, phoneme_pieces

ROOT = Path(__file__).resolve().parent
G2P = 'mehdi-hf/Homo-GE2PE-Persian-HF'
MODEL = 'mehdi-hf/pocket-tts-farsi-v2'
CONFIG = 'hf://mehdi-hf/pocket-tts-farsi-v2/model.yaml'
TO_PHONEMES = str.maketrans({'/':'a', 'a':'A', '@':'?', '$':'S', 'c':'C'})


def main(text, output):
    import numpy as np
    import torch
    import soundfile as sf
    import sentencepiece as spm
    from huggingface_hub import hf_hub_download
    from transformers import AutoTokenizer, T5ForConditionalGeneration
    from pocket_tts import TTSModel
    from normalize_fa import normalize_for_model

    debug_dir = ROOT / '.tts_debug'
    debug_dir.mkdir(exist_ok=True)
    report = {'text': text, 'started': time.time(), 'chunks': [], 'status': 'started'}
    report_path = debug_dir / 'latest.json'
    def save_report():
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    save_report()
    try:
        voice_path = ROOT / 'my_voice_prompt.wav'
        voice, voice_rate = sf.read(voice_path, dtype='float32', always_2d=True)
        report['voice_original_seconds'] = len(voice) / voice_rate
        # Preserve the exact original voice reference: no crop, conversion or replacement.
        if len(voice) < voice_rate * 0.5 or float(np.max(np.abs(voice))) < 0.001:
            raise RuntimeError('Voice reference is too short or silent')
        report['voice_used_seconds'] = len(voice) / voice_rate
        tokenizer = AutoTokenizer.from_pretrained(G2P)
        g2p = T5ForConditionalGeneration.from_pretrained(G2P).eval()
        sp = spm.SentencePieceProcessor(model_file=hf_hub_download(MODEL, 'tokenizer_ph.model'))
        def token_count(s):
            return len(sp.encode(s, out_type=int))

        # Normalize numbers BEFORE length splitting, since digits expand to words.
        normalized = normalize_for_model(text)
        report['normalized_text'] = normalized
        if not normalized.strip():
            raise RuntimeError('No pronounceable text remains after Persian normalization')
        plans = []
        for phrase, sentence_pause in sentence_pieces(normalized):
            source = phrase.replace('؟', '').replace('?', '')
            encoded = tokenizer([source], add_special_tokens=False, return_tensors='pt')
            with torch.no_grad():
                output_ids = g2p.generate(**encoded, num_beams=5, max_length=512, early_stopping=True)
            ids = output_ids[0].tolist()
            if tokenizer.eos_token_id not in ids:
                raise RuntimeError('G2P hit its limit without ending; refusing incomplete pronunciation')
            raw = tokenizer.batch_decode(output_ids, skip_special_tokens=True)[0].strip()
            phonemes = raw.translate(TO_PHONEMES)
            parts = phoneme_pieces(phonemes, token_count)
            if not parts:
                raise RuntimeError('G2P returned empty pronunciation')
            for i, part in enumerate(parts):
                plans.append({'source': phrase, 'phonemes': part, 'tokens': token_count(part),
                              'pause': sentence_pause if i == len(parts)-1 else 0.10})
        del g2p, tokenizer
        report['planned_chunks'] = len(plans)
        save_report()
        print(f'[TTS] Generating {len(plans)} short chunks with original my_voice_prompt.wav.', flush=True)
        # Explicit config preserves the phoneme frontend flags used by the CLI.
        model = TTSModel.load_model(config=CONFIG)
        with tempfile.TemporaryDirectory(prefix='khorshid_tts_') as tmp:
            state = model.get_state_for_audio_prompt(str(voice_path))
            def normal_state(value):
                # Pocket updates caches in a worker thread. Inference tensors cannot
                # cross that boundary; clone them outside inference mode first.
                if isinstance(value, torch.Tensor):
                    with torch.inference_mode(False), torch.no_grad():
                        return value.detach().clone()
                if isinstance(value, dict):
                    return {key: normal_state(item) for key, item in value.items()}
                if isinstance(value, list):
                    return [normal_state(item) for item in value]
                if isinstance(value, tuple):
                    return tuple(normal_state(item) for item in value)
                return copy.deepcopy(value)
            rate = model.sample_rate
            pieces = []
            for index, plan in enumerate(plans, 1):
                cap = plan['tokens'] / 3.0 + 2.0
                accepted = None
                attempts = []
                for attempt in range(3):
                    # Fresh voice state for each attempt/chunk prevents context carry-over.
                    with torch.no_grad():
                        audio = model.generate_audio(normal_state(state), plan['phonemes'])
                    pcm = audio.detach().cpu().numpy().reshape(-1).astype('float32')
                    seconds = len(pcm) / rate
                    valid = (len(pcm) > 0 and np.isfinite(pcm).all()
                             and seconds < cap and float(np.max(np.abs(pcm))) > 0.001)
                    attempts.append({'seconds': seconds, 'accepted': bool(valid)})
                    if valid:
                        accepted = pcm
                        break
                    print(f'[TTS] Retrying chunk {index}: duration/silence check.', flush=True)
                item = dict(plan, attempts=attempts)
                report['chunks'].append(item)
                save_report()
                if accepted is None:
                    raise RuntimeError(f'Chunk {index} failed checks after 3 attempts; see .tts_debug/latest.json')
                pieces.append(accepted)
                if index < len(plans):
                    pieces.append(np.zeros(round(rate * plan['pause']), dtype='float32'))
                print(f'[TTS] {index}/{len(plans)} ready', flush=True)
            result = np.concatenate(pieces)
            destination = Path(output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + '.partial.wav')
            sf.write(temporary, np.clip(result, -1, 1), rate, subtype='PCM_16')
            os.replace(temporary, destination)
            report['status'] = 'ok'
            report['duration_seconds'] = len(result) / rate
    except Exception as exc:
        report['status'] = 'error'
        report['error'] = str(exc)
        raise
    finally:
        save_report()


if __name__ == '__main__':
    if len(sys.argv) != 3:
        raise SystemExit('Usage: pocket_farsi_tts.py TEXT OUTPUT.wav')
    main(sys.argv[1], sys.argv[2])
