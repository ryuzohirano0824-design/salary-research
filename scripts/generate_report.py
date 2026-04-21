#!/usr/bin/env python3
"""給与レポートHTML生成スクリプト

salary_master.csv を読み込み、GitHub Pages 向けの index.html を生成する。
"""

import csv
import json
import statistics
from collections import defaultdict
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
DATA_FILE = BASE_DIR / "data" / "salary_master.csv"
OUTPUT_FILE = BASE_DIR / "docs" / "index.html"

COMPANIES = [
    "リタリコ", "コペル", "LUMO", "TAKUMI",
    "ネイスプラス", "リーフプラス", "ビーマスポーツ",
]
QUALIFICATIONS = [
    "児童発達支援管理責任者", "児童指導員", "保育士",
    "作業療法士", "理学療法士",
]
AREAS = ["首都圏", "関西", "東海", "その他"]

# Chart.js カラーパレット
COLORS = [
    "rgba(66,133,244,0.85)",   # blue
    "rgba(234,67,53,0.85)",    # red
    "rgba(251,188,5,0.85)",    # yellow
    "rgba(52,168,83,0.85)",    # green
    "rgba(255,109,0,0.85)",    # orange
]


def load_data() -> list:
    if not DATA_FILE.exists():
        return []
    with open(DATA_FILE, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def to_monthly(row: dict):
    """給与を月額換算（万円）して返す。算出できない場合は None。"""
    try:
        val = int(row["salary_min"])
        if not val:
            return None
        t = row.get("salary_type", "")
        if t == "monthly":
            return val / 10_000
        elif t == "annual":
            return val / 10_000 / 12
        elif t == "hourly":
            return val * 160 / 10_000   # 月160h想定
        elif t == "daily":
            return val * 20 / 10_000    # 月20日想定
    except (ValueError, TypeError):
        return None


def build_chart_data(rows: list) -> dict:
    """会社別・資格別の平均月額（万円）を Chart.js 形式で返す。"""
    bucket: dict = defaultdict(list)
    for r in rows:
        v = to_monthly(r)
        if v:
            bucket[(r["company"], r["qualification"])].append(v)

    datasets = []
    for i, qual in enumerate(QUALIFICATIONS):
        data = []
        for company in COMPANIES:
            vals = bucket.get((company, qual), [])
            data.append(round(statistics.mean(vals), 1) if vals else 0)
        datasets.append({
            "label": qual,
            "data": data,
            "backgroundColor": COLORS[i % len(COLORS)],
            "borderColor": COLORS[i % len(COLORS)].replace("0.85", "1"),
            "borderWidth": 1,
        })

    return {"labels": COMPANIES, "datasets": datasets}


def build_area_chart_data(rows: list) -> dict:
    """エリア別の平均月額を資格ごとに集計。"""
    bucket: dict = defaultdict(list)
    for r in rows:
        v = to_monthly(r)
        if v:
            bucket[(r["area"], r["qualification"])].append(v)

    datasets = []
    for i, qual in enumerate(QUALIFICATIONS):
        data = []
        for area in AREAS:
            vals = bucket.get((area, qual), [])
            data.append(round(statistics.mean(vals), 1) if vals else 0)
        datasets.append({
            "label": qual,
            "data": data,
            "backgroundColor": COLORS[i % len(COLORS)],
            "borderWidth": 1,
        })
    return {"labels": AREAS, "datasets": datasets}


def build_table_rows(rows: list) -> str:
    html = ""
    for r in sorted(rows, key=lambda x: x.get("date", ""), reverse=True)[:1000]:
        title = (r.get("job_title") or "")[:45]
        salary = r.get("salary_raw") or "－"
        url = r.get("source_url", "")
        area = r.get("area", "その他")
        html += (
            f"<tr>"
            f"<td>{r.get('date','')}</td>"
            f"<td>{r.get('company','')}</td>"
            f"<td>{r.get('qualification','')}</td>"
            f"<td class='title-cell'>{title}</td>"
            f"<td>{r.get('location','')}</td>"
            f"<td><span class='badge badge-{area}'>{area}</span></td>"
            f"<td class='salary-cell'>{salary}</td>"
            f"<td><a href='{url}' target='_blank' rel='noopener noreferrer'>🔗</a></td>"
            f"</tr>\n"
        )
    return html


def generate_html(rows: list) -> str:
    salary_rows = [r for r in rows if r.get("salary_min")]
    chart_data = build_chart_data(rows)
    area_chart_data = build_area_chart_data(rows)
    table_rows = build_table_rows(rows)

    today = date.today().strftime("%Y年%m月%d日")
    total = len(rows)
    with_salary = len(salary_rows)
    companies_found = len({r["company"] for r in rows})
    quals_found = len({r["qualification"] for r in rows if r["qualification"]})

    options_company = "\n".join(f"<option>{c}</option>" for c in COMPANIES)
    options_qual = "\n".join(f"<option>{q}</option>" for q in QUALIFICATIONS)
    options_area = "\n".join(f"<option>{a}</option>" for a in AREAS)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>福祉・保育業界 給与水準レポート</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>
*, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', sans-serif;
       background: #f4f6fb; color: #222; font-size: 14px; }}
header {{ background: linear-gradient(135deg,#1a73e8,#0d47a1); color:#fff;
          padding: 20px 32px; }}
header h1 {{ font-size: 20px; font-weight: 700; }}
header p  {{ font-size: 12px; opacity: .85; margin-top: 4px; }}
.container {{ max-width: 1280px; margin: 0 auto; padding: 20px 16px; }}
.stats {{ display: grid; grid-template-columns: repeat(auto-fit,minmax(140px,1fr));
          gap: 12px; margin-bottom: 20px; }}
.stat  {{ background:#fff; border-radius:8px; padding:14px 18px;
          box-shadow:0 1px 3px rgba(0,0,0,.08); }}
.stat .num   {{ font-size: 26px; font-weight:700; color:#1a73e8; }}
.stat .label {{ font-size: 11px; color:#777; margin-top:3px; }}
.card  {{ background:#fff; border-radius:8px; padding:20px 24px;
          box-shadow:0 1px 3px rgba(0,0,0,.08); margin-bottom:20px; }}
.card h2 {{ font-size:15px; font-weight:600; margin-bottom:14px; color:#333;
            border-left:3px solid #1a73e8; padding-left:10px; }}
.charts-row {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:20px; }}
@media(max-width:768px) {{ .charts-row {{ grid-template-columns:1fr; }} }}
.filter-bar {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:10px; }}
.filter-bar select {{ padding:5px 10px; border:1px solid #ddd; border-radius:4px;
                      font-size:13px; background:#fff; }}
.tbl-wrap {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th {{ background:#f0f4ff; text-align:left; padding:7px 10px;
      border-bottom:2px solid #ddd; white-space:nowrap; }}
td {{ padding:6px 10px; border-bottom:1px solid #f2f2f2; vertical-align:middle; }}
tr:hover td {{ background:#fafbff; }}
.title-cell {{ max-width:240px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }}
.salary-cell {{ font-weight:600; color:#1a73e8; white-space:nowrap; }}
.badge {{ display:inline-block; padding:1px 7px; border-radius:10px;
          font-size:11px; font-weight:600; }}
.badge-首都圏 {{ background:#e8f0fe; color:#1a73e8; }}
.badge-関西   {{ background:#fce8e6; color:#c5221f; }}
.badge-東海   {{ background:#fef7e0; color:#b06000; }}
.badge-その他 {{ background:#e6f4ea; color:#137333; }}
footer {{ text-align:center; font-size:12px; color:#aaa; padding:20px; }}
</style>
</head>
<body>
<header>
  <h1>📊 福祉・保育業界 給与水準レポート</h1>
  <p>最終更新: {today}　｜　Indeed求人データ自動収集　｜　毎週月曜 9:00 JST 更新</p>
</header>
<div class="container">

  <div class="stats">
    <div class="stat"><div class="num">{total}</div><div class="label">累計求人数</div></div>
    <div class="stat"><div class="num">{with_salary}</div><div class="label">給与記載あり</div></div>
    <div class="stat"><div class="num">{companies_found}</div><div class="label">対象企業数</div></div>
    <div class="stat"><div class="num">{quals_found}</div><div class="label">対象資格数</div></div>
  </div>

  <div class="charts-row">
    <div class="card">
      <h2>企業別・資格別 平均月給（万円）</h2>
      <canvas id="companyChart"></canvas>
    </div>
    <div class="card">
      <h2>エリア別・資格別 平均月給（万円）</h2>
      <canvas id="areaChart"></canvas>
    </div>
  </div>

  <div class="card">
    <h2>求人一覧</h2>
    <div class="filter-bar">
      <select id="fcCompany" onchange="filterTable()">
        <option value="">企業：すべて</option>
        {options_company}
      </select>
      <select id="fcQual" onchange="filterTable()">
        <option value="">資格：すべて</option>
        {options_qual}
      </select>
      <select id="fcArea" onchange="filterTable()">
        <option value="">エリア：すべて</option>
        {options_area}
      </select>
    </div>
    <div class="tbl-wrap">
      <table>
        <thead>
          <tr>
            <th>日付</th><th>企業</th><th>資格</th><th>求人タイトル</th>
            <th>勤務地</th><th>エリア</th><th>給与</th><th>URL</th>
          </tr>
        </thead>
        <tbody id="tblBody">
{table_rows}
        </tbody>
      </table>
    </div>
  </div>

</div>
<footer>データソース: Indeed Japan　｜　自動収集・研究目的のみ　｜　<a href="https://github.com" style="color:#aaa;">GitHub</a></footer>

<script>
const companyChart = new Chart(document.getElementById('companyChart'), {{
  type: 'bar',
  data: {json.dumps(chart_data, ensure_ascii=False)},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ position: 'top', labels: {{ font: {{ size: 11 }} }} }} }},
    scales: {{
      y: {{ title: {{ display: true, text: '万円/月' }}, beginAtZero: true }},
      x: {{ ticks: {{ font: {{ size: 10 }} }} }}
    }}
  }}
}});

const areaChart = new Chart(document.getElementById('areaChart'), {{
  type: 'bar',
  data: {json.dumps(area_chart_data, ensure_ascii=False)},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ position: 'top', labels: {{ font: {{ size: 11 }} }} }} }},
    scales: {{
      y: {{ title: {{ display: true, text: '万円/月' }}, beginAtZero: true }},
      x: {{ ticks: {{ font: {{ size: 11 }} }} }}
    }}
  }}
}});

function filterTable() {{
  const co = document.getElementById('fcCompany').value;
  const qu = document.getElementById('fcQual').value;
  const ar = document.getElementById('fcArea').value;
  document.querySelectorAll('#tblBody tr').forEach(tr => {{
    const c = tr.cells;
    tr.style.display =
      (!co || c[1].textContent === co) &&
      (!qu || c[2].textContent === qu) &&
      (!ar || c[5].textContent.trim() === ar)
      ? '' : 'none';
  }});
}}
</script>
</body>
</html>"""


def main() -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    rows = load_data()
    html = generate_html(rows)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"レポート生成完了: {OUTPUT_FILE}  ({len(rows)} 件)")


if __name__ == "__main__":
    main()
