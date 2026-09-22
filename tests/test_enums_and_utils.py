import pytest
from datetime import datetime, timezone, timedelta
from FunPayAPI.common import enums, utils

def test_currency_enum_and_mapping():
    assert str(enums.Currency.RUB) == "₽"
    assert str(enums.Currency.USD) == "$"
    assert str(enums.Currency.EUR) == "€"
    assert str(enums.Currency.UNKNOWN) == "¤"

    assert enums.Currency.RUB.code == "rub"
    assert enums.Currency.USD.code == "usd"
    assert enums.Currency.EUR.code == "eur"
    with pytest.raises(Exception):
        _ = enums.Currency.UNKNOWN.code

def test_parse_currency():
    # Uppercase
    assert utils.parse_currency("RUB") == enums.Currency.RUB
    assert utils.parse_currency("USD") == enums.Currency.USD
    assert utils.parse_currency("EUR") == enums.Currency.EUR

    # Lowercase
    assert utils.parse_currency("rub") == enums.Currency.RUB
    assert utils.parse_currency("usd") == enums.Currency.USD
    assert utils.parse_currency("eur") == enums.Currency.EUR

    # Symbols
    assert utils.parse_currency("₽") == enums.Currency.RUB
    assert utils.parse_currency("$") == enums.Currency.USD
    assert utils.parse_currency("€") == enums.Currency.EUR
    assert utils.parse_currency("¤") == enums.Currency.RUB

    # Whitespace and unknown
    assert utils.parse_currency("  rub  ") == enums.Currency.RUB
    assert utils.parse_currency("") == enums.Currency.UNKNOWN
    assert utils.parse_currency(None) == enums.Currency.UNKNOWN
    assert utils.parse_currency("UNKNOWN_VAL") == enums.Currency.UNKNOWN

def test_random_tag():
    tag1 = utils.random_tag()
    tag2 = utils.random_tag()
    assert len(tag1) == 10
    assert len(tag2) == 10
    assert tag1 != tag2
    assert tag1.isalnum()

def test_parse_wait_time():
    assert utils.parse_wait_time("Подождите 30 секунд") == 30
    assert utils.parse_wait_time("Подождите 10 минут") == 9 * 60
    assert utils.parse_wait_time("Подождите 2 часа") == int(1.5 * 3600)
    assert utils.parse_wait_time("Неизвестный ответ") == 10

def test_parse_funpay_datetime():
    now = datetime.now(tz=timezone(timedelta(hours=3)))
    
    # Today
    dt_today = utils.parse_funpay_datetime("сегодня, 14:30")
    assert dt_today.hour == 14
    assert dt_today.minute == 30
    assert dt_today.day == now.day

    # Yesterday
    dt_yesterday = utils.parse_funpay_datetime("вчера, 09:15")
    assert dt_yesterday.hour == 9
    assert dt_yesterday.minute == 15

    # Specific date in current year
    dt_date = utils.parse_funpay_datetime("15 января, 18:45")
    assert dt_date.month == 1
    assert dt_date.day == 15
    assert dt_date.hour == 18
    assert dt_date.minute == 45

def test_all_enums_definitions():
    assert enums.EventTypes.NEW_ORDER.value == 6
    assert enums.EventTypes.NEW_MESSAGE.value == 3
    assert enums.MessageTypes.NON_SYSTEM.value == 0
    assert enums.MessageTypes.ORDER_PURCHASED.value == 1
    assert enums.OrderStatuses.PAID.value == 0
    assert enums.OrderStatuses.CLOSED.value == 1
    assert enums.OrderStatuses.REFUNDED.value == 2
    assert enums.SubCategoryTypes.COMMON.value == 0
    assert enums.SubCategoryTypes.CURRENCY.value == 1
