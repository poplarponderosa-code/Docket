import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from docket import __version__, updates     # noqa: E402


def test_versions():
    assert updates.parse_version("v1.2.10") == (1, 2, 10)
    assert updates.is_newer("v1.2.0", "1.1.0") and not updates.is_newer("v1.1.0", "1.1.0")
    assert updates.is_newer("v1.10.0", "1.9.3") and not updates.is_newer("v1.0.9", __version__)


def test_release_parsing_and_asset():
    body = (b'{"tag_name": "v1.2.0", "html_url": "https://github.com/x/y/releases/tag/v1.2.0", "assets": ['
            b'{"name": "notes.txt", "browser_download_url": "u1"},'
            b'{"name": "Docket-Setup-1.2.0.exe", "browser_download_url": "https://e/Docket-Setup-1.2.0.exe"}]}')
    rel = updates.parse_release(body)
    assert rel["tag_name"] == "v1.2.0"
    assert updates.pick_installer(rel) == ("Docket-Setup-1.2.0.exe", "https://e/Docket-Setup-1.2.0.exe")
    assert updates.parse_release(b"not json") is None and updates.parse_release(b'{"message": "Not Found"}') is None
    assert updates.download_path("Docket Setup?.exe").name == "Docket_Setup_.exe"
