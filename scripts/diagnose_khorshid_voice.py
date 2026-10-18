#!/usr/bin/env python3
"""Read-only Khorshid voice report: no models, audio devices, or configuration modified."""
from pathlib import Path
import json
import sys

root = Path(__file__).resolve().parents[1]
report_path = root / '.tts_debug' / 'latest.json'
if not report_path.is_file():
    print('گزارش صدا پیدا نشد:', report_path)
    print('یک بار خورشید را با دستور معمول اجرا کنید و از او یک پاسخ صوتی بخواهید؛ سپس دوباره این فایل را اجرا کنید.')
    sys.exit(2)
try:
    d = json.loads(report_path.read_text(encoding='utf-8'))
except (OSError, ValueError) as e:
    print('خواندن گزارش ممکن نشد:', e)
    sys.exit(2)
chunks = d.get('chunks', [])
phrases = d.get('phrase_boundaries', [])
retries = sum(max(0,len(c.get('attempts', []))-1) for c in chunks)
failed = sum(1 for c in chunks if not any(a.get('accepted') for a in c.get('attempts', [])))
print('=== Khorshid voice: read-only diagnostics ===')
print('status:', d.get('status', 'unknown'))
print('device:', d.get('device', 'unknown'))
print('voice reference used (seconds):', d.get('voice_used_seconds', 'unknown'))
print('number of phrases:', len(phrases))
print('number of generated chunks:', len(chunks))
print('total generation retries:', retries)
print('failed chunks:', failed)
print('first chunk generation (s):', d.get('first_chunk_seconds', 'unknown'))
print('total generation (s):', d.get('generation_seconds', 'unknown'))
print('intentional phrase pauses (s):', round(sum(float(p.get('pause',0)) for p in phrases[:-1]), 2))
print('chunk durations:')
for i,c in enumerate(chunks[:35], 1):
    att = c.get('attempts', [])
    ok = next((a for a in att if a.get('accepted')), None)
    dur = round(float(ok['seconds']),2) if ok and ok.get('seconds') is not None else '?'
    print(f'  {i:02d}: audio={dur}s, attempts={len(att)}, phoneme_tokens={c.get("tokens","?")}')
if len(chunks)>35:
    print('  ...',len(chunks)-35,'more chunks')
print('NOTE: report has synthesis timings, NOT actual playback gap measurements.')
print('NOTE: no configuration, model, MT5, or desktop tools changed.')
