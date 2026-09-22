from datetime import datetime, timezone

import pytest

from promos.classify import Classification, classify, normalize
from promos.feeds import FeedItem


def item(title: str, summary: str = "") -> FeedItem:
    return FeedItem(guid=title, title=title, summary=summary, link="https://example.com/x",
                    source="Teste", categories=(), published_at=datetime(2026, 9, 21, tzinfo=timezone.utc))


def test_normalize_strips_accents_and_lowercases():
    assert normalize("Milão, SÃO LUÍS e Florianópolis") == "milao, sao luis e florianopolis"


def test_italy_sale_is_a_fare_with_both_cities_in_text_order():
    c, reason = classify(item("Itália nas férias! Voos para Roma ou Milão a partir de R$ 4.270 ida e volta"))
    assert c == Classification(kind="fare", destinations=("Itália", "Roma", "Milão"), programs=(),
                               from_bh=False, origin_unknown=True)
    assert reason == "fare:destination:Itália"


def test_generic_national_sale_passes_with_origin_unknown():
    c, reason = classify(item("Ofertas do fim de semana! Passagens nacionais a partir de R$ 336 "
                              "ida e volta com Azul, Gol e Latam"))
    assert c is not None and c.kind == "fare"
    assert c.destinations == () and c.origin_unknown and not c.from_bh
    assert reason == "fare:generic:nacionais"


def test_generic_sale_listing_other_cities_still_passes():
    c, _ = classify(item("Passagens nacionais em promoção", "Trechos para Salvador, Recife e Fortaleza."))
    assert c is not None and c.origin_unknown


def test_home_city_sets_from_bh():
    c, reason = classify(item("Voos saindo de Belo Horizonte para Miami a partir de R$ 2.100"))
    assert c is not None and c.from_bh and not c.origin_unknown
    assert reason == "fare:home"


@pytest.mark.parametrize("home", ["BH", "Confins", "CNF", "belo horizonte"])
def test_every_home_term_counts(home):
    c, _ = classify(item(f"Passagens em promoção saindo de {home}"))
    assert c is not None and c.from_bh


def test_news_about_new_flights_is_rejected_even_with_a_configured_city():
    c, reason = classify(item(
        "Acabou a escala! British Airways terá voos exclusivos entre Londres e Rio de Janeiro a partir de 2027",
        "A British Airways anunciou mudanças e passará a oferecer um voo diário sem escalas."))
    assert c is None and reason == "rejected:no-offer-signal"


def test_non_flight_posts_are_rejected():
    c, reason = classify(item("Começa hoje! Oktoberfest São Paulo volta ao Ibirapuera com muito chope"))
    assert c is None and reason == "rejected:no-fare-word"


def test_hotel_price_without_a_fare_word_is_rejected():
    c, reason = classify(item("Hotéis em Roma com diárias a partir de R$ 300"))
    assert c is None and reason == "rejected:no-fare-word"


def test_sale_to_a_place_outside_the_config_is_rejected():
    c, reason = classify(item("Voos para Miami a partir de R$ 2.000 ida e volta"))
    assert c is None and reason == "rejected:other-place:Miami"


def test_sale_with_no_place_at_all_passes_as_origin_unknown():
    c, reason = classify(item("Tarifa erro? Passagens com 70% de desconto na Latam"))
    assert c is not None and c.origin_unknown and reason == "fare:no-place"


def test_porto_seguro_is_not_porto_and_rio_branco_is_not_rio():
    c, reason = classify(item("Voos para Porto Seguro e Rio Branco a partir de R$ 400"))
    assert c is None and reason == "rejected:other-place:Porto Seguro"


def test_porto_alegre_is_its_own_destination():
    c, _ = classify(item("Passagens para Porto Alegre a partir de R$ 250"))
    assert c is not None and c.destinations == ("Porto Alegre",)


def test_words_only_match_whole():
    # "aroma" contains "roma"; "bhutan" starts with "bh"
    c, reason = classify(item("Passagens em promoção para o Bhutan, terra do aroma de incenso"))
    assert c is not None and c.destinations == () and not c.from_bh


def test_unaccented_spelling_matches_too():
    c, _ = classify(item("Voos para Milao e Sao Luis a partir de R$ 500"))
    assert c is not None and c.destinations == ("Milão", "São Luís")


def test_transfer_bonus_is_miles_with_every_programme_in_text_order():
    c, reason = classify(item("Livelo oferece até 100% de bônus na transferência de pontos para a Smiles"))
    assert c == Classification(kind="miles", destinations=(), programs=("Livelo", "Smiles"),
                               from_bh=False, origin_unknown=False)
    assert reason == "miles:Livelo"


@pytest.mark.parametrize("title", [
    "Smiles vende milhas com até 80% de desconto na compra de milhas",
    "Clube Latam Pass com 3 meses grátis",
    "Azul Fidelidade: resgate de passagens a partir de 3 mil pontos",
    "Ganhe 10 pontos por real no Esfera comprando na Amazon",
    "Acumule até 12 pontos Livelo por real",
    "Milheiro Smiles a R$ 16 na promoção de hoje",
    "TudoAzul: transferência bonificada do Itaú",
])
def test_miles_signals(title):
    c, _ = classify(item(title))
    assert c is not None and c.kind == "miles"


def test_foreign_or_hotel_programmes_alone_are_not_miles():
    c, _ = classify(item("IHG One Rewards oferece até o triplo de pontos em estadias"))
    assert c is None
    c, _ = classify(item("Flying Blue tem bônus na compra de milhas"))
    assert c is None


def test_a_brazilian_programme_carries_a_foreign_one():
    c, _ = classify(item("Livelo com 100% de bônus na transferência para o Flying Blue"))
    assert c is not None and c.kind == "miles" and c.programs == ("Livelo",)


def test_post_matching_both_kinds_is_miles_and_keeps_the_destination():
    c, _ = classify(item("Resgate Smiles: voos para Lisboa por 35 mil milhas o trecho, em promoção"))
    assert c is not None and c.kind == "miles" and c.destinations == ("Lisboa",)


def test_miles_citing_bh_keeps_the_origin():
    c, _ = classify(item("Resgate Smiles saindo de Confins para Lisboa em promoção"))
    assert c is not None and c.kind == "miles"
    assert c.from_bh is True
    assert c.destinations == ("Lisboa",)


def test_news_about_a_programme_without_a_promotion_signal_is_not_miles():
    c, _ = classify(item("Smiles anuncia novo diretor de marketing"))
    assert c is None


def test_the_summary_counts_too():
    c, _ = classify(item("Promoção relâmpago da Gol", "Passagens saindo de Confins a partir de R$ 199."))
    assert c is not None and c.from_bh
