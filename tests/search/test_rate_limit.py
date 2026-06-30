"""Tests for Google Flights ErrorResponse detection / surfacing."""

from __future__ import annotations

from pathlib import Path

import pytest

from fli.models.airport import Airport
from fli.models.google_flights.base import FlightSegment, PassengerInfo, TripType
from fli.models.google_flights.flights import FlightSearchFilters
from fli.search._wire import extract_error_session_id, is_rate_limit_response
from fli.search.dates import SearchDates
from fli.search.exceptions import GoogleFlightsRateLimited
from fli.search.flights import SearchFlights

FIXTURE = Path(__file__).parent / "fixtures" / "rate_limit_error.json"


@pytest.fixture
def rate_limit_body() -> str:
    """Return the captured ErrorResponse body."""
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture
def one_way_search_params() -> FlightSearchFilters:
    """Return a minimal one-way search filter."""
    from datetime import datetime, timedelta

    travel_date = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    segment = FlightSegment(
        departure_airport=[[Airport.JFK, 0]],
        arrival_airport=[[Airport.LAX, 0]],
        travel_date=travel_date,
    )
    return FlightSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=PassengerInfo(adults=1),
        flight_segments=[segment],
    )


def test_is_rate_limit_response_detects_error_envelope(rate_limit_body: str):
    """The marker substring must be detected inside an HTTP-200 body."""
    assert is_rate_limit_response(rate_limit_body) is True


def test_is_rate_limit_response_ignores_normal_response():
    """Normal shopping JSON should not trigger the rate-limit heuristic."""
    assert is_rate_limit_response(')]\'\n[["wrb.fr","abc",[1,2,3]]]') is False
    assert is_rate_limit_response("no payload here") is False
    assert is_rate_limit_response(b"\x00binary gibberish") is False


def test_extract_error_session_id_parses_session_id(rate_limit_body: str):
    """A session id from the error envelope should be extracted."""
    session_id = extract_error_session_id(rate_limit_body)
    assert session_id is not None
    assert session_id == "avU5aqPqKqioj8oP77Xy6Qc"


def test_extract_error_session_id_returns_none_for_normal_body():
    assert extract_error_session_id(')]\'\n[["wrb.fr","abc",[1,2,3]]]') is None


def test_flight_search_raises_rate_limited(
    monkeypatch, rate_limit_body: str, one_way_search_params: FlightSearchFilters
):
    """SearchFlights.search must raise GoogleFlightsRateLimited on ErrorResponse."""

    class FakeResponse:
        text = rate_limit_body
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(SearchFlights, "_capture_session_id", lambda self, inner: None)
    monkeypatch.setattr(
        "curl_cffi.requests.Session.post",
        lambda self, url, **kwargs: FakeResponse(),
    )

    client = SearchFlights()
    with pytest.raises(GoogleFlightsRateLimited) as exc_info:
        client.search(one_way_search_params)

    assert "ErrorResponse" in str(exc_info.value)
    assert exc_info.value.session_id == "avU5aqPqKqioj8oP77Xy6Qc"


def test_date_search_raises_rate_limited(
    monkeypatch, rate_limit_body: str, one_way_search_params: FlightSearchFilters
):
    """SearchDates.search must raise GoogleFlightsRateLimited on ErrorResponse."""

    class FakeResponse:
        text = rate_limit_body
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(
        "curl_cffi.requests.Session.post",
        lambda self, url, **kwargs: FakeResponse(),
    )

    from fli.models.google_flights.dates import DateSearchFilters

    date_filters = DateSearchFilters(
        trip_type=TripType.ONE_WAY,
        passenger_info=one_way_search_params.passenger_info,
        flight_segments=one_way_search_params.flight_segments,
        from_date=one_way_search_params.flight_segments[0].travel_date,
        to_date=one_way_search_params.flight_segments[0].travel_date,
    )

    client = SearchDates()
    with pytest.raises(GoogleFlightsRateLimited) as exc_info:
        client.search(date_filters)

    assert "ErrorResponse" in str(exc_info.value)
