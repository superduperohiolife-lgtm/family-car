# -*- coding: utf-8 -*-
"""カーセンサー 一覧ページから対象車種・対象県の在庫を取得・解析する。

設計（重要）:
 - 一覧の各カードに「グレード/支払総額/年式/走行距離/修復歴/県・市/詳細URL」が全て揃う。
   → 詳細ページは取得しない（数十回のアクセス＝レート制限で48分暴走・タイムアウトの原因）。
 - 一覧ページ内の /usedcar/detail/AU… リンクは結果カードのみ（おすすめ枠は /lease/ や /catalog/）。
 - 詳細IDの初出位置でHTMLをカード単位に区切り、各カードのget_textから項目を抽出。
 - 値には妥当域チェック（誤抽出=範囲外は除外）。IDで重複排除。
robots.txt で /usedcar/bHO/... は Disallow 対象外（2026-07 確認）。
"""
import re, time, sys
import requests
from bs4 import BeautifulSoup
import config

BASE = "https://www.carsensor.net"
UA = "family-car-bot/1.0 (personal daily update; +https://superduperohiolife-lgtm.github.io/family-car/)"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"}
TIMEOUT = 30
SLEEP = getattr(config, "REQUEST_SLEEP", 1.5)
MAX_PAGES = getattr(config, "MAX_PAGES", 6)

# 結果一覧より後ろ（おすすめ/比較/リース/フッター）を切り落とすマーカー
CUT_MARKERS = ["よく一緒に検討されている", "お探しの車種でリース", "最新情報をお届け",
               "この車種のクチコミ", "ジェイドに関するクチコミ", "リースできるクルマ"]

PREF_NAMES = ["北海道","青森県","岩手県","宮城県","秋田県","山形県","福島県","茨城県","栃木県",
"群馬県","埼玉県","千葉県","東京都","神奈川県","新潟県","富山県","石川県","福井県","山梨県",
"長野県","岐阜県","静岡県","愛知県","三重県","滋賀県","京都府","大阪府","兵庫県","奈良県",
"和歌山県","鳥取県","島根県","岡山県","広島県","山口県","徳島県","香川県","愛媛県","高知県",
"福岡県","佐賀県","長崎県","熊本県","大分県","宮崎県","鹿児島県","沖縄県"]
_PREF_RE = re.compile(r"(" + "|".join(PREF_NAMES) + r")\s+(\S{1,8}?[市区町村郡])")

_session = requests.Session()
_session.headers.update(HEADERS)

def _get(url):
    r = _session.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text

def _cut_footer(html):
    idx = len(html)
    for m in CUT_MARKERS:
        i = html.find(m)
        if 0 <= i < idx:
            idx = i
    return html[:idx]

def _parse_count(html):
    m = re.search(r"(\d{1,4})\s*台\s*検索する", html) or re.search(r"(\d{1,4})\s*台", html)
    return int(m.group(1)) if m else None

def _num_after(text, label, unit, window=40):
    i = text.find(label)
    if i < 0:
        return None
    seg = text[i + len(label): i + len(label) + window]
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*" + re.escape(unit), seg)
    return float(m.group(1).replace(",", "")) if m else None

def _year(text):
    i = text.find("年式")
    if i < 0:
        return None
    m = re.search(r"(20\d{2})", text[i: i + 20])
    return int(m.group(1)) if m else None

def _distance_and_city(text, pref_name, pref_km):
    for key in sorted(config.CITY_KM, key=len, reverse=True):
        if key in text:
            return config.CITY_KM[key], key
    return pref_km, pref_name  # フォールバック：県代表距離

def parse_card(card_html, pref_name, pref_km):
    text = BeautifulSoup(card_html, "html.parser").get_text(" ", strip=True)
    # グレード：get_text上「ジェイド <grade> 支払総額 …」（画像altは除外されるため最初のジェイドが車名見出し）
    mg = re.search(r"ジェイド\s+(.+?)\s+支払総額", text)
    grade = mg.group(1).strip() if mg else None
    price = _num_after(text, "支払総額", "万円")
    year = _year(text)
    mil = _num_after(text, "走行距離", "万km", window=16)
    mr = re.search(r"修復歴\s*(なし|あり|無|有)", text)
    repair = ("なし" if mr and mr.group(1) in ("なし", "無") else ("あり" if mr else None))
    mp = _PREF_RE.search(text)
    pref = mp.group(1).replace("県","").replace("都","").replace("府","") if mp else pref_name
    dist, city = _distance_and_city(text, pref_name, pref_km)
    return {"grade": grade, "price": price, "year": year, "mil": mil,
            "repair": repair, "pref": pref, "city": city, "dist": dist}

def _cards(html):
    """詳細IDの初出位置でHTMLをカードに分割。返り値 [(auid, card_html)]"""
    body = _cut_footer(html)
    first = {}
    for m in re.finditer(r"/usedcar/detail/(AU\d+)/index\.html", body):
        first.setdefault(m.group(1), m.start())
    items = sorted(first.items(), key=lambda kv: kv[1])  # 出現順
    out = []
    for i, (auid, pos) in enumerate(items):
        end = items[i + 1][1] if i + 1 < len(items) else len(body)
        out.append((auid, body[pos:end]))
    return out

def fetch_prefecture(area_code, pref_name, pref_km):
    rows, seen = [], set()
    count = None
    for n in range(1, MAX_PAGES + 1):
        page = "index.html" if n == 1 else f"index{n}.html"
        url = f"{BASE}/usedcar/{config.MAKER_CODE}/{config.MODEL_CODE}/{area_code}/{page}"
        try:
            html = _get(url)
        except requests.HTTPError:
            break
        if n == 1:
            count = _parse_count(html)
        cards = _cards(html)
        new_ct = 0
        for auid, chtml in cards:
            if auid in seen:
                continue
            seen.add(auid); new_ct += 1
            d = parse_card(chtml, pref_name, pref_km)
            d["auid"] = auid
            d["url"] = f"{BASE}/usedcar/detail/{auid}/index.html"
            rows.append(d)
        if new_ct == 0:
            break
        if count and len(seen) >= count:
            break
        time.sleep(SLEEP)
    return rows, (count if count is not None else len(rows))

# 妥当域（誤抽出の除外）
YEAR_MIN, YEAR_MAX = 2013, 2021   # ジェイド生産 2015-2020（余裕）
PRICE_MIN, PRICE_MAX = 20, 400
MIL_MAX = 25

def fetch_all():
    rows, stats = [], {}
    for code, info in config.PREFS.items():
        pref_rows, listed = fetch_prefecture(code, info["name"], info["km"])
        passed = 0
        for d in pref_rows:
            if None in (d["grade"], d["year"], d["mil"], d["price"], d["repair"], d["dist"]):
                continue
            if not (YEAR_MIN <= d["year"] <= YEAR_MAX): continue
            if not (PRICE_MIN <= d["price"] <= PRICE_MAX): continue
            if d["mil"] > MIL_MAX: continue
            if config.EXCLUDE_REPAIR and d["repair"] == "あり": continue
            if config.BUDGET_MAN and d["price"] > config.BUDGET_MAN: continue
            d["pref_name"] = info["name"]
            rows.append(d); passed += 1
        stats[info["name"]] = {"listed": listed, "passed": passed}
        print(f"[info] {info['name']}: 掲載{listed} → 通過{passed}")
        time.sleep(SLEEP)
    # 全体の重複除去（auid）
    uniq = {}
    for r in rows:
        uniq[r["auid"]] = r
    return list(uniq.values()), stats
