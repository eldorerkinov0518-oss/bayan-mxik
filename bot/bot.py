"""ИКПУ излаш Telegram боти.

Штрих код (GTIN) ёки 17 хонали ИКПУ кодини юборсангиз, tasnif.soliq.uz
базасидан маълумотини топиб беради. Фақат Python 3 стандарт кутубхонаси
ишлатилади, ҳеч нарса ўрнатиш шарт эмас.

Компьютерда: bot.py ёнидаги token.txt файлига BotFather берган токенни
ёзинг ва start.bat ни икки марта босинг.
Серверда: токен BOT_TOKEN муҳит ўзгарувчисида келади, каталог эса сайтнинг
catalog.json файлидан (CATALOG_FILE) ўқилади. Батафсил: bot/README.md.
"""
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

API = "https://tasnif.soliq.uz/api/cls-api"
# Same catalog and accepted differences as the web page; refreshed from the site so the bot follows page updates.
CATALOG_URL = "https://eldorerkinov0518-oss.github.io/bayan-mxik/catalog.json"
# On the server the site's own catalog.json is deployed next to the bot, so it is read from disk.
CATALOG_FILE = os.environ.get("CATALOG_FILE", "")
CATALOG_TTL = 6 * 3600
LANG = "uz"
HERE = os.path.dirname(os.path.abspath(__file__))


def load_token():
    token = os.environ.get("BOT_TOKEN", "").strip()
    path = os.path.join(HERE, "token.txt")
    if not token and os.path.exists(path):
        with open(path, encoding="utf-8-sig") as f:
            token = f.read().strip()
    if not re.fullmatch(r"\d+:[\w-]{30,}", token):
        if os.environ.get("BOT_WAIT_FOR_TOKEN"):
            # Server before the token is set: stay idle instead of restarting every few seconds.
            print("BOT_TOKEN берилмаган ёки нотўғри. Бот кутиш ҳолатида.", flush=True)
            while True:
                time.sleep(3600)
        sys.exit("token.txt файлига BotFather берган токенни ёзинг (масалан 123456:ABC...).")
    return token


def get_json(url, timeout=20):
    req = urllib.request.Request(url, headers={"accept": "application/json", "user-agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def tasnif(path, **params):
    try:
        return get_json(f"{API}{path}?{urllib.parse.urlencode(params)}")
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:
            return None


def strip0(c):
    return c.lstrip("0")


def find_by_barcode(code):
    # Asl Belgisi gives 14-digit GTINs with leading zeros, tasnif usually
    # stores the 13-digit EAN, so try every form and compare without zeros.
    core = strip0(code)
    variants = list(dict.fromkeys([code, core, core.zfill(13), core.zfill(14)]))

    def exact(items):
        return [i for i in items or []
                if any(c and strip0(c) == core for c in re.split(r"[^0-9]+", str(i.get("internationalCode") or "")))]

    for v in variants:
        body = tasnif("/mxik/search/by-params", gtin=v, page=0, size=20, lang=LANG) or {}
        items = exact((body.get("data") or {}).get("content"))
        if items:
            return items
    for v in (core, code):
        body = tasnif("/elasticsearch/search", search=v, page=0, size=20, lang=LANG) or {}
        data = body.get("data")
        items = exact(data if isinstance(data, list) else [])
        if items:
            return items
    return []


def get_card(mxik):
    body = tasnif("/mxik/get/by-mxik", mxikCode=mxik, lang=LANG)
    if not isinstance(body, dict):
        return None
    data = body.get("data")
    return data if isinstance(data, dict) and data.get("mxikCode") else body


def find_by_ikpu(code):
    body = tasnif("/mxik/search/by-params", mxikCode=code, page=0, size=20, lang=LANG) or {}
    items = [i for i in (body.get("data") or {}).get("content") or [] if i.get("mxikCode") == code]
    if items:
        return items
    card = get_card(code)
    return [card] if card and card.get("mxikCode") == code else []


_cat = {"at": 0, "by": {}, "accept": {}}


def catalog():
    if time.time() - _cat["at"] < CATALOG_TTL and _cat["by"]:
        return _cat
    data = None
    if CATALOG_FILE:
        try:
            with open(CATALOG_FILE, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as ex:
            print("Каталог файлини ўқиб бўлмади:", CATALOG_FILE, ex, flush=True)
    if not data:
        try:
            data = get_json(CATALOG_URL)
        except Exception as ex:
            print("Каталогни сайтдан олиб бўлмади, маҳаллий нусха ишлатилади:", ex, flush=True)
    local = os.path.join(HERE, "catalog.json")
    if data and not CATALOG_FILE:
        try:
            with open(local, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
        except OSError:
            pass
    elif not data and os.path.exists(local):
        with open(local, encoding="utf-8") as f:
            data = json.load(f)
    if data:
        _cat.update(at=time.time(), by={strip0(r[0]): r for r in data["catalog"]}, accept=data.get("accept") or {})
    return _cat


def own_of(code):
    return catalog()["by"].get(strip0(str(code or "")))


# Catalog vs tasnif check; mirrors compare() in index.html. The catalog is the reference and
# only clear contradictions count; something tasnif doesn't mention is not an error.
CYR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюяўқғҳ",
               ["a", "b", "v", "g", "d", "e", "yo", "j", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f", "x",
                "ts", "ch", "sh", "sh", "", "i", "", "e", "yu", "ya", "o", "q", "g", "h"]))
UNITS = "мкг|мг|г|мл|ме|ед|%"
MAIN = ("Номи", "Қадоқ сони")


def name_key(t):
    t = "".join(CYR.get(c, c) for c in str(t or "").lower())
    t = t.replace("x", "ks").replace("c", "k").replace("q", "k").replace("w", "v")
    return re.sub(r"[^a-z0-9]", "", t)


def norm_t(t):
    t = str(t or "").lower().replace(",", ".")
    t = re.sub(r"(\d)\s+(?=[a-zа-яё%])", r"\1", t)
    return re.sub(r"\s+", " ", t)


def has_tok(text, tok):
    return re.search(r"(^|[^\d.])" + re.escape(tok) + r"(?![а-яёa-z])", text, re.I) is not None


def lev(a, b):
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i]
        for j in range(1, len(b) + 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1])))
        prev = cur
    return prev[-1]


