# -*- coding: utf-8 -*-
"""オーケストレーション：取得→採点→HTML生成→public/index.html 出力。
フェイルセーフ：取得が異常に少ない場合は非0終了しデプロイを中止（誤情報・空ページを公開しない）。
"""
import sys, html, datetime, os
import config
from carsensor import fetch_all
from score import score

def _bar(v, color):
    return f'<div class="bar"><span style="width:{v:.0f}%;background:{color}"></span><b>{v:.0f}</b></div>'

def _row(r, top=False):
    cls = "toprow" if top else ""
    return f'''<tr class="{cls}">
<td class="rk">{r["rank"]}</td>
<td class="sc"><b>{r["total"]:.1f}</b></td>
<td>{html.escape(r["pref_name"])}<br><span class="city">{html.escape(str(r["city"]))}</span></td>
<td class="gr">{html.escape(str(r["grade"]))}</td>
<td class="num">{r["year"]}</td>
<td class="num">{r["mil"]:.1f}</td>
<td class="num">{r["price"]:.1f}</td>
<td class="num dist">~{r["dist"]}</td>
<td>{_bar(r["dsc"],"#2a7de1")}</td>
<td>{_bar(r["new"],"#17a673")}</td>
<td>{_bar(r["psc"],"#e0902a")}</td>
<td><a href="{r["url"]}" target="_blank" rel="noopener">確認 &#8599;</a></td>
</tr>'''

def _stats_table(stats):
    head = '<table style="font-size:12px"><thead><tr><th>県</th><th>一覧掲載</th><th>条件通過</th></tr></thead><tbody>'
    body = "".join(f'<tr><td>{html.escape(k)}</td><td class="num">{v["listed"]}</td><td class="num">{v["passed"]}</td></tr>' for k, v in stats.items())
    return head + body + "</tbody></table>"

def main():
    rows, stats = fetch_all()
    rows = score(rows)

    # --- フェイルセーフ ---
    n = len(rows)
    prefs_with_data = sum(1 for v in stats.values() if v["passed"] > 0)
    if n < config.MIN_LISTINGS:
        print(f"[FAIL] 通過物件 {n} < {config.MIN_LISTINGS}。異常のためデプロイ中止。", file=sys.stderr)
        sys.exit(1)
    if prefs_with_data < config.MIN_PREFS_WITH_DATA:
        print(f"[FAIL] データ取得県 {prefs_with_data} < {config.MIN_PREFS_WITH_DATA}。中止。", file=sys.stderr)
        sys.exit(1)

    jst = datetime.timezone(datetime.timedelta(hours=9))
    date = datetime.datetime.now(jst).strftime("%Y-%m-%d %H:%M JST")

    tpl = open("template.html", encoding="utf-8").read()
    top_html = "\n".join(_row(r, True) for r in rows[:10])
    rest_html = "\n".join(_row(r) for r in rows[10:])
    w = config.WEIGHTS
    repl = {
        "{{ROWS_TOP}}": top_html, "{{ROWS_REST}}": rest_html or "<tr><td colspan='12'>該当なし</td></tr>",
        "{{DATE}}": date, "{{N}}": str(n), "{{NPREF}}": str(len(config.PREFS)),
        "{{W_D}}": str(w["distance"]), "{{W_N}}": str(w["newness"]), "{{W_P}}": str(w["price"]),
        "{{BUDGET}}": str(config.BUDGET_MAN), "{{STATS}}": _stats_table(stats),
    }
    for k, v in repl.items():
        tpl = tpl.replace(k, v)

    os.makedirs("public", exist_ok=True)
    with open("public/index.html", "w", encoding="utf-8", newline="\n") as f:
        f.write(tpl)
    print(f"[OK] public/index.html 生成完了（{n}台・{date}）")

if __name__ == "__main__":
    main()
