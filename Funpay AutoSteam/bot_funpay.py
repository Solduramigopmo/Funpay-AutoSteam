import os
import uuid
import logging
import re
import time
import threading
import requests
from dotenv import load_dotenv

from FunPayAPI import Account
from FunPayAPI.updater.runner import Runner
from FunPayAPI.updater.events import NewOrderEvent, NewMessageEvent

_env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
if os.path.exists(_env_path):
    load_dotenv(_env_path)
load_dotenv()

FUNPAY_AUTH_TOKEN = os.getenv("FUNPAY_AUTH_TOKEN")
STEAM_API_USER = os.getenv("STEAM_API_USER")
STEAM_API_PASS = os.getenv("STEAM_API_PASS")
MIN_BALANCE = float(os.getenv("MIN_BALANCE", "5"))

def _env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")

AUTO_REFUND = _env_bool("AUTO_REFUND", True)
AUTO_DEACTIVATE = _env_bool("AUTO_DEACTIVATE", True)

CATEGORY_ID = 1086

CREATOR_NAME = os.getenv("CREATOR_NAME", "@tinechelovec")
CREATOR_URL = os.getenv("CREATOR_URL", "https://t.me/tinechelovec")
CHANNEL_URL = os.getenv("CHANNEL_URL", "https://t.me/by_thc")
GITHUB_URL = os.getenv("GITHUB_URL", "https://github.com/tinechelovec/Funpay-AutoSteam")
BANNER_NOTE = os.getenv(
    "BANNER_NOTE",
    "Бот бесплатный и с открытым исходным кодом на GitHub. "
    "Создатель бота его НЕ продаёт. Если вы где-то видите платную версию — "
    "это решение перепродавца, к автору отношения не имеет."
)

try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init(autoreset=True)
except Exception:
    class _Dummy:
        RESET_ALL = ""
    class _Fore(_Dummy):
        RED = GREEN = YELLOW = CYAN = MAGENTA = BLUE = WHITE = ""
    class _Style(_Dummy):
        BRIGHT = NORMAL = ""
    Fore, Style = _Fore(), _Style()

class ColorFormatter(logging.Formatter):
    LEVEL_COLORS = {
        logging.DEBUG: Fore.BLUE,
        logging.INFO: Fore.CYAN,
        logging.WARNING: Fore.YELLOW,
        logging.ERROR: Fore.RED,
        logging.CRITICAL: Fore.MAGENTA + Style.BRIGHT,
    }
    def format(self, record):
        color = self.LEVEL_COLORS.get(record.levelno, "")
        message = super().format(record)
        return f"{color}{message}{Style.RESET_ALL}"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s:%(lineno)d | %(message)s"
)

file_handler = logging.FileHandler("log.txt", encoding="utf-8")
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s:%(lineno)d | %(message)s"))
logging.getLogger().addHandler(file_handler)

for h in logging.getLogger().handlers:
    if isinstance(h, logging.FileHandler):
        continue
    h.setFormatter(ColorFormatter(h.formatter._fmt if hasattr(h, "formatter") else "%(message)s"))

logger = logging.getLogger("SteamBot")

MIN_AMOUNTS = {"RUB": 15, "KZT": 80, "UAH": 7, "USD": 0.15}
STEAM_BASE = "https://xn--h1aahgceagbyl.xn--p1ai/api"
REQUEST_TIMEOUT = 20

USER_STATES = {}
SESSION_TTL = 60 * 60

MY_ID = None

LOG_COLOR_BOT  = Fore.GREEN + Style.BRIGHT
LOG_COLOR_USER = Fore.WHITE + Style.BRIGHT
LOG_COLOR_SYS  = Fore.CYAN + Style.NORMAL

def _short(s: str | None, n: int = 12) -> str:
    if not s:
        return "-"
    s = str(s)
    return s if len(s) <= n else s[-n:]

def _who_and_color(author_id) -> tuple[str, str]:
    if author_id in (None, 0):
        return "SYS", LOG_COLOR_SYS
    try:
        if MY_ID is not None and str(author_id) == str(MY_ID):
            return "BOT", LOG_COLOR_BOT
    except Exception:
        pass
    return "USER", LOG_COLOR_USER

def _resolve_order_id(message, state) -> str | None:
    return getattr(message, "order_id", None) or (state.get("order_id") if isinstance(state, dict) else None)

