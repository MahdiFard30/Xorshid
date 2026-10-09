"""Run from Ultimate-Jarvis-main with: python apply_fast_tts.py"""
import hashlib
import json
from pathlib import Path
import shutil
from datetime import datetime

root = Path.cwd()
source = Path(__file__).resolve().parent / 'patch'
if not (root / 'ultimate_khorshid/voice/engines.py').is_file():
    raise SystemExit('Run this command inside Ultimate-Jarvis-main after installing Khorshid.')
manifest = json.loads((source.parent / 'manifest.json').read_text())
for rel, expected in manifest.items():
    target = root / rel
    incoming = source / rel
    if target.exists():
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if digest not in (expected, hashlib.sha256(incoming.read_bytes()).hexdigest()):
            raise SystemExit(f'Local changes found in {rel}; nothing replaced. Send this file for a tailored update.')
backup = root / '.khorshid-backups' / ('fast-tts-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
for rel in manifest:
    target = root / rel
    if target.exists():
        saved = backup / rel
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, saved)
for rel in manifest:
    target = root / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / rel, target)
print('TTS update installed. Original files backed up to:', backup)
print('Start: python khorshid_sun_final.py')
