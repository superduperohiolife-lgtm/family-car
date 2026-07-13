# -*- coding: utf-8 -*-
"""カーセンサーから対象車種・対象県の在庫を取得しパースする。

暴走防止の要点:
 - 一覧ページには「おすすめ車」ブロックがあり毎回異なる詳細番号を出すため、
   単純なページ送りは無限に近く膨張する。→「掲載台数(XX台)＋余裕」で打ち切る。
 - 非結果セクションはマーカーで切り落としてから番号抽出。
 - 各詳細ページはタイトルで車種確認し、ジェイド以外は除外。
robots.txt で /usedcar/bHO/... と /usedcar/detail/... は Disallow 対象外（2026-07 確認）。
"""
import re, time, sys
import requests
from bs4 import BeautifulSoup
import config

BASE = "https://www.carsensor.net"
UA = "family-car-bot/1.0 (personal daily update; +https://superduperohiolife-lgtm.github.io/family-car/)"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"}
TIMEOUT = 30
SLEEP = getattr(config, "REQUEST_SLEEP", 1.0)
MAX_PAGES = getattr(config, "MAX_PAGES", 6)
ID_MARGIN = getattr(config, "ID_MARGIN", 15)
ABS_MAX = getattr(config, "ABS_MAX_PER_PREF", 70)

# 結果一覧より後（=おすすめ/関連/フッター）を切り落とすマーカー
CUT_MARKERS = [
    "おススメの中古車", "おすすめの中古車", "他の車種から中古車を探す",
    "中古車情報カーセンサー関連サイト", "この車種の中古車を都道府県",
    "都道府県から中古車を探す",
]

PREF_NAMES = ["北海道","青森県","岩手県","宮城県","秋田県","山形県","福島県","茨城県","栃木県",
"群馬県","埼玉県","千葉県","東京都","神奈川県","新潟県","富山県","石川県","福井県","山梨県",
"長野県","岐阜県","静岡県","愛知県","三重県","滋賀県","京都府","大阪府","兵庫県","奈良県",
"和歌山県","鳥取県","島根県","岡山県","広島県","山口県","徳島県","香川県","愛媛県","高知県",
"福岡県","佐賀県","長崎県","熊本県","大分県","宮崎県","鹿児島県","沖縄県"]

_session = requests.Session()
_session.headers.update(HEADERS)

def _get(url):
    r = _session.get(url, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text

def _cut_recommendations(html):
    """結果一覧より後ろ（おすすめ等）を切り落とす。マーカーが無ければ全体を返す。"""
    idx = len(html)
    for m in CUT_MARKERS:
        i = html.find(m)
        if 0 <= i < idx:
            idx = i
    return html[:idx]

def _parse_count(html):
    """「XX台」の掲載台数（ASCII数字のみ＝広告の全角台数は拾わない）。無ければ None"""
    m = re.search(r"(\d{1,4})\s*台\s*検索する", html) or re.search(r"(\d{1,4})\s*台", html)
    return int(m.group(1)) if m else None

def collect_detail_ids(area_code):
    """県別一覧から詳細ID(AU########)を、掲載台数＋余裕を上限に収集"""
    ids, seen = [], set()
    cap = ABS_MAX
    for n in range(1, MAX_PAGES + 1):
        page = "index.html" if n == 1 else f"index{n}.html"
        url = f"{BASE}/usedcar/{config.MAKER_CODE}/{config.MODEL_CODE}/{area_code}/{page}"
        try:
            html = _get(url)
        except requests.HTTPError:
            break
        if n == 1:
            cnt = _parse_count(html)
            if cnt:
                cap = min(ABS_MAX, cnt + ID_MARGIN)
        body = _cut_recommendations(html)
        found = re.findall(r"/usedcar/detail/(AU\d+)/index\.html", body)
        new = [x for x in found if x not in seen]
        if not new:
            break
        for x in new:
            seen.add(x); ids.append(x)
            if len(ids) >= cap:
                return ids[:cap]
        time.sleep(SLEEP)
    return ids

def _num_after(text, label, unit, window=80):
    i = text.find(label)
    if i < 0:
        return None
    seg = text[i + len(label): i + len(label) + window]
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*" + re.escape(unit), seg)
    return float(m.group(1).replace(",", "")) if m else None

def _year_after(text, window=30):
    i = text.find("年式")
    if i < 0:
        return None
    m = re.search(r"(20\d{2})", text[i: i + window])
    return int(m.group(1)) if m else None

def _distance_and_city(addr, pref):
    if addr:
        for key in sorted(config.CITY_KM, key=len, reverse=True):
            if key in addr:
                return config.CITY_KM[key], key
    for _, info in config.PREFS.items():
        if pref and info["name"] == pref:
            return info["km"], (pref or "不明")
    return None, (pref or "不明")

def parse_detail(auid):
    url = f"{BASE}/usedcar/detail/{auid}/index.html"
    html = _get(url)
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    t = soup.title.string if soup.title else ""
    # 車種確認：タイトルに「ジェイド」が無ければ対象外（おすすめ混入を除外）
    if "ジェイド" not in (t or ""):
        return None
    grade = None
    mg = re.search(r"ジェイド\s*(.+?)\s*[（(]", t or "")
    if mg:
        grade = mg.group(1).strip()

    year = _year_after(text)
    mil = _num_after(text, "走行距離", "万km")
    price = _num_after(text, "支払総額（税込）", "万円")
    if price is None:
        price = _num_after(text, "車両本体価格（税込）", "万円")
    mr = re.search(r"修復歴[^なあ無有]{0,8}(なし|あり|無|有)", text)
    repair = ("なし" if mr.group(1) in ("なし", "無") else "あり") if mr else None

    pref = None; addr = None
    ma = re.search(r"住所[：:]\s*([^\s　]+)", text)
    if ma:
        addr = ma.group(1)
        for p in PREF_NAMES:
            if addr.startswith(p):
                pref = p.replace("県", "").replace("都", "").replace("府", "")
                break
    dist, city = _distance_and_city(addr or text, pref)
    ms = re.search(r"販売店名[：:]\s*([^\n<]+?)\s{2,}", text) or re.search(r"販売店名[：:]\s*(\S+)", text)
    shop = ms.group(1).strip() if ms else None

    return {"auid": auid, "url": url, "grade": grade, "year": year, "mil": mil,
            "price": price, "repair": repair, "pref": pref, "city": city, "dist": dist, "shop": shop}

def fetch_all():
    rows, stats = [], {}
    for code, info in config.PREFS.items():
        ids = collect_detail_ids(code)
        got = 0
        for auid in ids:
            try:
                d = parse_detail(auid)
            except Exception as e:
                print(f"[warn] parse失敗 {auid}: {e}", file=sys.stderr)
                time.sleep(SLEEP); continue
            time.sleep(SLEEP)
            if d is None:
                continue
            # 必須項目（グレード=ジェイド確認済 含む）。欠落は推測せず除外
            if None in (d["grade"], d["year"], d["mil"], d["price"], d["repair"], d["dist"]):
                continue
            if config.EXCLUDE_REPAIR and d["repair"] == "あり":
                continue
            if config.BUDGET_MAN and d["price"] > config.BUDGET_MAN:
                continue
            d["pref_name"] = info["name"]
            rows.append(d); got += 1
        stats[info["name"]] = {"listed": len(ids), "passed": got}
        print(f"[info] {info['name']}: 詳細取得{len(ids)}件 → 通過{got}件")
    return rows, stats
