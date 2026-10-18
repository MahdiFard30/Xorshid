"""Audio mixer state, independent of hardware and real user playback."""
from copy import deepcopy
import os
import threading
import time

import pytest

from ultimate_khorshid.voice import ducking


def stream(index=1, pid='999999', levels=(50000, 30000), name='Browser'):
    return {'index': index, 'client': index+10, 'channel_map': 'front-left,front-right',
            'properties': {'application.process.id': pid, 'application.name': name},
            'volume': {str(i): {'value': value} for i, value in enumerate(levels)}, 'mute': False}


class Mixer:
    def __init__(self, *streams):
        self.data = {s['index']: s for s in streams}
        self.calls = []

    def streams(self):
        return deepcopy(list(self.data.values()))

    def volume(self, index, values):
        self.calls.append((index, values))
        for channel, value in zip(self.data[index]['volume'].values(), values):
            channel['value'] = value


def test_restore_original_stereo_levels_without_changing_mute_or_own_voice():
    media = stream(); media['mute'] = True
    tagged = stream(4, name='ALSA plug-in [aplay]')
    tagged['properties']['khorshid.voice']='1'
    mixer = Mixer(media, stream(2, str(os.getpid())), stream(3, name='Khorshid'), tagged)
    ducker = ducking.StreamDucker(mixer)
    ducker.refresh(); ducker.refresh()
    assert mixer.calls == [(1, (6000, 3600))]
    assert mixer.data[1]['mute']
    ducker.restore()
    assert mixer.calls[-1] == (1, (50000, 30000))
    assert not ducker.saved


def test_manual_volume_change_is_not_overwritten():
    mixer = Mixer(stream())
    ducker = ducking.StreamDucker(mixer)
    ducker.refresh()
    mixer.volume(1, (20000, 20000))
    ducker.refresh(); ducker.restore()
    assert ducking._levels(mixer.data[1]) == (20000, 20000)
    assert len(mixer.calls) == 2


def test_new_streams_and_reused_indices_do_not_restore_someone_elses_volume():
    mixer = Mixer(stream())
    ducker = ducking.StreamDucker(mixer)
    ducker.refresh()
    mixer.data[1] = stream(pid='888888', levels=(10000, 10000))
    mixer.data[2] = stream(2)
    ducker.refresh(); ducker.restore()
    assert ducking._levels(mixer.data[1]) == (10000, 10000)
    assert ducking._levels(mixer.data[2]) == (50000, 30000)


def test_disappeared_stream_is_harmless():
    mixer = Mixer(stream())
    ducker = ducking.StreamDucker(mixer)
    ducker.refresh(); mixer.data.clear(); ducker.restore()
    assert not ducker.saved


def test_retry_failed_restore_without_losing_original_levels():
    mixer = Mixer(stream())
    ducker = ducking.StreamDucker(mixer)
    ducker.refresh()
    original = mixer.volume
    mixer.volume = lambda *args: (_ for _ in ()).throw(OSError('gone temporarily'))
    ducker.restore()
    assert ducker.saved
    mixer.volume = original
    ducker.restore()
    assert ducking._levels(mixer.data[1]) == (50000, 30000)


def test_nested_leases_hold_ducking_until_last_voice_finishes():
    mixer = Mixer(stream())
    service = ducking.DuckingService(mixer)
    try:
        first = service.hold(); assert first.ready.wait(1)
        second = service.hold(); assert second.ready.wait(1)
        first.close()
        assert ducking._levels(mixer.data[1]) == (6000, 3600)
        second.close()
        assert ducking._levels(mixer.data[1]) == (50000, 30000)
    finally:
        service.close()


def test_worker_ducks_new_stream_during_speech_and_restores_on_shutdown():
    mixer = Mixer()
    service = ducking.DuckingService(mixer)
    lease = service.hold(); assert lease.ready.wait(1)
    mixer.data[1] = stream()
    deadline = time.monotonic()+1
    while not mixer.calls and time.monotonic()<deadline:
        threading.Event().wait(.01)
    service.close()
    assert mixer.calls == [(1, (6000, 3600)), (1, (50000, 30000))]


def test_exception_in_voice_playback_restores_volume(monkeypatch):
    mixer = Mixer(stream())
    service = ducking.DuckingService(mixer)
    monkeypatch.setattr(ducking, 'service', service)
    try:
        with pytest.raises(RuntimeError), ducking.duck_other_audio():
            assert ducking._levels(mixer.data[1]) == (6000, 3600)
            raise RuntimeError('cancelled')
        assert ducking._levels(mixer.data[1]) == (50000, 30000)
    finally:
        service.close()


def test_unavailable_audio_server_does_not_block_speech():
    class Unavailable(Mixer):
        def streams(self):
            raise OSError('no PulseAudio server')
    service = ducking.DuckingService(Unavailable())
    try:
        lease = service.hold()
        assert lease.ready.wait(1)
        lease.close()
    finally:
        service.close()


def test_voice_child_tag_does_not_modify_global_environment():
    original = os.environ.get('PULSE_PROP_application.name')
    assert ducking.voice_environment()['PULSE_PROP_application.name'] == 'Khorshid'
    assert ducking.voice_environment()['PULSE_PROP_khorshid.voice'] == '1'
    assert os.environ.get('PULSE_PROP_application.name') == original