def near_in(text, k):
    # One spelling slip is fine; two would let the INN "Мелоксикам" pass for "Мелоксилат".
    if not k:
        return False
    if k in text:
        return True
    if len(k) < 5:
        return False
    return any(lev(text[i:i + n], k) <= 1 for n in range(len(k) - 1, len(k) + 2) for i in range(0, len(text) - n + 1))


def compare(own, it):
    gtin, name, brand, desc, pack = own
    t_name = it.get("mxikName") or it.get("name") or ""
    T = norm_t(f"{t_name} {it.get('attributeName') or ''} {it.get('brandName') or ''}")
    out = []
    key_t = name_key(T)
    cands = [x for x in (brand, name) if len(name_key(x)) >= 3]
    if cands:
        ok = any(near_in(key_t, name_key(c)) or near_in(key_t, name_key(re.split(r"[\s(]", str(c))[0])) for c in cands)
        out.append((ok, f"Номи: {brand or name}" if ok
                    else f"Номи: каталог бўйича «{brand or name}» бўлиши керак, tasnif номи: «{t_name}»"))
    d = norm_t(desc)
    dose_re = re.compile(rf"(\d+(?:\.\d+)?)({UNITS})(?![а-яёa-z])", re.I)
    doses = list(dict.fromkeys(m.group(1) + m.group(2) for m in dose_re.finditer(d)))
    t_units = [m.group(2) for m in dose_re.finditer(T)]
    wrong = [x for x in doses if re.sub(r"^[\d.]+", "", x) in t_units and not has_tok(T, x)]
    if doses:
        out.append((not wrong, f"Доза: {'/'.join(doses)}" if not wrong
                    else f"Доза: каталог бўйича {'/'.join(doses)} бўлиши керак, tasnif'да бошқача ({', '.join(wrong)} йўқ)"))
    if re.search(r"концентрат|эритма|раствор|инъекц|инфуз", T) and ("концентрат" in d) != ("концентрат" in T):
        out.append((False, "Дори шакли: каталог бўйича концентрат бўлиши керак, tasnif'да концентрат эмас" if "концентрат" in d
                    else "Дори шакли: каталог бўйича эритма (раствор) бўлиши керак, tasnif'да концентрат"))
    pk = norm_t(pack)
    cm = (re.search(r"(\d+)\s*(?:[а-я]+(?:ых|ая|ые|ой)\s+)?(?:ампул|флакон|шприц|таблет|капсул|пакет|саше|туб|суппозитор|комплект)", pk)
          or re.search(r"(?:ампул[а-я]*|флакон[а-я]*)\s+(?:[\d.]+(?:мл|мг)\s+)?(\d+)шт", pk))
    tm = re.search(r"№\s*(\d+)", T)
    if cm and tm:
        same = int(cm.group(1)) == int(tm.group(1))
        out.append((same, f"Қадоқ сони: №{cm.group(1)}" if same
                    else f"Қадоқ сони: каталог бўйича №{cm.group(1)} бўлиши керак, tasnif'да №{tm.group(1)}"))
    vm = re.findall(r"(\d+(?:\.\d+)?)мл", pk)
    t_vol = [float(v) for v in re.findall(r"(?:^|[^\d.])(\d+(?:\.\d+)?)мл", re.sub(r"/\s*[\d.]+мл", "", T))]
    if vm and t_vol:
        ok = float(vm[-1]) in t_vol
        vols = ", ".join(f"{v:g}" for v in t_vol)
        out.append((ok, f"Ҳажми: {vm[-1]} мл" if ok else f"Ҳажми: каталог бўйича {vm[-1]} мл бўлиши керак, tasnif'да {vols} мл"))
    accepted = catalog()["accept"].get(gtin, [])
    res = [(True if not ok and txt.split(":")[0] in accepted else ok, txt) for ok, txt in out]
    return sorted(res, key=lambda x: 0 if not x[0] and x[1].split(":")[0] in MAIN else 1)


