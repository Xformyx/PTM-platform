"""The declared PhosX directory is ignored unless the round 09 bytes are present."""
from ptm_shared.phosx_registered_resource import locate_declared_phosx_manifest


def test_missing_or_wrong_bytes_do_not_register(tmp_path):
    assert locate_declared_phosx_manifest(tmp_path) is None
    root = tmp_path / "phosx-0.23.1-b556f59"
    root.mkdir()
    (root / "manifest.json").write_text("{}")
    assert locate_declared_phosx_manifest(tmp_path) is None
