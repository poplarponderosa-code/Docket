import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docket import companions   # noqa: E402


def test_find_in_usual_folder(tmp_path, monkeypatch):
    led = companions.get("ledger")
    assert led is not None and led.releases_url == "https://github.com/poplarponderosa-code/Docket-Ledger/releases/latest"
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("ProgramFiles", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    assert companions.find(led) is None
    exe = tmp_path / "Programs" / "Docket Ledger" / "DocketLedger.exe"
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    assert companions.find(led) == exe


def test_shared_file_keeps_other_keys(tmp_path):
    (tmp_path / "shared.json").write_text('{"ledger_seen": true}', encoding="utf-8")
    companions.write_shared(tmp_path, {"timelog_dir": "C:/Logs", "docket_version": "1.2.0"})
    data = json.loads((tmp_path / "shared.json").read_text(encoding="utf-8"))
    assert data == {"ledger_seen": True, "timelog_dir": "C:/Logs", "docket_version": "1.2.0"}
    (tmp_path / "shared.json").write_text("not json", encoding="utf-8")
    companions.write_shared(tmp_path, {"timelog_dir": "D:/x"})
    assert json.loads((tmp_path / "shared.json").read_text(encoding="utf-8")) == {"timelog_dir": "D:/x"}


def test_modes():
    from docket import companions
    assert [c.key for c in companions.for_mode("pro")] == ["ledger"]
    assert companions.for_mode("basic") == [] and companions.for_mode("advanced") == []
    assert [c.key for c in companions.suits_exactly("pro")] == ["ledger"]
    led = companions.get("ledger")
    assert led.api_latest.endswith("/Docket-Ledger/releases/latest") and led.description and led.features
