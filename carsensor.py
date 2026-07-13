# -*- coding: utf-8 -*-
"""カーセンサー 一覧ページから対象車種・対象県の在庫を取得・解析する。

要点:
 - 各カードに「グレード/支払総額/年式/走行/修復歴/県市/URL」が揃うため詳細ページは取得しない。
 - カードはBeautifulSoupの要素ツリーで取得（文字列スライスはタグ途中で壊れるため禁止）。
   タイトルリンク<a href=/usedcar/detail/AU…>ジェイド…</a>を起点に、修復歴＋支払総額を含む
   最小の祖先要素＝カードとして、そのget_textから項目抽出。
 - 値は妥当域チェック（誤抽出は除外）。IDで重複排除。
robots.txt で /usedcar/bHO/... は Disallow 対象外（2026-07 確認）。
"""
import re, time, sys
import requests
from bs4 import BeautifulSoup
import config

BASE = "https://www.carsensor.net"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.9"}
TIMEOUT = 30
SLEEP = getattr(config, "REQUEST_SLEEP", 1.5)
MAX_PAGES = getattr(config, "MAX_PAGES", 6)
DEBUG = True   # 失敗診断用。安定後 False に

DETAIL_RE = re.compile(r"/usedcar/detail/(AU\d+)/index\.html")

PREF_NAMES = ["北海道","青森県","岩手県","宮城県","秋田県","山形県","福島県","茨城県","栃木県",
"群馬県","埼玉県","千葉県","東京都","神奈川県","新潟県","富山県","石川県","福井県","山梨県",
"長野県","岐阜県","静岡県","愛知県","三重県","滋賀県","京都府","大阪府","兵庫県","奈良県",
"和歌山県","鳥取県","島根県","岡山県","広島県","山口県","徳島県","香川県","愛媛県","高知県",
"福岡県","佐賀県","長崎県","熊本県","大分県","宮崎県","鹿児島県","沖縄県"]
_PREF_RE = re.compile(r"(" + "|".join(PREF_NAMES) + r")\s*([^\s　]{1,8}?[市区町村郡])")

_session = requests.Session()
_session.headers.update(HEADERS)

def _get(url):
    r = _session.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text

def _parse_count(soup):
    txt = soup.get_text(" ", strip=True)
    m = re.search(r"(\d{1,4})\s*台\s*検索する", txt)
    return int(m.group(1)) if m else None

def _num_after(text, label, unit, window=60):
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
    m = re.search(r"(20\d{2})", text[i: i + 24])
    return int(m.group(1)) if m else None

def _distance_and_city(text, pref_name, pref_km):
    for key in sorted(config.CITY_KM, key=len, reverse=True):
        if key in text:
            return config.CITY_KM[key], key
    return pref_km, pref_name

def _find_card(anchor):
    """タイトルリンクから、修復歴＋支払総額を含む最小の祖先要素（=カード）を返す"""
    node = anchor
    for _ in range(10):
        node = node.parent
        if node is None:
            return None
        t = node.get_text(" ", strip=True)
        if "修復歴" in t and "支払総額" in t:
            return node
    return None

def parse_card(card, pref_name, pref_km):
    text = re.sub(r"[　\xa0]", " ", card.get_text(" ", strip=True))
    price = _num_after(text, "支払総額", "万円")
    if price is None:
        price = _num_after(text, "車両本体価格", "万円")
    year = _year(text)
    mil = _num_after(text, "走行距離", "万km", window=24)
    mr = re.search(r"修復歴\s*[:：]?\s*(なし|あり|無|有)", text)
    repair = ("なし" if mr and mr.group(1) in ("なし", "無") else ("あり" if mr else None))
    mp = _PREF_RE.search(text)
    pref = mp.group(1).replace("県","").replace("都","").replace("府","") if mp else pref_name
    dist, city = _distance_and_city(text, pref_name, pref_km)
    return {"price": price, "year": year, "mil": mil, "repair": repair,
            "pref": pref, "city": city, "dist": dist, "_text": text}

def _cards_from_page(html):
    """(auid, grade, card_element) を結果カードぶん返す"""
    soup = BeautifulSoup(html, "html.parser")
    count = _parse_count(soup)
    out, seen = [], set()
    for a in soup.find_all("a", href=DETAIL_RE):
        txt = a.get_text(" ", strip=True)
        if not txt.startswith("ジェイド"):
            continue  # 画像リンク等は本文なし。タイトルリンクのみ採用
        auid = DETAIL_RE.search(a["href"]).group(1)
        if auid in seen:
            continue
        seen.add(auid)
        card = _find_card(a)
        if card is None:
            continue
        grade = re.sub(r"[　\xa0]", " ", txt)
        grade = re.sub(r"^ジェイド\s*", "", grade).strip()
        out.append((auid, grade, card))
    return out, count

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
        cards, cnt = _cards_from_page(html)
        if n == 1:
            count = cnt
            if DEBUG and cards:
                d0 = parse_card(cards[0][2], pref_name, pref_km)
                print(f"[dbg] {pref_name} cards={len(cards)} count={count} "
                      f"sample: grade={cards[0][1][:20]!r} year={d0['year']} mil={d0['mil']} "
                      f"price={d0['price']} repair={d0['repair']} city={d0['city']}", file=sys.stderr)
        new_ct = 0
        for auid, grade, card in cards:
            if auid in seen:
                continue
            seen.add(auid); new_ct += 1
            d = parse_card(card, pref_name, pref_km)
            d.update(auid=auid, grade=grade, url=f"{BASE}/usedcar/detail/{auid}/index.html")
            rows.append(d)
        if new_ct == 0:
            break
        if count and len(seen) >= count:
            break
        time.sleep(SLEEP)
    return rows, (count if count is not None else len(rows))

YEAR_MIN, YEAR_MAX = 2013, 2021
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
            d.pop("_text", None)
            rows.append(d); passed += 1
        stats[info["name"]] = {"listed": listed, "passed": passed}
        print(f"[info] {info['name']}: 掲載{listed} → 通過{passed}")
        time.sleep(SLEEP)
    uniq = {}
    for r in rows:
        uniq[r["auid"]] = r
    return list(uniq.values()), stats
