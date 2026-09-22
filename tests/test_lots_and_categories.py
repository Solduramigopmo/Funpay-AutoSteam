import pytest
from unittest.mock import MagicMock, patch
import requests

from FunPayAPI.common import enums
from FunPayAPI.types import LotFields, SubCategoryTypes

SAMPLE_LOTS_HTML = """
<!DOCTYPE html>
<html>
<body>
    <div class="user-link-name">TestSeller</div>
    <a class="tc-item" data-offer="12345678" href="/lots/offer?id=12345678">
        <div class="tc-server">Global</div>
        <div class="tc-side">Any</div>
        <div class="tc-desc-text">Пополнение баланса Steam 100-5000 руб</div>
        <div class="tc-amount">999 шт.</div>
        <div class="tc-price" data-s="1.05">1.05 <span class="unit">₽</span></div>
    </a>
</body>
</html>
"""

SAMPLE_OFFER_EDIT_HTML = """
<!DOCTYPE html>
<html>
<body>
    <form class="form-horizontal form-offer-editor" action="/lots/offerSave" method="post">
        <input type="hidden" name="offer_id" value="12345678">
        <input type="hidden" name="node_id" value="1086">
        <input type="hidden" name="csrf_token" value="test_token">
        <input type="checkbox" name="active" value="on" checked>
        <textarea name="fields[desc][ru]">Описание лота</textarea>
        <input type="text" name="price" value="1.05">
        <input type="text" name="amount" value="100">
        <span class="form-control-feedback">₽</span>
    </form>
</body>
</html>
"""

def test_get_my_subcategory_lots(initiated_account):
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.content = SAMPLE_LOTS_HTML.encode("utf-8")

    with patch.object(initiated_account, "method", return_value=mock_resp):
        lots = initiated_account.get_my_subcategory_lots(1086)
        assert len(lots) == 1
        lot = lots[0]
        assert lot.id == 12345678
        assert lot.description == "Пополнение баланса Steam 100-5000 руб"
        assert lot.server == "Global"
        assert lot.price == 1.05
        assert lot.currency == enums.Currency.RUB
        assert lot.amount == 999

def test_get_lot_fields(initiated_account):
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.content = SAMPLE_OFFER_EDIT_HTML.encode("utf-8")

    with patch.object(initiated_account, "method", return_value=mock_resp):
        fields = initiated_account.get_lot_fields(12345678)
        assert isinstance(fields, LotFields)
        assert fields.lot_id == 12345678
        assert fields.subcategory.id == 1086
        assert fields.active is True
        assert fields.description_ru == "Описание лота"
        assert fields.price == 1.05
        assert fields.amount == 100

def test_save_lot(initiated_account):
    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"error": 0, "msg": "Лот сохранен"}

    fields = LotFields(12345678, {"price": 1.10, "active": "on"})
    fields.subcategory_id = 1086
    fields.price = 1.10
    fields.active = True

    with patch.object(initiated_account, "method", return_value=mock_resp) as mock_m:
        initiated_account.save_lot(fields)
        mock_m.assert_called_once()
        args, kwargs = mock_m.call_args
        assert args[1] == "lots/offerSave"
