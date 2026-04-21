# salary-research

福祉・保育業界の給与水準を定期調査・可視化するシステム。

## アーキテクチャ

```
salary-research/
├── .github/workflows/weekly_survey.yml  # GitHub Actions（毎週月曜 9:00 JST）
├── scripts/
│   ├── scrape_indeed.py                 # Indeed求人スクレイピング（Selenium）
│   ├── scrape_careers.py               # 各社採用ページ直接スクレイピング
│   └── generate_report.py              # HTMLレポート生成
├── data/
│   └── salary_master.csv               # 累積給与データ（追記形式）
├── docs/
│   └── index.html                      # GitHub Pages公開レポート
├── requirements.txt
└── CLAUDE.md
```

## 調査対象

**企業（7社）**: リタリコ、コペル、LUMO、TAKUMI、ネイスプラス、リーフプラス、ビーマスポーツ

**資格（5種）**: 児童発達支援管理責任者、児童指導員、保育士、作業療法士、理学療法士

**エリア分類**: 首都圏（東京・神奈川・埼玉・千葉）/ 関西（大阪・京都・兵庫・奈良）/ 東海（愛知・静岡・岐阜・三重）/ その他

## データフォーマット（salary_master.csv）

| カラム | 説明 |
|--------|------|
| date | 収集日（YYYY-MM-DD） |
| company | 検索した企業名 |
| qualification | 検索した資格名 |
| job_title | 求人タイトル |
| location | 勤務地（テキスト） |
| area | エリア分類 |
| salary_min | 給与下限（円） |
| salary_max | 給与上限（円） |
| salary_type | 給与種別（monthly/annual/hourly/daily） |
| salary_raw | 給与テキスト原文 |
| source_url | Indeed求人URL（重複排除キー） |

## ローカル実行

```bash
pip install -r requirements.txt
python scripts/scrape_indeed.py    # Indeed収集（数十分かかる場合あり）
python scripts/scrape_careers.py   # 各社採用ページ収集
python scripts/generate_report.py  # レポート生成
```

## GitHub Pages設定

Settings → Pages → Source: `Deploy from branch` → Branch: `main` / folder: `/docs`

## 各社採用ページURL

| 企業 | 採用ページURL |
|------|--------------|
| リタリコ | https://recruit.litalico.jp/ |
| コペル | https://copelplus.copel.co.jp/saiyou/ |
| LUMO | https://gotoschool.co.jp/recruit/ |
| TAKUMI | https://initias-recruit.jp/recruit/ |
| ネイスプラス | https://ne-is.com/recruit/ |
| リーフプラス | 調査中（503エラー） |
| ビーマスポーツ | https://www.biimasports-recruit.com/ |

## 注意事項

- Indeedの HTML 構造変更でセレクタが機能しなくなることがある。その場合は `scrape_indeed.py` のセレクタを修正する。
- レート制限のため1回の全件スクレイピングに15〜30分かかる。
- 同一URLは重複して記録しない（`source_url` で重複排除）。
- `scrape_careers.py` はリタリコ・ビーマスポーツのみSeleniumを使用（Python sandboxのDNS制限回避）。
