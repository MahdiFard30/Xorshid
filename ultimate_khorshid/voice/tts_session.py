"""Owned persistent worker in .tts-venv, with overlapping generation/playback."""
import atexit
import json
import os
from pathlib import Path
import queue
import subprocess
import tempfile
import threading
import time
import uuid

ROOT=Path(__file__).resolve().parents[2]


class Session:
    def __init__(self):
        self.proc=None
        self.events=queue.Queue()
        self.start_lock=threading.Lock()
        self.request_lock=threading.Lock()

    def start(self):
        with self.start_lock:
            if self.proc is not None and self.proc.poll() is None:return
            self.events=queue.Queue()
            python=ROOT/'.tts-venv/bin/python'
            script=ROOT/'khorshid_tts_worker.py'
            env=os.environ.copy();env['PYTHONUNBUFFERED']='1'
            self.proc=subprocess.Popen([str(python),str(script)],cwd=ROOT,env=env,
                                       stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                                       text=True,encoding='utf-8',bufsize=1)
            proc=self.proc;events=self.events
            def reader():
                try:
                    for line in proc.stdout:
                        try:event=json.loads(line)
                        except ValueError:continue
                        if event.get('type')=='ready':
                            print('[TTS] Ready on '+event['device']+'; original voice loaded once.',flush=True)
                        else:events.put(event)
                finally:events.put({'type':'fatal','error':'TTS worker stopped'})
            threading.Thread(target=reader,name='khorshid-tts-events',daemon=True).start()
            print('[TTS] Loading your voice and models once...',flush=True)

    def close(self):
        proc=self.proc
        if proc is not None and proc.poll() is None:
            proc.terminate()
            try:proc.wait(timeout=2)
            except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=2)
        self.proc=None

    def speak(self,text,out='',play_it=True):
        from ultimate_khorshid.voice import audio as A
        with self.request_lock:
            self.start()
            request_id=uuid.uuid4().hex
            output=str(Path(out).resolve()) if out else A.tmp_wav('khorshid_pocket')
            with tempfile.TemporaryDirectory(prefix='khorshid_chunks_') as directory:
                request={'id':request_id,'text':text,'output':output,'directory':directory}
                try:
                    self.proc.stdin.write(json.dumps(request,ensure_ascii=False)+'\n')
                    self.proc.stdin.flush()
                    deadline=time.monotonic()+1200
                    while True:
                        remaining=deadline-time.monotonic()
                        if remaining<=0:raise TimeoutError('TTS generation timed out')
                        try:event=self.events.get(timeout=min(remaining,1))
                        except queue.Empty:continue
                        if event.get('type')=='fatal':raise RuntimeError(event.get('error'))
                        if event.get('id')!=request_id:continue
                        if event['type']=='error':raise RuntimeError(event['error'])
                        if event['type']=='chunk' and play_it:
                            path=Path(event['path']).resolve()
                            if path.parent!=Path(directory).resolve():raise RuntimeError('Invalid chunk path')
                            if not A.play(str(path)):raise RuntimeError('Original voice playback failed')
                        if event['type']=='done':return output
                except BaseException:
                    # No replay, no alternative voice, no orphan generation on cancellation.
                    self.close()
                    raise


_session=Session()
atexit.register(_session.close)

def warmup():
    _session.start()

def speak(text,out='',play_it=True):
    return _session.speak(text,out,play_it)
