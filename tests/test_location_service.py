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


def test_clean_spoken_stop_code_standard():
    from src.location_service import clean_spoken_stop_code
    assert clean_spoken_stop_code("PD184") == "P D 184"
    assert clean_spoken_stop_code("PA345") == "P A 345"
    assert clean_spoken_stop_code("PC2") == "P C 2"


def test_clean_spoken_stop_code_edge_cases():
    from src.location_service import clean_spoken_stop_code
    assert clean_spoken_stop_code("") == ""
    assert clean_spoken_stop_code("METRO") == "METRO"


def test_normalize_destination_query():
    from src.location_service import normalize_destination_query
    q1 = normalize_destination_query("Pedro de Valdivia con Providencia")
    assert "Pedro de Valdivia / Providencia" in q1
    assert "Santiago, Chile" in q1

    q2 = normalize_destination_query("Grecia y Salvador")
    assert "Grecia / Salvador" in q2
    assert "Santiago, Chile" in q2

    q3 = normalize_destination_query("Apoquindo 1234")
    assert "Apoquindo 1234" in q3
    assert "Santiago, Chile" in q3

    q4 = normalize_destination_query("al Costanera Center")
    assert q4.startswith("Costanera Center")
    assert "al Costanera" not in q4

    q5 = normalize_destination_query("el Costanera Center")
    assert q5.startswith("Costanera Center")
    assert "el Costanera" not in q5


def test_find_stops_by_intersection_accent_insensitive_jose_arrieta():
    ida, vuelta = find_stops_by_intersection("jose arrieta", "ictinos")
    assert ida is not None
    assert ida["code"] == "PD289"
    assert "Arrieta" in ida["name"]
    assert vuelta is not None
    assert vuelta["code"] == "PD260"


