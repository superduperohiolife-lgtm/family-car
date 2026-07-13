# -*- coding: utf-8 -*-
"""カーセンサーから対象車種・対象県の在庫を取得しパースする。

方針:
 1) 県別一覧ページ（index/index2…）から詳細URL(AU########)を収集
 2) 各詳細ページを取得し、ラベル文言ベースで堅牢に項目抽出
 3) 取得できない値は None（推測で埋めない）
robots.txt で /usedcar/bHO/... と /usedcar/detail/... は Disallow 対象外（2026-07 確認）。
低頻度・UA明示・リクエスト間ウェイトで運用。
"""
import re, time, sys
import requests
from bs4 import BeautifulSoup
import config

BASE = "https://www.carsensor.net"
UA = "family-car-bot/1.0 (personal daily update; +https://superduperohiolife-lgtm.github.io/family-car/)"
HEADERS = {"User-Agent": UA, "Accept-Language": "ja,en;q=0.8"}
SLEEP = 1.5          # リクエスト間の待機（秒）
MAX_PAGES = 15       # 1県あたりの一覧ページ上限（安全弁）
TIMEOUT = 30

PREF_NAMES = ["北海道","青森県","岩手県","宮城県","秋田県","山形県","福島県","茨城県","栃木県",
"群馬県","埼玉県","千葉県","東京都","神奈川県","新潟県","富山県","石川県","福井県","山梨県",
"長野県","岐阜県","静岡県","愛知県","三重県","滋賀県","京都府","大阪府","兵庫県","奈良県",
"和歌山県","鳥取県","島根県","岡山県","広島県","山口県","徳島県","香川県","愛媛県","高知県",
"福岡県","佐賀県","長崎県","熊本県","大分県","宮崎県","鹿児島県","沖縄県"]

def _get(url):
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    r.encoding = r.apparent_encoding or "utf-8"
    return r.text

def collect_detail_ids(area_code):
    """県別一覧をページ送りしながら詳細ID(AU########)を収集"""
    ids = []
    seen = set()
    for n in range(1, MAX_PAGES + 1):
        page = "index.html" if n == 1 else f"index{n}.html"
        url = f"{BASE}/usedcar/{config.MAKER_CODE}/{config.MODEL_CODE}/{area_code}/{page}"
        try:
            html = _get(url)
        except requests.HTTPError:
            break
        found = re.findall(r"/usedcar/detail/(AU\d+)/index\.html", html)
        new = [x for x in found if x not in seen]
        if not new:
            break
        for x in new:
            seen.add(x); ids.append(x)
        time.sleep(SLEEP)
    return ids

def _num_after(text, label, unit, window=80):
    """label 出現位置から window 文字以内で最初に現れる「数値+unit」を返す。無ければ None。
    間にヘルプリンク文言等が挟まっても拾えるよう、ラベル基点のスライス探索とする。"""
    i = text.find(label)
    if i < 0:
        return None
    seg = text[i + len(label): i + len(label) + window]
    m = re.search(r"([\d,]+(?:\.\d+)?)\s*" + re.escape(unit), seg)
    if not m:
        return None
    return float(m.group(1).replace(",", ""))

def _year_after(text, window=30):
    i = text.find("年式")
    if i < 0:
        return None
    m = re.search(r"(20\d{2})", text[i: i + window])
    return int(m.group(1)) if m else None

def parse_detail(auid):
    url = f"{BASE}/usedcar/detail/{auid}/index.html"
    html = _get(url)
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)

    # グレード（title: "ジェイド 1.5 ハイブリッド X(栃木)の中古車詳細 …"）
    grade = None
    t = soup.title.string if soup.title else ""
    mg = re.search(r"ジェイド\s*(.+?)\s*[（(]", t or "")
    if mg:
        grade = mg.group(1).strip()

    # 年式（西暦4桁）
    year = _year_after(text)

    # 走行距離（万km）
    mil = _num_after(text, "走行距離", "万km")

    # 支払総額（税込, 万円）→ 無ければ本体価格
    price = _num_after(text, "支払総額（税込）", "万円")
    price_kind = "支払総額"
    if price is None:
        price = _num_after(text, "車両本体価格（税込）", "万円")
        price_kind = "本体価格" if price is not None else None

    # 修復歴
    mr = re.search(r"修復歴[^なあ無有]{0,8}(なし|あり|無|有)", text)
    repair = None
    if mr:
        repair = "なし" if mr.group(1) in ("なし", "無") else "あり"

    # 住所 → 県・市区町村
    pref = None; city = None; addr = None
    ma = re.search(r"住所[：:]\s*([^\s　]+)", text)
    if ma:
        addr = ma.group(1)
        for p in PREF_NAMES:
            if addr.startswith(p):
                pref = p.replace("県", "").replace("都", "").replace("府", "")
                break
    # 市区町村は距離辞書の最長一致で表示・距離判定
    dist, city = _distance_and_city(addr or text, pref)

    # 販売店
    ms = re.search(r"販売店名[：:]\s*([^\n<]+?)\s{2,}", text) or re.search(r"販売店名[：:]\s*(\S+)", text)
    shop = ms.group(1).strip() if ms else None

    return {
        "auid": auid, "url": url, "grade": grade, "year": year, "mil": mil,
        "price": price, "price_kind": price_kind, "repair": repair,
        "pref": pref, "city": city, "dist": dist,
    }

def _distance_and_city(addr, pref):
    """距離辞書の最長キー一致で距離と市名を決定。無ければ県代表値。"""
    if addr:
        for key in sorted(config.CITY_KM, key=len, reverse=True):
            if key in addr:
                return config.CITY_KM[key], key
    # フォールバック：県の代表距離
    for code, info in config.PREFS.items():
        if pref and info["name"] == pref:
            return info["km"], (pref or "不明")
    return None, (pref or "不明")

def fetch_all():
    """対象県すべての通過物件と、県別の取得統計を返す"""
    rows = []
    stats = {}
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
            # 必須項目チェック（欠落は捨てる：推測で埋めない）
            if None in (d["year"], d["mil"], d["price"], d["repair"], d["dist"]):
                continue
            if config.EXCLUDE_REPAIR and d["repair"] == "あり":
                continue
            if config.BUDGET_MAN and d["price"] > config.BUDGET_MAN:
                continue
            d["pref_name"] = info["name"]
            rows.append(d); got += 1
        stats[info["name"]] = {"listed": len(ids), "passed": got}
        print(f"[info] {info['name']}: 一覧{len(ids)}件 → 通過{got}件")
    return rows, stats
