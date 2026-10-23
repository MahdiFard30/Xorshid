import hashlib
import json

import pytest

from scripts import install_news_bridge as installer


@pytest.fixture
def setup(tmp_path,monkeypatch):
    root=tmp_path/'project';artifacts=root/'mt5';artifacts.mkdir(parents=True)
    terminal=tmp_path/'terminal';(terminal/'MQL5').mkdir(parents=True)
    for name in installer.NAMES:(artifacts/name).write_bytes(name.encode())
    manifest={key:hashlib.sha256((artifacts/name).read_bytes()).hexdigest() for key,name in zip(
        ('news_bridge_source_sha256','news_bridge_binary_sha256'),installer.NAMES)}
    (artifacts/'recovery-build.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(installer,'ROOT',root)
    return terminal,artifacts


def test_install_is_idempotent_and_never_starts_or_changes_chart_experts(setup):
    terminal,artifacts=setup
    experts=terminal/'MQL5/Experts';experts.mkdir();(experts/'robot.ex5').write_bytes(b'active robot')
    result=installer.install(terminal)
    assert not result['started'] and not result['trade_operations']
    assert installer.install(terminal)==result
    assert (experts/'robot.ex5').read_bytes()==b'active robot'


def test_tampered_service_build_cannot_be_installed(setup):
    terminal,artifacts=setup
    (artifacts/installer.NAMES[1]).write_bytes(b'tampered')
    with pytest.raises(ValueError,match='hashes'):installer.install(terminal)


def test_existing_modified_service_is_preserved(setup):
    terminal,artifacts=setup
    target=terminal/'MQL5/Services';target.mkdir()
    (target/installer.NAMES[0]).write_text('user edits')
    with pytest.raises(ValueError,match='differs'):installer.install(terminal)
    assert (target/installer.NAMES[0]).read_text()=='user edits'


def test_partial_failure_rolls_back_only_new_service_files(setup,monkeypatch):
    terminal,artifacts=setup
    original=installer.os.replace;calls=[]
    def fail(source,dest):
        calls.append(1)
        if len(calls)==2:raise OSError('disk error')
        return original(source,dest)
    monkeypatch.setattr(installer.os,'replace',fail)
    with pytest.raises(OSError):installer.install(terminal)
    assert not any((terminal/'MQL5/Services').iterdir())
