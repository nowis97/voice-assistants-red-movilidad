import io
import os
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import config
from src import google_cast_service


@pytest.fixture(autouse=True)
def clear_tts_buffer():
    google_cast_service.clear_tts_clips()
    yield
    google_cast_service.clear_tts_clips()


def test_config_exposes_google_home_settings():
    assert hasattr(config, "GOOGLE_OAUTH_CLIENT_ID")
    assert hasattr(config, "GOOGLE_OAUTH_CLIENT_SECRET")
    assert hasattr(config, "GOOGLE_OAUTH_PIN")
    assert hasattr(config, "GOOGLE_CAST_DEVICE")
    assert hasattr(config, "GOOGLE_CAST_HOST")
    assert hasattr(config, "LOCAL_SERVER_IP")
    assert isinstance(config.GOOGLE_WATCH_THRESHOLD_MINUTES, int)
    assert config.GOOGLE_WATCH_THRESHOLD_MINUTES >= 1


def test_cast_playback_max_wait_accommodates_tts_and_setup():
    assert google_cast_service.CAST_PLAYBACK_MAX_WAIT >= 35.0


def test_normalize_speech_for_tts_spaces_stop_codes_only():
    text = "La 401c llega al paradero PD289 y pa345 antes que la D03."
    normalized = google_cast_service.normalize_speech_for_tts(text)
    assert "P D 289" in normalized
    assert "P A 345" in normalized
    assert "401c" in normalized
    assert "D03" in normalized


def test_tts_ring_buffer_evicts_oldest_after_max_clips():
    def fake_gtts(text, lang="es"):
        inst = MagicMock()
        inst.write_to_fp.side_effect = lambda fp: fp.write(f"MP3:{text}".encode("utf-8"))
        return inst

    with patch("src.google_cast_service.gTTS", side_effect=fake_gtts):
        clip_ids = [google_cast_service.create_tts_clip(f"Mensaje {i}") for i in range(12)]

    # First 2 evicted, last 10 remain
    assert google_cast_service.get_tts_clip(clip_ids[0]) is None
    assert google_cast_service.get_tts_clip(clip_ids[1]) is None
    assert google_cast_service.get_tts_clip(clip_ids[2]) == b"MP3:Mensaje 2"
    assert google_cast_service.get_tts_clip(clip_ids[11]) == b"MP3:Mensaje 11"


def test_get_local_ip_prefers_config_override(monkeypatch):
    monkeypatch.setattr(config, "LOCAL_SERVER_IP", "192.168.0.115")
    assert google_cast_service.get_local_ip() == "192.168.0.115"


def test_list_cast_devices_extracts_info_and_stops_discovery():
    fake_cast_speaker = SimpleNamespace(
        cast_info=SimpleNamespace(
            friendly_name="Parlante Pieza",
            model_name="Google Home Mini",
            cast_type="audio",
            uuid="1111-2222",
            host="192.168.0.50",
            port=8009,
        )
    )
    fake_cast_tv = SimpleNamespace(
        cast_info=SimpleNamespace(
            friendly_name="Android TV",
            model_name="BRAVIA",
            cast_type="cast",
            uuid="3333-4444",
            host="192.168.0.60",
            port=8009,
        )
    )
    fake_browser = MagicMock()

    with patch(
        "src.google_cast_service.pychromecast.get_chromecasts",
        return_value=([fake_cast_speaker, fake_cast_tv], fake_browser),
    ), patch("src.google_cast_service.pychromecast.discovery.stop_discovery") as mock_legacy_stop:
        devices = google_cast_service.list_cast_devices(timeout=1.0)

    assert len(devices) == 2
    assert devices[0]["name"] == "Parlante Pieza"
    assert devices[0]["cast_type"] == "audio"
    assert devices[1]["name"] == "Android TV"
    fake_browser.stop_discovery.assert_called_once_with()
    mock_legacy_stop.assert_not_called()


