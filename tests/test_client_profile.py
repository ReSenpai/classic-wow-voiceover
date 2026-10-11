import pytest

from voru.config import ClientProfile, load_client_profile


def test_repo_client_profile_matches_target_client():
    profile = load_client_profile()

    assert profile == ClientProfile(
        flavor="vanilla",
        version="1.15.9",
        build=70003,
        interface=11509,
        locale="ruRU",
    )


def test_missing_field_is_reported_by_name(tmp_path):
    path = tmp_path / "client.yaml"
    path.write_text("flavor: vanilla\nversion: 1.15.9\nbuild: 70003\nlocale: ruRU\n", encoding="utf-8")

    with pytest.raises(ValueError, match="interface"):
        load_client_profile(path)