def log_chat(message, state, text_snippet: str = ""):
    author_id = getattr(message, "author_id", None)
    chat_id = (
        getattr(message, "chat_id", None)
        or getattr(message, "dialog_id", None)
        or getattr(message, "conversation_id", None)
    )
    who, color = _who_and_color(author_id)
    order_id = _resolve_order_id(message, state)
    buyer_id = state.get("buyer_id") if isinstance(state, dict) else None

    prefix = f"{color}[{who}]{Style.RESET_ALL}"
    tag_order = f" #{order_id}" if order_id else ""
    tag_user  = f" user={buyer_id}" if buyer_id else ""
    tag_chat  = f" chat={_short(chat_id)}"
    logger.info(f"{prefix}{tag_order}{tag_user}{tag_chat} → {text_snippet}")

def _norm_id(v):
    if v is None:
        return None
    try:
        return str(int(v))
    except Exception:
        return str(v).strip()

def _state_keys(chat_id=None, buyer_id=None, order_id=None):
    keys = []
    c = _norm_id(chat_id)
    b = _norm_id(buyer_id)
    o = _norm_id(order_id)
    if c: keys.append(f"chat:{c}")
    if b: keys.append(f"user:{b}")
    if b and o: keys.append(f"user:{b}:order:{o}")
    return keys

def _put_state(state: dict):
    keys = _state_keys(state.get("chat_id"), state.get("buyer_id"), state.get("order_id"))
    state["_keys"] = keys
    for k in keys:
        USER_STATES[k] = state
    logger.info(Fore.CYAN + f"[STATE] index -> {', '.join(keys)}")

def _pop_state(state_or_key):
    if isinstance(state_or_key, dict):
        keys = state_or_key.get("_keys", [])
    else:
        keys = [state_or_key]
    for k in list(keys):
        USER_STATES.pop(k, None)

def _find_state_for_message(msg):
    chat_id = getattr(msg, "chat_id", None) or getattr(msg, "dialog_id", None) or getattr(msg, "conversation_id", None)
    author_id = getattr(msg, "author_id", None)
    order_id = getattr(msg, "order_id", None)
    for k in _state_keys(chat_id, author_id, order_id):
        s = USER_STATES.get(k)
        if s:
            return s
    b = _norm_id(author_id)
    if b:
        candidates = [s for k, s in USER_STATES.items() if k.startswith(f"user:{b}")]
        if len(candidates) == 1:
            return candidates[0]
    return None

STEAM_TOKEN: str | None = None
_STEAM_TOKEN_LOCK = threading.Lock()

def _set_token(token: str):
    global STEAM_TOKEN
    STEAM_TOKEN = token

