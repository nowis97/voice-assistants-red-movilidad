import pytest
from src.location_service import (
    clean_intersection_name,
    find_opposing_stop,
    find_stops_by_intersection,
)


def test_clean_intersection_name_standard():
    raw = "PC186-Avenida Apoquindo / Esq. El Bosque Norte"
    cleaned = clean_intersection_name(raw)
    assert cleaned == "Avenida Apoquindo con El Bosque Norte"


def test_clean_intersection_name_abbreviations():
    raw = "PD184-Av. Grecia / Esq. Salvador"
    cleaned = clean_intersection_name(raw)
    assert cleaned == "Avenida Grecia con Salvador"


def test_clean_intersection_name_metro():
    raw = "PA345-Parada 4 / (M) Universidad De Chile"
    cleaned = clean_intersection_name(raw)
    assert "Metro Universidad De Chile" in cleaned
    assert "PA345" not in cleaned


def test_find_opposing_stop_pc186():
    # PC186 (Apoquindo / El Bosque Norte) tiene a PC156 enfrente en Av. Apoquindo
    opposing = find_opposing_stop("PC186")
    assert opposing is not None
    assert opposing["code"] == "PC156"
    assert "Apoquindo" in opposing["name"]
    assert opposing["distance_meters"] < 250


def test_find_stops_by_intersection_apoquindo_bosque():
    ida, vuelta = find_stops_by_intersection("Apoquindo", "Bosque")
    assert ida is not None
    assert ida["code"] == "PC186"
    assert vuelta is not None
    assert vuelta["code"] == "PC156"


def test_find_stops_by_intersection_not_found():
    ida, vuelta = find_stops_by_intersection("CalleFalsaInexistente999", "OtraCalle")
    assert ida is None
    assert vuelta is None
