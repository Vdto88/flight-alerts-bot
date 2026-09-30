import json
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from miles.cycle import run, search_plan, select
from miles.model import Award
from miles.providers import parse_latam, parse_smiles
from scripts.encrypt_deals import main as encrypt, decrypt_bytes


def award(points=20000, **kwargs):
    return Award("azul", "CNF", "CGH", "2026-12-21", points,
                 "https://passagens.voeazul.com.br/pt/buscador-de-pontos", **kwargs)


PLAN = {("CNF", "CGH"): {"2026-12-21", "2026-12-22"}}


def test_plan_shares_routes_windows_and_far_dates():
    plan = search_plan(date(2026, 9, 30))
    assert ("CNF", "CGH") in plan and ("CGH", "CNF") in plan
    assert "2026-10-01" in plan[("CNF", "IGU")]  # configured extra window
    assert "2027-02-15" in plan[("CNF", "BRC")]
    assert "2027-02-15" not in plan[("CNF", "CGH")]
    assert "2027-02-15" in search_plan(date(2026, 9, 30), True)[("CNF", "CGH")]


def test_selection_dedup_does_not_mix_membership_or_roundtrip():
    rows = [award(), award(18000), award(12000, condition="Clube"),
            award(24000, return_date="2026-12-22"),
            award(25000, return_date="2026-12-23")]
    assert sorted(o.points for o in select(rows, PLAN)) == [12000, 18000, 24000]


def test_latam_cash_taxes_are_not_award_taxes_and_missing_points_are_ignored():
    deal = {"originIataCode": "CNF", "destinationIataCode": "FLN", "typeOfTrip": "oneway",
            "priceTrip": {"outboundDate": "2026-12-21", "totalLoyaltyAmount": 10475,
                          "totalPrice": 390.05, "taxesPrice": 35.15},
            "cabinData": {"cabinCode": "Economy"}}
    offers = parse_latam({"deals": [deal, {**deal, "priceTrip": {"totalPrice": 300}}]})
    assert len(offers) == 1 and offers[0].points == 10475
    assert offers[0].taxes_brl is None


def test_smiles_filters_other_airlines_keeps_club_distinct_and_per_segment():
    row = {"Cia": "GOL", "iata_origem": "CGH", "iata_destino": "CNF",
           "data_saida": "21/12/2026", "Clube": "16.300", "Smiles": "20.000",
           "Links": "https://www.smiles.com.br/?returnDate=1798513199000"}
    offers = parse_smiles([row, {**row, "Cia": "Azul"}], "https://www.smiles.com.br/passagens")
    assert [o.points for o in offers] == [16300, 20000]
    assert len({o.key for o in offers}) == 2
    assert all(o.return_date is None for o in offers)


@pytest.mark.asyncio
async def test_first_collection_then_fall_and_duplicate_delivery(tmp_path):
    sender = AsyncMock(return_value=True)
    current = [award()]
    provider = lambda plan: (current, {"status": "ok"})
    args = dict(plan=PLAN, provider_map={"azul": provider}, sender=sender, notify=True,
                state_path=tmp_path / "state.json", output_path=tmp_path / "miles.json")
    await run(**args)
    sender.assert_not_called()
    current[:] = [award(15000)]
    await run(**args)
    assert sender.call_count == 1 and sender.call_args.args[1] == 20000
    current[:] = [award(18000)]
    await run(**args)
    current[:] = [award(15000)]
    await run(**args)
    assert sender.call_count == 1


@pytest.mark.asyncio
async def test_failed_delivery_retried_source_failure_isolated_and_preview_readonly(tmp_path):
    current = [award()]
    provider = lambda plan: (current, {"status": "ok"})
    sender = AsyncMock(side_effect=[False, True])
    args = dict(plan=PLAN, provider_map={"azul": provider}, sender=sender,
                state_path=tmp_path / "state.json", output_path=tmp_path / "miles.json")
    await run(**args)
    assert not args["state_path"].exists()
    await run(**args, notify=True)
    current[:] = [award(15000)]
    await run(**args, notify=True)
    await run(**args, notify=True)
    assert sender.call_count == 2
    before = args["state_path"].read_bytes()
    await run(**args)
    assert args["state_path"].read_bytes() == before
    def broken(plan):
        raise ValueError("source failed")
    args["provider_map"]["gol"] = broken
    result = await run(**args, notify=True)
    assert result["programs"]["gol"]["status"] == "error"
    assert len(result["programs"]["azul"]["offers"]) == 1


@pytest.mark.asyncio
async def test_expired_baseline_does_not_trigger_false_fall(tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"prices": {award().key: {"points": 50000,
         "seen_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()}}, "sent": {}}))
    sender = AsyncMock(return_value=True)
    await run(plan=PLAN, provider_map={"azul": lambda p: ([award()], {"status": "ok"})},
              sender=sender, notify=True, state_path=state, output_path=tmp_path / "miles.json")
    sender.assert_not_called()


def test_miles_encrypted_with_same_panel_password(tmp_path):
    (tmp_path / "deals.json").write_text('{"deals": []}')
    (tmp_path / "miles.json").write_text('{"programs": {"azul": {"offers": []}}}')
    encrypt("test-password", str(tmp_path))
    encrypted = json.loads((tmp_path / "miles.enc.json").read_text())
    assert json.loads(decrypt_bytes(encrypted, "test-password"))["programs"]["azul"]["offers"] == []
