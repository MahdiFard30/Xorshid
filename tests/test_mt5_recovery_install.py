import hashlib
import json

import pytest

from scripts import install_mt5_recovery as installer


@pytest.fixture
def installation(tmp_path,monkeypatch):
    artifacts=tmp_path/'artifacts'; artifacts.mkdir()
    target=tmp_path/'Experts'; target.mkdir()
    old={name:('old-'+name).encode() for name in installer.NAMES}
    for name in installer.NAMES:
        (artifacts/name).write_bytes(('new-'+name).encode())
        (target/name).write_bytes(old[name])
    manifest={field:hashlib.sha256((artifacts/name).read_bytes()).hexdigest() for field,name in
              [('source_sha256',installer.NAMES[1]),('binary_sha256',installer.NAMES[2]),('policy_sha256',installer.NAMES[0])]}
    manifest['previous_source_sha256']=hashlib.sha256(old[installer.NAMES[1]]).hexdigest()
    (artifacts/'recovery-build.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(installer,'ROOT',tmp_path)
    monkeypatch.setattr(installer,'ARTIFACTS',artifacts)
    monkeypatch.setattr(installer,'terminal_running',lambda:False)
    monkeypatch.setattr(installer,'workers_running',lambda:False)
    return target,artifacts,old


@pytest.mark.parametrize('active',['terminal_running','workers_running'])
def test_installer_refuses_active_terminal_or_worker(installation,monkeypatch,active):
    target,_,old=installation
    monkeypatch.setattr(installer,active,lambda:True)
    with pytest.raises(ValueError): installer.install(target)
    assert {name:(target/name).read_bytes() for name in old}==old


def test_installer_backs_up_files_and_does_not_touch_stop_markers(installation):
    target,artifacts,old=installation
    marker=target/'stop.flag'; marker.write_text('User requested stop')
    backup=installer.install(target)
    assert {name:(backup/name).read_bytes() for name in old}==old
    assert all((target/name).read_bytes()==(artifacts/name).read_bytes() for name in old)
    assert marker.read_text()=='User requested stop'


def test_modified_installed_source_not_overwritten(installation):
    target,_,_=installation
    (target/'KhorshidMultiTrader.mq5').write_text('user edits')
    with pytest.raises(ValueError): installer.install(target)
    assert (target/'KhorshidMultiTrader.mq5').read_text()=='user edits'


def test_tampered_build_not_installed(installation):
    target,artifacts,old=installation
    (artifacts/'KhorshidMultiTrader.ex5').write_bytes(b'changed')
    with pytest.raises(ValueError): installer.install(target)
    assert {name:(target/name).read_bytes() for name in old}==old


def test_partial_install_failure_restores_old_files(installation,monkeypatch):
    target,_,old=installation
    original=installer._replace
    calls=0
    def fail_once(path,data):
        nonlocal calls
        calls+=1
        if calls==2: raise OSError('simulated disk failure')
        original(path,data)
    monkeypatch.setattr(installer,'_replace',fail_once)
    with pytest.raises(OSError): installer.install(target)
    assert {name:(target/name).read_bytes() for name in old}==old
