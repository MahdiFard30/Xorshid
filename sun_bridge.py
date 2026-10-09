"""Import in Khorshid. Send state and PCM amplitude, never audio samples.

Call pcm() with short chunks AT PLAYBACK TIME, not during TTS generation.
"""
import json
import math
import os
import socket
import numpy as np


class SunBridge:
    def __init__(self, port=None):
        self.port = int(port or os.environ.get('KHORSHID_SUN_PORT', '47831'))
        self.token = os.environ.get('KHORSHID_SUN_TOKEN', '')
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def _send(self, **payload):
        payload['token'] = self.token
        try:
            self.sock.sendto(json.dumps(payload, allow_nan=False).encode(), ('127.0.0.1', self.port))
        except (OSError, ValueError):
            pass  # An absent overlay must never interrupt Khorshid.

    def state(self, state):
        if state not in ('idle', 'listening', 'thinking', 'speaking'):
            raise ValueError('Unknown sun state: ' + str(state))
        self._send(state=state)

    def level(self, normalized_rms):
        """Normalized RMS, 0..1; use only for the agent's OUTPUT audio."""
        value = float(normalized_rms)
        if math.isfinite(value):
            self._send(state='speaking', rms=max(0.0, min(1.0, value)))

    def pcm(self, samples, dtype=None):
        """PCM only. Bytes need explicit dtype, e.g. '<i2' for int16 LE.

        Float arrays must be normalized to [-1, 1]. Integer arrays are scaled
        automatically. Interleaved channels are supported. No MP3/WAV headers.
        """
        if isinstance(samples, (bytes, bytearray, memoryview)):
            if dtype is None:
                raise ValueError("For PCM bytes specify dtype='<i2' or the actual sample format")
            array = np.frombuffer(samples, dtype=dtype)
        else:
            array = np.asarray(samples, dtype=dtype)
        if not array.size:
            self.level(0)
            return
        kind = array.dtype.kind
        if kind == 'i':
            data = array.astype(np.float32) / float(-np.iinfo(array.dtype).min)
        elif kind == 'u' and array.dtype.itemsize == 1:
            data = (array.astype(np.float32) - 128) / 128
        elif kind == 'f':
            data = array.astype(np.float32)
        else:
            raise ValueError('Use signed integer PCM, uint8 PCM, or normalized float PCM')
        data = np.clip(np.nan_to_num(data, nan=0, posinf=0, neginf=0), -1, 1)
        self.level(float(np.sqrt(np.mean(data * data))))

    def close(self):
        self.sock.close()
