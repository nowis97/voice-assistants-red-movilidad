import pytest
import time
from unittest.mock import patch, MagicMock
from src.bus_watcher import BusWatcherManager, WatcherJob


def test_bus_watcher_start_and_cancel():
    manager = BusWatcherManager(poll_interval_seconds=1)
    job = manager.start_watch(
        user_id="user_123",
        linea="513",
        stop_code="PD289",
        corner_name="José Arrieta con Ictinos",
        threshold_minutes=5,
        api_endpoint="https://api.amazonalexa.com",
        api_access_token="token_abc"
    )
    assert job.user_id == "user_123"
    assert job.linea == "513"
    assert job.threshold_minutes == 5
    assert manager.has_active_job("user_123") is True

    cancelled = manager.cancel_watch("user_123")
    assert cancelled is True
    assert manager.has_active_job("user_123") is False

    # Second cancel returns False
    assert manager.cancel_watch("user_123") is False


def test_bus_watcher_triggers_reminder_when_in_range():
    manager = BusWatcherManager(poll_interval_seconds=0.05)

    mock_pred = {
        "success": True,
        "buses": [
            {"service": "513", "min_time": 4, "max_time": 4, "meters": 800}
        ]
    }

    with patch("src.red_service.get_stop_predictions", return_value=mock_pred), \
         patch("src.reminders_service.create_spoken_reminder", return_value={"success": True}) as mock_remind:

        job = manager.start_watch(
            user_id="user_456",
            linea="513",
            stop_code="PD289",
            corner_name="José Arrieta con Ictinos",
            threshold_minutes=5,
            api_endpoint="https://api.amazonalexa.com",
            api_access_token="token_xyz"
        )

        # Wait for worker thread to evaluate
        time.sleep(0.2)
        assert mock_remind.called
        assert manager.has_active_job("user_456") is False


def test_bus_watcher_waits_when_above_threshold():
    manager = BusWatcherManager(poll_interval_seconds=0.05)

    mock_pred = {
        "success": True,
        "buses": [
            {"service": "513", "min_time": 12, "max_time": 15, "meters": 3500}
        ]
    }

    with patch("src.red_service.get_stop_predictions", return_value=mock_pred), \
         patch("src.reminders_service.create_spoken_reminder") as mock_remind:

        job = manager.start_watch(
            user_id="user_waiting",
            linea="513",
            stop_code="PD289",
            corner_name="José Arrieta",
            threshold_minutes=5,
            api_endpoint="https://api.amazonalexa.com",
            api_access_token="token_xyz"
        )

        time.sleep(0.15)
        # Should NOT trigger yet
        assert not mock_remind.called
        assert manager.has_active_job("user_waiting") is True

        # Clean up
        manager.cancel_watch("user_waiting")
        assert manager.has_active_job("user_waiting") is False


def test_bus_watcher_get_active_jobs():
    manager = BusWatcherManager(poll_interval_seconds=10)
    manager.start_watch(
        user_id="user_active_list",
        linea="508",
        stop_code="PD289",
        corner_name="José Arrieta",
        threshold_minutes=5,
        api_endpoint="https://api.amazonalexa.com",
        api_access_token="token_xyz"
    )
    active = manager.get_active_jobs()
    assert len(active) == 1
    assert active[0]["linea"] == "508"
    assert active[0]["user_id"] == "user_active_list"

    manager.cancel_watch("user_active_list")
    assert len(manager.get_active_jobs()) == 0