def get_api_token() -> str:
    url = f"{STEAM_BASE}/token"
    payload = {"username": STEAM_API_USER, "password": STEAM_API_PASS}
    headers = {"accept": "application/json", "content-type": "application/json"}
    r = requests.post(url, json=payload, headers=headers, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    token = r.json().get("access_token")
    if not token:
        raise RuntimeError("Ошибка авторизации в Steam API (нет access_token).")
    logger.info(Fore.GREEN + "✅ Успешно получили токен Steam API")
    return token

def _ensure_token():
    global STEAM_TOKEN
    if STEAM_TOKEN:
        return
    with _STEAM_TOKEN_LOCK:
        if not STEAM_TOKEN:
            _set_token(get_api_token())

def _refresh_token():
    with _STEAM_TOKEN_LOCK:
        _set_token(get_api_token())

def steam_headers() -> dict:
    return {
        "accept": "application/json",
        "content-type": "application/json",
        "authorization": f"Bearer {STEAM_TOKEN}"
    }

def _request_with_refresh(method: str, path: str, retry: bool = True, **kwargs) -> requests.Response:
    _ensure_token()
    headers = kwargs.pop("headers", {}) or {}
    url = f"{STEAM_BASE}{path}"
    resp = requests.request(method.upper(), url, headers={**headers, **steam_headers()}, timeout=REQUEST_TIMEOUT, **kwargs)
    if resp.status_code in (401, 403) and retry:
        logger.warning(Fore.YELLOW + f"[AUTH] {resp.status_code} на {path}. Обновляю токен и повторяю запрос.")
        _refresh_token()
        resp = requests.request(method.upper(), url, headers={**headers, **steam_headers()}, timeout=REQUEST_TIMEOUT, **kwargs)
    return resp

def _token_refresher_loop(interval_sec: int = 50 * 60):
    while True:
        try:
            time.sleep(interval_sec)
            logger.info(Fore.CYAN + "[AUTH] Плановый рефреш токена")
            _refresh_token()
        except Exception as e:
            logger.error(Fore.RED + f"[AUTH] Плановый рефреш не удался: {e}")

def start_token_refresher(interval_sec: int = 50 * 60):
    t = threading.Thread(target=_token_refresher_loop, args=(interval_sec,), daemon=True)
    t.start()
    def _t():
        _m = "".join([
            "Сп", "асибо, ", "что пользуетесь этим ботом, он полностью бесплатный. ",
            "Автор не продаёт его."
        ])
        while True:
            try:
                time.sleep(15 * 60)
                logger.info(Fore.MAGENTA + _m + (f" Исходники: {GITHUB_URL}" if GITHUB_URL else ""))
            except Exception:
                pass
    threading.Thread(target=_t, daemon=True).start()

def _friendly_http_error(resp: requests.Response, default_msg: str = "Сервис временно недоступен."):
    try:
        data = resp.json()
    except Exception:
        data = {}
    text = data.get("message") or data.get("detail") or ""
    tech = text or resp.text[:500]
    logger.error(f"{default_msg} HTTP {resp.status_code}. Ответ: {tech}")
    if resp.status_code in (401, 403):
        return "Ошибка авторизации сервиса. Уже разбираемся — оформим возврат."
    if resp.status_code in (429,):
        return "Сервис перегружен. Попробуйте оформить заказ чуть позже — мы сделаем возврат."
    if resp.status_code >= 500:
        return "У сервиса технические неполадки. Мы вернём средства."
    if resp.status_code >= 400:
        return "Запрос отклонён сервисом. Мы вернём средства."
    return "Не удалось выполнить запрос. Мы вернём средства."

def check_login(login: str) -> bool:
    if not login:
        return False
    try:
        r = _request_with_refresh("POST", "/check", json={"login": login})
        ok = bool(r.json().get("result", False))
        logger.info((Fore.GREEN if ok else Fore.YELLOW) + f"🔎 Проверка логина: '{login}' -> {ok}")
        return ok
    except Exception as e:
        logger.error(Fore.RED + f"Ошибка проверки логина Steam: {e}")
        return False

def convert_to_usd(currency: str, amount: float) -> float | None:
    try:
        if currency.upper() == "USD":
            return float(amount)
        r = _request_with_refresh("POST", "/rates", json={"primary_currency": currency.upper(), "amount": amount})
        if r.status_code != 200:
            logger.warning(Fore.YELLOW + f"[RATES] Нехороший ответ: {r.status_code} {r.text[:200]}")
            return None
        return r.json().get("usd_price")
    except Exception as e:
        logger.error(Fore.RED + f"Ошибка конвертации: {e}")
        return None

def create_order(login: str, usd_amount: float):
    custom_id = str(uuid.uuid4())
    payload = {"service_id": 1, "quantity": round(float(usd_amount), 2), "custom_id": custom_id, "data": login}
    logger.debug(Fore.BLUE + f"[DEBUG] payload create_order: {payload}")
    r = _request_with_refresh("POST", "/create_order", json=payload)
    logger.info((Fore.GREEN if r.status_code == 200 else Fore.RED) + f"🧾 Создание заказа {custom_id}: HTTP {r.status_code}")
    return r, custom_id

def pay_order(custom_id: str):
    payload = {"custom_id": str(custom_id)}
    logger.debug(Fore.BLUE + f"[DEBUG] payload pay_order: {payload}")
    r = _request_with_refresh("POST", "/pay_order", json=payload)
    logger.info((Fore.GREEN if r.status_code == 200 else Fore.RED) + f"💳 Оплата заказа {custom_id}: HTTP {r.status_code}")
    return r

def check_balance() -> float:
    try:
        r = _request_with_refresh("POST", "/check_balance")
        r.raise_for_status()
        data = r.json()
        balance = float(data.get("balance", data) if isinstance(data, dict) else data)
        logger.info(Fore.MAGENTA + f"[BALANCE] Текущий баланс API: {balance} USD")
        return balance
    except Exception as e:
        logger.error(Fore.RED + f"[BALANCE] Ошибка проверки баланса: {e}")
        return 0.0

def deactivate_category(account: Account, category_id: int):
    try:
        my_lots = account.get_my_subcategory_lots(category_id)
    except Exception as e:
        logger.error(Fore.RED + f"[LOTS] Не удалось получить список лотов категории {category_id}: {e}")
        return
    if not my_lots:
        logger.info(Fore.YELLOW + f"[LOTS] В категории {category_id} нет лотов для деактивации.")
        return

    deactivated = skipped = failed = 0
    for lot in my_lots:
        lot_id = getattr(lot, "id", None)
        if lot_id is None:
            logger.warning(Fore.YELLOW + "[LOTS] Пропускаю элемент без lot.id")
            skipped += 1
            continue
        try:
            fields = account.get_lot_fields(lot_id)
        except Exception as e:
            logger.error(Fore.RED + f"[LOTS] Не удалось получить поля лота {lot_id}: {e}")
            failed += 1
            continue
        if fields is None:
            logger.warning(Fore.YELLOW + f"[LOTS] get_lot_fields вернул None для {lot_id} — пропускаю")
            skipped += 1
            continue
        try:
            if isinstance(fields, dict):
                is_active = fields.get("active", fields.get("is_active", True))
                if not is_active:
                    skipped += 1
                    continue
                fields["active"] = False
                account.save_lot(fields)
            else:
                active_val = (
                    getattr(fields, "active", None) if hasattr(fields, "active")
                    else getattr(fields, "is_active", None) if hasattr(fields, "is_active")
                    else getattr(fields, "enabled", None) if hasattr(fields, "enabled")
                    else None
                )
                if active_val is False:
                    skipped += 1
                    continue
                if hasattr(fields, "active"): fields.active = False
                elif hasattr(fields, "is_active"): fields.is_active = False
                elif hasattr(fields, "enabled"): fields.enabled = False
                else:
                    skipped += 1
                    continue
                account.save_lot(fields)
            deactivated += 1
            logger.info(Fore.YELLOW + f"[LOTS] Деактивирован лот {lot_id}")
            time.sleep(0.3)
        except Exception as e:
            logger.error(Fore.RED + f"[LOTS] Ошибка деактивации лота {lot_id}: {e}")
            failed += 1
            continue

    logger.warning(Fore.YELLOW + f"[LOTS] Итог: деактивировано={deactivated}, пропущено={skipped}, с ошибкой={failed} (категория {category_id})")

def activate_category(account: Account, category_id: int):
    try:
        my_lots = account.get_my_subcategory_lots(category_id)
    except Exception as e:
        logger.error(Fore.RED + f"[LOTS] Не удалось получить список лотов категории {category_id}: {e}")
        return
    if not my_lots:
        logger.info(Fore.YELLOW + f"[LOTS] В категории {category_id} нет лотов для активации.")
        return

    activated = skipped = failed = 0
    for lot in my_lots:
        lot_id = getattr(lot, "id", None)
        if lot_id is None:
            skipped += 1
            continue
        try:
            fields = account.get_lot_fields(lot_id)
            if fields is None:
                skipped += 1
                continue
            if isinstance(fields, dict):
                is_active = fields.get("active", fields.get("is_active", False))
                if is_active:
                    skipped += 1
                    continue
                fields["active"] = True
                account.save_lot(fields)
            else:
                active_val = (
                    getattr(fields, "active", None) if hasattr(fields, "active")
                    else getattr(fields, "is_active", None) if hasattr(fields, "is_active")
                    else getattr(fields, "enabled", None) if hasattr(fields, "enabled")
                    else None
                )
                if active_val is True:
                    skipped += 1
                    continue
                if hasattr(fields, "active"): fields.active = True
                elif hasattr(fields, "is_active"): fields.is_active = True
                elif hasattr(fields, "enabled"): fields.enabled = True
                else:
                    skipped += 1
                    continue
                account.save_lot(fields)
            activated += 1
            logger.info(Fore.GREEN + f"[LOTS] Активирован лот {lot_id}")
            time.sleep(0.3)
        except Exception as e:
            logger.error(Fore.RED + f"[LOTS] Ошибка активации лота {lot_id}: {e}")
            failed += 1
            continue

    logger.warning(Fore.CYAN + f"[LOTS] Итог активации: активировано={activated}, пропущено={skipped}, с ошибкой={failed} (категория {category_id})")

def _first_number_from_string(s: str) -> float | None:
    m = re.search(r"(\d+(?:[.,]\d+)?)", s)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except:
            return None
    return None

def get_order_amount(order) -> tuple[float, str] | None:
    candidate_attrs = ["quantity", "qty", "amount", "sum", "count", "price", "quantity_value", "quantity_text"]
    for attr in candidate_attrs:
        val = getattr(order, attr, None)
        if val is None or (isinstance(val, str) and not val.strip()):
            continue
        if isinstance(val, (int, float)):
            logger.info(Fore.CYAN + f"[get_order_amount] Взято из атрибута '{attr}': {float(val)}")
            return float(val), f"attr:{attr}"
        try:
            s = str(val).replace(",", ".").strip()
            num = _first_number_from_string(s)
            if num is not None:
                logger.info(Fore.CYAN + f"[get_order_amount] Взято из атрибута '{attr}' (парсинг строки): {num} (raw='{val}')")
                return float(num), f"attr:{attr}"
        except Exception as e:
            logger.debug(f"[get_order_amount] Ошибка парсинга атрибута {attr}: {e}")

    text_fields = []
    for f in ("html", "title", "full_description", "short_description"):
        v = getattr(order, f, None)
        if v:
            text_fields.append(str(v))
    full_text = " ".join(text_fields).lower()
    if not full_text.strip():
        logger.warning(Fore.YELLOW + "[get_order_amount] Нет текстовых полей для поиска суммы.")
        return None

    patterns_priority = [
        r'(?:количеств(?:о|о:)|кол-во|кол:)\D{0,60}?(\d+(?:[.,]\d+)?)',
        r'(?:amount|quantity|qty)\D{0,60}?(\d+(?:[.,]\d+)?)',
        r'(?:пополнение|пополнен|wallet|steam_wallet)\D{0,60}?(\d+(?:[.,]\d+)?)',
        r'(\d+(?:[.,]\d+)?)\s*(?:uah|грн|uah|rub|руб|kzt|тенге|usd|\$|₽|₸)\b'
    ]
    for pat in patterns_priority:
        m = re.search(pat, full_text)
        if m:
            try:
                val = float(m.group(1).replace(",", "."))
                logger.info(Fore.CYAN + f"[get_order_amount] Найдено по приоритетному шаблону: {val} (pattern: {pat})")
                return val, f"pattern:{pat}"
            except Exception:
                pass

    first_num = _first_number_from_string(full_text)
    if first_num is not None:
        logger.info(Fore.CYAN + f"[get_order_amount] Взято первое число из текста: {first_num}")
        return float(first_num), "text:first_number"

    logger.warning(Fore.YELLOW + "[get_order_amount] Не удалось определить сумму пополнения.")
    return None

def get_description_text(order) -> str:
    for attr in ("full_description", "short_description", "html", "title"):
        v = getattr(order, attr, None)
        if v:
            return str(v).lower()
    return ""

def order_link(order_id) -> str:
    try:
        return f"https://funpay.com/orders/{int(order_id)}/"
    except Exception:
        return "https://funpay.com/orders/"

def _nice_refund(account: Account, chat_id, order_id, user_text: str):
    logger.info(Fore.YELLOW + f"↩️ Возврат по заказу {order_id}: {user_text}")
    if chat_id:
        if AUTO_REFUND:
            account.send_message(chat_id, user_text + "\n\nДеньги будут возвращены автоматически.")
        else:
            account.send_message(chat_id, user_text + "\n\n⚠️ Автоматический возврат выключен. Свяжитесь с админом для возврата.")
    if order_id and AUTO_REFUND:
        try:
            account.refund(order_id)
        except Exception as e:
            logger.error(Fore.RED + f"[REFUND] Ошибка возврата по заказу {order_id}: {e}")

def handle_new_order(account: Account, order):
    try:
        _refresh_token()

        subcat_id, subcat = get_subcategory_id_safe(order, account)
        if subcat_id != CATEGORY_ID:
            logger.info(Fore.BLUE + f"[ORDER] Заказ {order.id} проигнорирован (subcategory {subcat_id}, требуется {CATEGORY_ID})")
            return

        chat_id = getattr(order, "chat_id", None)
        buyer_id = getattr(order, "buyer_id", None)

        title = getattr(order, "title", None)
        logger.info(Style.BRIGHT + Fore.WHITE + "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        logger.info(Style.BRIGHT + Fore.CYAN + f"🆕 Новый заказ #{getattr(order, 'id', 'unknown')} | Покупатель: {buyer_id}")
        if title:
            logger.info(Fore.CYAN + f"📦 Товар: {title}")
        logger.info(Style.BRIGHT + Fore.WHITE + "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        desc_text = get_description_text(order)
        if "steam_wallet:" not in desc_text:
            _nice_refund(
                account, chat_id, getattr(order, "id", None),
                "⚠️ Ошибка в заказе: не указана валюта (ожидалось steam_wallet: rub|uah|kzt|usd)."
            )
            return

        try:
            currency_raw = desc_text.split("steam_wallet:")[1].split()[0]
            currency = currency_raw.strip().upper()
        except Exception:
            currency = None

        if currency not in MIN_AMOUNTS:
            _nice_refund(
                account, chat_id, getattr(order, "id", None),
                f"⚠️ Неверная валюта: {currency or '—'}. Поддерживаются: RUB, UAH, KZT, USD."
            )
            return

        amt_info = get_order_amount(order)
        if not amt_info:
            _nice_refund(
                account, chat_id, getattr(order, "id", None),
                "⚠️ Не удалось определить сумму пополнения. Пожалуйста, укажите количество при оформлении заказа."
            )
            return

        amount, source = amt_info
        logger.info(Fore.CYAN + f"[ORDER] Сумма пополнения: {amount} {currency} (source={source})")

        if amount < MIN_AMOUNTS[currency]:
            _nice_refund(
                account, chat_id, getattr(order, "id", None),
                f"⚠️ Минимальная сумма пополнения — {MIN_AMOUNTS[currency]} {currency}."
            )
            return

        usd_amount = convert_to_usd(currency, amount)
        if usd_amount is None:
            _nice_refund(
                account, chat_id, getattr(order, "id", None),
                "❌ Не удалось преобразовать валюту. Повторите заказ позже."
            )
            return

        state = {
            "step": "waiting_login",
            "created_at": time.time(),
            "buyer_id": buyer_id,
            "order_id": getattr(order, "id", None),
            "chat_id": chat_id,
            "amount": amount,
            "currency": currency,
            "usd_amount": usd_amount,
            "paid": False
        }
        _put_state(state)

        account.send_message(
            chat_id,
            "👋 Спасибо за заказ!\n\n"
            f"Сумма пополнения: {amount} {currency} (≈ {usd_amount:.2f} USD).\n"
            "Пожалуйста, укажите ваш Steam-логин (без почты и телефона)."
        )
        logger.info(Fore.BLUE + f"⏳ Ожидаем логин от покупателя {buyer_id}...")

    except Exception:
        logger.exception(Fore.RED + "Ошибка обработки заказа (общая)")
    logger.info(Fore.CYAN + f"[ORDER->STATE] chat_id={chat_id} buyer_id={buyer_id} order_id={getattr(order,'id',None)}")

def handle_new_message(account: Account, message):
    if not message:
        logger.debug("[MSG] Пустое сообщение (None) — пропускаю")
        return

    user_id = getattr(message, "author_id", None)
    msg_chat_id = (
        getattr(message, "chat_id", None)
        or getattr(message, "dialog_id", None)
        or getattr(message, "conversation_id", None)
    )

    raw_text = (
        getattr(message, "text", None)
        or getattr(message, "body", None)
        or getattr(message, "content", None)
        or ""
    )
    text = raw_text.strip() if isinstance(raw_text, str) else ""
    snippet = (text or (str(raw_text) if raw_text is not None else ""))[:200]

    if not isinstance(raw_text, str) or not text:
        logger.debug("[MSG] Нет текстового содержимого — пропускаю")
        return

    state = _find_state_for_message(message) if "_find_state_for_message" in globals() else None
    if not state:
        if msg_chat_id and msg_chat_id in USER_STATES:
            state = USER_STATES[msg_chat_id]
        else:
            log_chat(message, {}, snippet)
            logger.debug(Fore.BLUE + f"[MSG] Нет активной сессии для chat_id={msg_chat_id}, author_id={user_id}")
            return

    log_chat(message, state, snippet)

    chat_id = msg_chat_id or state.get("chat_id")

    if user_id and state.get("buyer_id") and user_id != state["buyer_id"]:
        return

    if time.time() - state.get("created_at", time.time()) > SESSION_TTL:
        logger.info(Fore.YELLOW + f"[MSG] Сессия в чате {chat_id} протухла — очищаю.")
        if "_pop_state" in globals():
            _pop_state(state)
        else:
            USER_STATES.pop(chat_id, None)
        return

    if state.get("step") in ("paying", "finished"):
        logger.info(Fore.BLUE + f"[MSG] Игнор дубля (step={state['step']}) в чате {chat_id}")
        return

    if state.get("step") == "waiting_login":
        login = text
        if not check_login(login):
            account.send_message(
                chat_id,
                f"⚠️ Логин {login} не найден. Проверьте правильность написания и отправьте ещё раз.\n\n"
                "Пример: gabelogannewell"
            )
            logger.info(Fore.YELLOW + f"🚫 Логин не найден: {login}")
            return

        state["login"] = login
        state["step"] = "confirm_login"
        account.send_message(
            chat_id,
            "✅ Логин найден!\n\n"
            f"Вы указали: {login}\n"
            f"Сумма: {state['amount']} {state['currency']} (≈ {state['usd_amount']:.2f} USD)\n\n"
            "Если всё верно — напишите +.\n"
            "Если нужно изменить логин — просто отправьте новый."
        )
        logger.info(Fore.GREEN + f"✅ Логин подтверждён существующий: {login}")
        return

    if state.get("step") == "confirm_login":
        if text == "+":
            if state.get("paid"):
                account.send_message(chat_id, "ℹ️ Заказ уже обрабатывается/выполнен. Повторное списание не требуется.")
                return
            state["paid"] = True
            state["step"] = "paying"

            logger.info(Fore.BLUE + f"🧾 Запрос на создание заказа для {state['login']} на {state['usd_amount']:.2f} USD")
            r, custom_id = create_order(state["login"], state["usd_amount"])

            try:
                json_r = r.json()
            except Exception:
                json_r = {}

            if r.status_code != 200 or "error" in json_r:
                user_msg = _friendly_http_error(r, "Не удалось создать заказ в сервисе пополнения.")
                account.send_message(chat_id, f"❌ {user_msg}")

                balance = check_balance()
                if balance < MIN_BALANCE and AUTO_DEACTIVATE:
                    logger.warning(Fore.YELLOW + "💤 Баланс ниже порога — деактивируем лоты категории.")
                    deactivate_category(account, CATEGORY_ID)

                if AUTO_REFUND:
                    try:
                        account.refund(state["order_id"])
                    except Exception as e:
                        logger.error(Fore.RED + f"[REFUND] Ошибка возврата: {e}")
                else:
                    account.send_message(chat_id, "⚠️ Автоматический возврат отключён. Свяжитесь с админом для возврата.")

                if "_pop_state" in globals():
                    _pop_state(state)
                else:
                    USER_STATES.pop(chat_id, None)
                return

            logger.info(Fore.BLUE + f"💳 Запрос на оплату заказа custom_id={custom_id}")
            pay_res = pay_order(custom_id)

            if pay_res.status_code == 200:
                link = order_link(state["order_id"])
                account.send_message(
                    chat_id,
                    "🎉 Готово!\n\n"
                    f"Мы пополнили баланс {state['login']} на {state['amount']} {state['currency']} "
                    f"(≈ {state['usd_amount']:.2f} USD).\n\n"
                    "Проверьте зачисление в Steam.\n"
                    "Пожалуйста, подтвердите выполнение заказа и, если не сложно, оставьте отзыв — это очень помогает!\n"
                    f"Ссылка на ваш заказ: {link}"
                )
                logger.info(Fore.GREEN + f"✅ Успешное пополнение: {state['amount']} {state['currency']} для {state['login']}.")

                state["step"] = "finished"
                if "_pop_state" in globals():
                    _pop_state(state)
                else:
                    USER_STATES.pop(chat_id, None)
                return
            else:
                user_msg = _friendly_http_error(pay_res, "Не удалось оплатить заказ в сервисе пополнения.")
                account.send_message(chat_id, f"❌ {user_msg}")

                balance = check_balance()
                if balance < MIN_BALANCE and AUTO_DEACTIVATE:
                    logger.warning(Fore.YELLOW + "💤 Баланс ниже порога — деактивируем лоты категории.")
                    deactivate_category(account, CATEGORY_ID)

                if AUTO_REFUND:
                    try:
                        account.refund(state["order_id"])
                    except Exception as e:
                        logger.error(Fore.RED + f"[REFUND] Ошибка возврата: {e}")
                else:
                    account.send_message(chat_id, "⚠️ Автоматический возврат отключён. Свяжитесь с админом для возврата.")

                if "_pop_state" in globals():
                    _pop_state(state)
                else:
                    USER_STATES.pop(chat_id, None)
                return
            
        new_login = text
        if state.get("paid"):
            account.send_message(chat_id, "ℹ️ Заказ уже в обработке/выполнен. Изменить логин поздно.")
            return

        if not check_login(new_login):
            account.send_message(chat_id, f"⚠️ Логин {new_login} не найден. Попробуйте снова:")
            logger.info(Fore.YELLOW + f"🚫 Новый логин не найден: {new_login}")
            return

        state["login"] = new_login
        account.send_message(
            chat_id,
            "✅ Новый логин найден!\n\n"
            f"Вы указали: {new_login}\n"
            f"Сумма: {state['amount']} {state['currency']} (≈ {state['usd_amount']:.2f} USD)\n\n"
            "Если всё верно — напишите +.\n"
            "Если нужно изменить логин — укажите другой."
        )
        logger.info(Fore.GREEN + f"♻️ Логин обновлён: {new_login}")
        return

def get_subcategory_id_safe(order, account):
    subcat = getattr(order, "subcategory", None) or getattr(order, "sub_category", None)
    if subcat and hasattr(subcat, "id"):
        return subcat.id, subcat
    try:
        full_order = account.get_order(order.id)
        subcat = getattr(full_order, "subcategory", None) or getattr(full_order, "sub_category", None)
        if subcat and hasattr(subcat, "id"):
            return subcat.id, subcat
    except Exception as e:
        logger.warning(Fore.YELLOW + f"⚠️ Не удалось загрузить полный заказ: {e}")
    return None, None

def _banner():
    logger.info(Style.BRIGHT + Fore.WHITE + "🚀 SteamBot запущен. Ожидаю события...")
    logger.info(Style.BRIGHT + Fore.MAGENTA + f"ℹ️ {BANNER_NOTE}")
    logger.info(Style.NORMAL + Fore.MAGENTA + f"   Автор: {CREATOR_NAME} | TG: {CREATOR_URL} | Канал: {CHANNEL_URL} | GitHub: {GITHUB_URL}\n")

def main():
    token = (FUNPAY_AUTH_TOKEN or "").strip()
    if not token or token == "FUNPAY_AUTH_TOKEN":
        logger.error(Fore.RED + "[-] В файле .env не указан реальный токен FunPay (FUNPAY_AUTH_TOKEN)!")
        print("\n" + "=" * 60)
        print("  Как настроить .env:")
        print("  1. Откройте funpay.com в браузере и авторизуйтесь.")
        print("  2. Нажмите F12 -> Application (Приложение) -> Cookies -> golden_key.")
        print("  3. Скопируйте значение и вставьте в .env вместо FUNPAY_AUTH_TOKEN.")
        print("=" * 60 + "\n")
        return

    steam_user = (STEAM_API_USER or "").strip()
    steam_pass = (STEAM_API_PASS or "").strip()
    if not steam_user or steam_user == "STEAM_API_USER" or not steam_pass or steam_pass == "STEAM_API_PASS":
        logger.warning(Fore.YELLOW + "[!] Внимание: STEAM_API_USER или STEAM_API_PASS не настроены в .env!")

    logger.info(Fore.CYAN + f"[CFG] AUTO_REFUND={AUTO_REFUND}, AUTO_DEACTIVATE={AUTO_DEACTIVATE}, MIN_BALANCE={MIN_BALANCE}")

    account = Account(token)
    try:
        account.get()
    except exceptions.UnauthorizedError:
        logger.error(Fore.RED + "[-] Ошибка: FunPay отклонил токен (UnauthorizedError). Проверьте актуальность golden_key в .env!")
        return
    except Exception as e:
        logger.error(Fore.RED + f"[-] Ошибка авторизации: {e}")
        return

    logger.info(Fore.GREEN + f"🔐 Авторизован как {getattr(account, 'username', '(unknown)')}")

    global MY_ID
    MY_ID = getattr(account, "id", None) or getattr(account, "user_id", None)

    start_token_refresher()
    _banner()

    runner = Runner(account)
    for event in runner.listen(requests_delay=3.0):
        try:
            if isinstance(event, NewOrderEvent):
                order = account.get_order(event.order.id)
                handle_new_order(account, order)
            elif isinstance(event, NewMessageEvent):
                if getattr(event, "message", None) is None:
                    logger.debug("[Runner] NewMessageEvent без message — пропускаю")
                else:
                    handle_new_message(account, event.message)
        except Exception:
            logger.exception(Fore.RED + "Ошибка в основном цикле")

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.exception(Fore.RED + f"Непредвиденная критическая ошибка: {e}")
    finally:
        try:
            input("\nНажмите Enter, чтобы закрыть окно...")
        except Exception:
            pass