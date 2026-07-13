# family-car — ジェイド中古車 Top10 自動更新サイト

宇都宮起点・車で片道約2時間圏（栃木・群馬・茨城・埼玉・福島）の Honda ジェイド中古車を
カーセンサーから毎日取得し、距離・新しさ・価格でスコアリングした Top10 を
GitHub Pages に自動公開する。全処理は GitHub Actions（public リポ無料枠）で完結。

- 公開URL（Pages有効化後）: https://superduperohiolife-lgtm.github.io/family-car/
- 更新頻度: 毎日 06:00 JST（cron）＋手動実行可
- 費用: 0円（public リポの標準ランナー・Pages は無料）

## ディレクトリ構成

| ファイル | 役割 |
|---|---|
| `config.py` | 重み・対象県・予算・しきい値・距離（**編集はここだけでOK**） |
| `carsensor.py` | カーセンサー取得＋パース（robots許可ページのみ・UA明示・ウェイト） |
| `score.py` | min-max正規化＋加重平均でスコア算出 |
| `build.py` | 取得→採点→HTML生成→`public/index.html` 出力（フェイルセーフ内蔵） |
| `template.html` | 出力HTMLテンプレート（プレースホルダ差込式） |
| `.github/workflows/deploy.yml` | 毎日cron→build→Pagesデプロイ |
| `requirements.txt` | 依存（requests, beautifulsoup4） |

## セットアップ手順（Claude Code / GitHub）

1. GitHub に **public** リポ `family-car` を作成（オーナー: superduperohiolife-lgtm）
2. 本ディレクトリ一式を push（UTF-8・改行LF）
   ```bash
   git init && git add . && git commit -m "init: jade top10 auto-deploy"
   git branch -M main
   git remote add origin https://github.com/superduperohiolife-lgtm/family-car.git
   git push -u origin main
   ```
3. リポ **Settings → Pages → Build and deployment → Source＝「GitHub Actions」** に設定
4. **Actions** タブで `daily-deploy` を選び **Run workflow**（`workflow_dispatch`）で初回手動実行
5. 完了後、公開URLを確認し Natsuko へ共有

## スケジュール変更

`.github/workflows/deploy.yml` の cron（UTC）を編集。
`0 21 * * *` = 毎日 21:00 UTC = **翌 06:00 JST**。
例: 07:00 JST にするなら `0 22 * * *`。

## カスタマイズ（config.py）

- `WEIGHTS`: スコア重み。現在 `距離5・新しさ4・価格1`
- `PREFS`: 対象県（カーセンサー エリアコード）と宇都宮からの代表距離
- `BUDGET_MAN`: 支払総額の上限（万円）。`None` で無制限
- `EXCLUDE_REPAIR`: 修復歴ありを除外
- `MIN_LISTINGS` / `MIN_PREFS_WITH_DATA`: フェイルセーフ下限
- `CITY_KM`: 市区町村の推定距離（無い市は県代表値にフォールバック）

## フェイルセーフ（誤情報を出さない設計）

- 通過物件が `MIN_LISTINGS` 未満、またはデータ取得県が `MIN_PREFS_WITH_DATA` 未満 → **非0終了しデプロイ中止**
- 必須項目（年式・走行・価格・修復歴・距離）が取れない物件は**推測せず除外**
- カーセンサーのHTML構造が変わりパースが崩れた場合も、上記により**空/誤ったページは公開されない**（Actionsが失敗通知）

## データ区分・免責

- ✅確定（準一次）: 年式・走行距離・支払総額・修復歴・所在地・URL＝カーセンサー実掲載ページ
- △推定: 宇都宮からの距離(km)。総合スコアはこの推定を含む算出値
- 在庫・価格は流動的。商談前に各物件リンクと販売店で最新確認

## 取得ポリシー / 注意

- robots.txt で対象ページ（`/usedcar/bHO/s105/...`・`/usedcar/detail/...`）は Disallow 対象外（2026-07 確認）
- 利用規約（ToS）上の自動取得可否は**要確認**。個人利用・日1回・UA明示・リクエスト間ウェイト（1.5秒）で運用
- 過度な頻度・並列は避ける

## ローカル実行（任意）

```bash
pip install -r requirements.txt
python build.py    # public/index.html を生成
```