def test_speak_on_home_fails_safely_when_device_name_empty(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CAST_DEVICE", "")
    with patch("src.google_cast_service.pychromecast.get_listed_chromecasts") as mock_discover:
        ok = google_cast_service.speak_on_home("Hola")
    assert ok is False
    mock_discover.assert_not_called()


def test_speak_on_home_ignores_non_matching_android_tv(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CAST_DEVICE", "Parlante Living")
    fake_tv = MagicMock()
    fake_tv.cast_info = SimpleNamespace(friendly_name="Android TV")
    fake_browser = MagicMock()

    with patch(
        "src.google_cast_service.pychromecast.get_listed_chromecasts",
        return_value=([fake_tv], fake_browser),
    ):
        ok = google_cast_service.speak_on_home("Hola")

    assert ok is False
    fake_tv.media_controller.play_media.assert_not_called()
    fake_browser.stop_discovery.assert_called_once_with()


def test_speak_on_home_plays_on_exact_speaker_and_cleans_up(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CAST_DEVICE", "Parlante Living")
    monkeypatch.setattr(config, "LOCAL_SERVER_IP", "192.168.0.115")
    monkeypatch.setattr(config, "PORT", 8000)

    fake_speaker = MagicMock()
    fake_speaker.cast_info = SimpleNamespace(friendly_name="Parlante Living")
    fake_speaker.media_controller.status = SimpleNamespace(player_state="IDLE")
    fake_browser = MagicMock()

    def fake_gtts(text, lang="es"):
        inst = MagicMock()
        inst.write_to_fp.side_effect = lambda fp: fp.write(b"FAKE_MP3")
        return inst

    with patch("src.google_cast_service.gTTS", side_effect=fake_gtts), patch(
        "src.google_cast_service.pychromecast.get_listed_chromecasts",
        return_value=([fake_speaker], fake_browser),
    ):
        ok = google_cast_service.speak_on_home("Tu micro viene en PD289")

    assert ok is True
    fake_speaker.wait.assert_called_once_with(timeout=5.0)
    play_args, _ = fake_speaker.media_controller.play_media.call_args
    assert play_args[0].startswith("http://192.168.0.115:8000/api/tts/")
    assert play_args[0].endswith(".mp3")
    assert play_args[1] == "audio/mpeg"
    fake_speaker.media_controller.block_until_active.assert_called_once_with(timeout=5.0)
    fake_speaker.disconnect.assert_called_once_with(timeout=2.0)
    fake_browser.stop_discovery.assert_called_once_with()


def test_speak_on_home_stops_discovery_on_cast_exception(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CAST_DEVICE", "Parlante Living")
    fake_speaker = MagicMock()
    fake_speaker.cast_info = SimpleNamespace(friendly_name="Parlante Living")
    fake_speaker.wait.side_effect = RuntimeError("Socket timeout")
    fake_browser = MagicMock()

    with patch(
        "src.google_cast_service.pychromecast.get_listed_chromecasts",
        return_value=([fake_speaker], fake_browser),
    ):
        ok = google_cast_service.speak_on_home("Hola")

    assert ok is False
    fake_speaker.disconnect.assert_called_once_with(timeout=2.0)
    fake_browser.stop_discovery.assert_called_once_with()


def test_speak_on_home_waits_for_playback_settle_window(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CAST_DEVICE", "Parlante Living")
    monkeypatch.setattr(config, "LOCAL_SERVER_IP", "192.168.0.115")
    monkeypatch.setattr(config, "PORT", 8000)

    fake_speaker = MagicMock()
    fake_speaker.cast_info = SimpleNamespace(friendly_name="Parlante Living")

    states = ["IDLE", "IDLE", "PLAYING", "PLAYING", "IDLE"]
    state_iter = iter(states)

    class DynamicStatus:
        @property
        def player_state(self):
            try:
                return next(state_iter)
            except StopIteration:
                return "IDLE"

    fake_speaker.media_controller.status = DynamicStatus()
    fake_browser = MagicMock()

    sleep_calls = []

    def mock_sleep(seconds):
        sleep_calls.append(seconds)

    def fake_gtts(text, lang="es"):
        inst = MagicMock()
        inst.write_to_fp.side_effect = lambda fp: fp.write(b"FAKE_MP3")
        return inst

    with patch("src.google_cast_service.gTTS", side_effect=fake_gtts), \
         patch("src.google_cast_service.pychromecast.get_listed_chromecasts", return_value=([fake_speaker], fake_browser)), \
         patch("src.google_cast_service.time.sleep", side_effect=mock_sleep):
        ok = google_cast_service.speak_on_home("Mensaje de prueba")

    assert ok is True
    # Verifies settle poll occurred (0.1s) and then active playback wait (0.25s)
    assert 0.1 in sleep_calls
    assert 0.25 in sleep_calls
    fake_speaker.disconnect.assert_called_once_with(timeout=2.0)
    fake_browser.stop_discovery.assert_called_once_with()


def test_list_cast_devices_passes_known_hosts_when_configured(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CAST_HOST", "192.168.0.103, 192.168.0.104 , ")
    fake_browser = MagicMock()

    with patch(
        "src.google_cast_service.pychromecast.get_chromecasts",
        return_value=([], fake_browser),
    ) as mock_discover:
        devices = google_cast_service.list_cast_devices(timeout=1.5)

    assert devices == []
    mock_discover.assert_called_once_with(
        timeout=1.5,
        known_hosts=["192.168.0.103", "192.168.0.104"],
    )
    fake_browser.stop_discovery.assert_called_once_with()


def test_list_cast_devices_omits_known_hosts_when_empty(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CAST_HOST", "  , ")
    fake_browser = MagicMock()

    with patch(
        "src.google_cast_service.pychromecast.get_chromecasts",
        return_value=([], fake_browser),
    ) as mock_discover:
        devices = google_cast_service.list_cast_devices(timeout=1.5)

    assert devices == []
    assert "known_hosts" not in mock_discover.call_args.kwargs


def test_speak_on_home_passes_and_omits_known_hosts(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CAST_DEVICE", "Comedor")
    fake_browser = MagicMock()

    monkeypatch.setattr(config, "GOOGLE_CAST_HOST", "192.168.0.103, 192.168.0.104")
    with patch(
        "src.google_cast_service.pychromecast.get_listed_chromecasts",
        return_value=([], fake_browser),
    ) as mock_listed:
        assert google_cast_service.speak_on_home("Hola") is False
    mock_listed.assert_called_once_with(
        friendly_names=["Comedor"],
        discovery_timeout=google_cast_service.CAST_DISCOVERY_TIMEOUT,
        known_hosts=["192.168.0.103", "192.168.0.104"],
    )

    monkeypatch.setattr(config, "GOOGLE_CAST_HOST", "")
    with patch(
        "src.google_cast_service.pychromecast.get_listed_chromecasts",
        return_value=([], fake_browser),
    ) as mock_listed_empty:
        assert google_cast_service.speak_on_home("Hola") is False
    assert "known_hosts" not in mock_listed_empty.call_args.kwargs


def test_list_cast_devices_falls_back_to_legacy_stop_discovery_without_method():
    legacy_browser = SimpleNamespace()

    with patch(
        "src.google_cast_service.pychromecast.get_chromecasts",
        return_value=([], legacy_browser),
    ), patch("src.google_cast_service.pychromecast.discovery.stop_discovery") as mock_legacy_stop:
        devices = google_cast_service.list_cast_devices(timeout=1.0)

    assert devices == []
    mock_legacy_stop.assert_called_once_with(legacy_browser)
