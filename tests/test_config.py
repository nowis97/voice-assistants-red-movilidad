import sys
import os
import json
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import config


def test_get_user_stops_fallback_default(monkeypatch, tmp_path):
    test_users_file = str(tmp_path / "users.json")
    monkeypatch.setattr(config, "USERS_FILE", test_users_file)

    users = {
        "user1": {
            "name": "Simón",
            "aliases": ["simon"],
            "card": "12345678",
            "stop": "PA345",
            "service": "513",
            "person_id": ""
        }
    }
    with open(test_users_file, "w", encoding="utf-8") as f:
        json.dump(users, f)

    stops_info = config.get_user_stops("user1")
    assert stops_info["ida"]["code"] == "PA345"
    assert stops_info["vuelta"]["code"] == "PA345"


def test_save_stops_pair_updates_user(monkeypatch, tmp_path):
    test_users_file = str(tmp_path / "users.json")
    monkeypatch.setattr(config, "USERS_FILE", test_users_file)

    users = {
        "user1": {
            "name": "Simón",
            "aliases": ["simon"],
            "card": "12345678",
            "stop": "PA345",
            "service": "513",
            "person_id": ""
        }
    }
    with open(test_users_file, "w", encoding="utf-8") as f:
        json.dump(users, f)

    stop_ida = {"code": "PC186", "name": "Avenida Apoquindo con El Bosque Norte"}
    stop_vuelta = {"code": "PC156", "name": "Avenida Apoquindo con El Bosque Sur"}

    success, msg, user = config.save_stops_pair(
        target_key="user1",
        stop_ida=stop_ida,
        stop_vuelta=stop_vuelta,
        intersection="Avenida Apoquindo con El Bosque"
    )

    assert success is True
    assert "PC186" in msg and "PC156" in msg
    assert user["stops"]["ida"]["code"] == "PC186"
    assert user["stops"]["vuelta"]["code"] == "PC156"
    assert user["stops"]["intersection"] == "Avenida Apoquindo con El Bosque"


def test_get_user_stops_with_stops_configured(monkeypatch, tmp_path):
    test_users_file = str(tmp_path / "users.json")
    monkeypatch.setattr(config, "USERS_FILE", test_users_file)

    users = {
        "user1": {
            "name": "Simón",
            "aliases": ["simon"],
            "card": "12345678",
            "stop": "PC186",
            "service": "513",
            "person_id": "",
            "stops": {
                "ida": {"code": "PC186", "name": "Apoquindo Norte", "direction": "de ida"},
                "vuelta": {"code": "PC156", "name": "Apoquindo Sur", "direction": "de regreso"},
                "intersection": "Apoquindo con El Bosque"
            }
        }
    }
    with open(test_users_file, "w", encoding="utf-8") as f:
        json.dump(users, f)

    stops_info = config.get_user_stops("user1")
    assert stops_info["ida"]["code"] == "PC186"
    assert stops_info["vuelta"]["code"] == "PC156"
    assert stops_info["intersection"] == "Apoquindo con El Bosque"


def test_save_stops_pair_single_stop(monkeypatch, tmp_path):
    test_users_file = str(tmp_path / "users.json")
    monkeypatch.setattr(config, "USERS_FILE", test_users_file)

    users = {
        "user1": {
            "name": "Simón",
            "aliases": ["simon"],
            "card": "12345678",
            "stop": "PA345",
            "service": "513",
            "person_id": ""
        }
    }
    with open(test_users_file, "w", encoding="utf-8") as f:
        json.dump(users, f)

    stop_ida = {"code": "PA345", "name": "Metro U de Chile"}

    success, msg, user = config.save_stops_pair(
        target_key="user1",
        stop_ida=stop_ida,
        stop_vuelta=None
    )

    assert success is True
    assert "Guardé el paradero PA345 para Simón" in msg
    assert user["stops"]["ida"]["code"] == "PA345"
    assert user["stops"]["vuelta"]["code"] == "PA345"
    assert user["stop"] == "PA345"


def test_get_user_stops_by_person_id(monkeypatch, tmp_path):
    test_users_file = str(tmp_path / "users.json")
    monkeypatch.setattr(config, "USERS_FILE", test_users_file)

    users = {
        "user1": {
            "name": "Simón",
            "aliases": ["simon"],
            "card": "12345678",
            "stop": "PA345",
            "service": "513",
            "person_id": "amzn1.ask.person.SIMON"
        },
        "user2": {
            "name": "María",
            "aliases": ["maria"],
            "card": "87654321",
            "stop": "PC186",
            "service": "506",
            "person_id": "amzn1.ask.person.MARIA",
            "stops": {
                "ida": {"code": "PC186", "name": "Apoquindo Norte", "direction": "de ida"},
                "vuelta": {"code": "PC156", "name": "Apoquindo Sur", "direction": "de regreso"},
                "intersection": "Apoquindo con El Bosque"
            }
        }
    }
    with open(test_users_file, "w", encoding="utf-8") as f:
        json.dump(users, f)

    stops_maria = config.get_user_stops(person_id="amzn1.ask.person.MARIA")
    assert stops_maria["ida"]["code"] == "PC186"
    assert stops_maria["vuelta"]["code"] == "PC156"

    stops_simon = config.get_user_stops(person_id="amzn1.ask.person.SIMON")
    assert stops_simon["ida"]["code"] == "PA345"
    assert stops_simon["vuelta"]["code"] == "PA345"


def test_save_stops_pair_target_by_alias(monkeypatch, tmp_path):
    test_users_file = str(tmp_path / "users.json")
    monkeypatch.setattr(config, "USERS_FILE", test_users_file)

    users = {
        "user1": {
            "name": "Simón",
            "aliases": ["simon", "yo"],
            "card": "12345678",
            "stop": "PA345",
            "service": "513",
            "person_id": ""
        },
        "user2": {
            "name": "María",
            "aliases": ["maria", "polola"],
            "card": "87654321",
            "stop": "PC186",
            "service": "506",
            "person_id": ""
        }
    }
    with open(test_users_file, "w", encoding="utf-8") as f:
        json.dump(users, f)

    stop_ida = {"code": "PD100", "name": "Plaza Egaña Norte"}
    stop_vuelta = {"code": "PD101", "name": "Plaza Egaña Sur"}

    success, msg, user = config.save_stops_pair(
        target_key="polola",
        stop_ida=stop_ida,
        stop_vuelta=stop_vuelta,
        intersection="Plaza Egaña"
    )

    assert success is True
    assert "PD100" in msg and "PD101" in msg
    assert user["name"] == "María"
    assert user["stops"]["ida"]["code"] == "PD100"
    assert user["stops"]["vuelta"]["code"] == "PD101"