def own_block(own):
    e = lambda v: html.escape(str(v))
    gtin, name, brand, desc, pack = own
    title = e(name) + (f" ({e(brand)})" if brand and brand != name else "")
    return f"🏢 <b>BAYAN MEDICAL каталогида:</b> {title}\n📄 {e(desc)}\n📦 {e(pack)}"


def compare_block(own, item):
    res = compare(own, item)
    if not res:
        return ""
    bad = [t for ok, t in res if not ok]
    if not bad:
        return "✅ <b>Каталогга мос</b> (" + ", ".join(t.split(":")[0].lower() for _, t in res) + ")"
    lines = []
    main_n = sum(1 for t in bad if t.split(":")[0] in MAIN)
    head = [f"❗ {main_n} та асосий хато" if main_n else "", f"⚠️ {len(bad) - main_n} та бошқа фарқ" if len(bad) > main_n else ""]
    lines.append("<b>" + " · ".join(h for h in head if h) + "</b>")
    for t in bad:
        txt = html.escape(t)
        txt = re.sub(r"(каталог бўйича .+? бўлиши керак)", r"<u><b>\1</b></u>", txt)
        lines.append(("❗ <b>Асосий хато.</b> " if t.split(":")[0] in MAIN else "⚠️ ") + txt)
    return "\n".join(lines)


def has(v):
    return v is not None and str(v).strip() != ""


def render(item, card):
    c = dict(item)
    c.update(card or {})
    e = lambda v: html.escape(str(v))
    lines = [f"✅ <b>ИКПУ:</b> <code>{e(c.get('mxikCode'))}</code>",
             f"<b>{e(c.get('mxikName') or c.get('name') or '')}</b>", ""]
    unit = c.get("unitName")
    if has(c.get("commonUnitName")) and c.get("commonUnitName") != unit:
        unit = f"{unit} / {c['commonUnitName']}" if has(unit) else c["commonUnitName"]
    rows = [
        ("🏭 Ишлаб чиқарувчи / бренд", c.get("brandName")),
        ("📏 Ўлчов бирлиги", unit),
        ("🔢 Штрих код", c.get("internationalCode")),
        ("🏷 Маркировка", "Мажбурий" if str(c.get("label")) == "1" else None),
        ("📝 Хусусияти", c.get("attributeName")),
        ("💊 ХПН", c.get("mnnName")),
        ("💰 Солиқ имтиёзи", c.get("lgotaName")),
    ]
    lines += [f"{k}: {e(v)}" for k, v in rows if has(v)]
    tree = [(c.get(f"{k}Code"), c.get(f"{k}Name")) for k in ("group", "class", "position", "subPosition")]
    tree = [f"{e(code)} {e(name)}" for code, name in tree if has(name)]
    if tree:
        lines += ["", "<b>Таснифдаги ўрни:</b>"] + [f"• {t}" for t in tree]
    pk = c.get("packages") or []
    if pk:
        lines += ["", "<b>Қадоқ кодлари:</b>"]
        for p in pk:
            qty = f" — {p.get('parentValue')} {p.get('unitName') or ''}".rstrip() if has(p.get("parentValue")) else ""
            lines.append(f"• <code>{e(p.get('code'))}</code> {e(p.get('name') or p.get('nameUz') or '')}{e(qty)}")
    own = own_of(c.get("internationalCode"))
    if own:
        lines += ["", own_block(own), "", "<b>Каталог бўйича текширув:</b>", compare_block(own, c)]
    return "\n".join(lines)[:4000]


HELP = ("Штрих код (GTIN) ёки 17 хонали ИКПУ кодини юборинг.\n"
        "Штрих код: 8, 12, 13 ёки 14 рақам (0 билан бошланса ҳам бўлади).\n"
        "ИКПУ коди: 17 рақам.")


def answer(text):
    code = re.sub(r"\D+", "", text or "")
    if (text or "").strip().startswith("/") or not code:
        return [HELP]
    is_ikpu = len(code) == 17
    if not is_ikpu and len(code) not in (8, 12, 13, 14):
        return [f"⚠️ {len(code)} та рақам киритдингиз.\n\n{HELP}"]
    try:
        items = find_by_ikpu(code) if is_ikpu else find_by_barcode(code)
    except Exception as ex:
        return [f"❌ tasnif.soliq.uz билан боғланиб бўлмади. Кейинроқ уриниб кўринг.\n<i>{html.escape(str(ex))}</i>"]
    if not items:
        if is_ikpu:
            return [f"❌ {code} ИКПУ коди базада топилмади."]
        own = own_of(code)
        return [f"❌ Бу штрих код ({code}) учун ИКПУ топилмади." + (f"\n\n{own_block(own)}" if own else "")]
    return [render(i, get_card(i.get("mxikCode"))) for i in items[:5]]


class Bot:
    def __init__(self, token):
        self.base = f"https://api.telegram.org/bot{token}"

    def call(self, method, http_timeout=40, **params):
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(f"{self.base}/{method}", data=data)
        with urllib.request.urlopen(req, timeout=http_timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def run(self):
        me = self.call("getMe")["result"]
        print(f"Бот ишга тушди: @{me['username']}.", flush=True)
        offset = 0
        while True:
            try:
                updates = self.call("getUpdates", http_timeout=70, offset=offset, timeout=50)["result"]
            except urllib.error.HTTPError as ex:
                if ex.code == 409:
                    # Telegram lets only one copy poll: the bot also runs elsewhere (e.g. start.bat on a PC).
                    print("409: бот бошқа жойда ҳам ишлаяпти (масалан, компьютердаги start.bat). Уни ёпинг.", flush=True)
                    time.sleep(30)
                else:
                    print("Telegram хатоси, қайта уриняпман:", ex, flush=True)
                    time.sleep(5)
                continue
            except Exception as ex:
                print("Telegram билан алоқа узилди, қайта уриняпман:", ex, flush=True)
                time.sleep(5)
                continue
            for u in updates:
                offset = u["update_id"] + 1
                msg = u.get("message") or {}
                chat = (msg.get("chat") or {}).get("id")
                if not chat:
                    continue
                print(time.strftime("%H:%M:%S"), chat, msg.get("text"), flush=True)
                try:
                    self.call("sendChatAction", chat_id=chat, action="typing")
                    for part in answer(msg.get("text")):
                        self.call("sendMessage", chat_id=chat, text=part, parse_mode="HTML")
                except Exception as ex:
                    print("Жавоб юборишда хато:", ex)


if __name__ == "__main__":
    Bot(load_token()).run()
