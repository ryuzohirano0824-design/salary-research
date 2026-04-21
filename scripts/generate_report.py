#!/usr/bin/env python3
"""給与レポートHTML生成スクリプト（改良版）

salary_master.csv を読み込み、GitHub Pages 向けの index.html を生成する。
・会社別×資格別 給与比較表
・給与レンジ浮動棒グラフ
・エリア別グラフ
・フィルター機能（会社・資格・エリア・ソース・給与あり絞り込み）
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
    "ネイスプラス", "リーフラス", "ビーマスポーツ",
]
QUALIFICATIONS = [
    "児童発達支援管理責任者", "児童指導員", "保育士",
    "作業療法士", "理学療法士",
]
AREAS = ["首都圏", "関西", "東海", "その他"]

PALETTE = [
    "#4285F4", "#EA4335", "#FBBC05", "#34A853", "#FF6D00",
    "#46BDC6", "#AB47BC",
]


# ── データ読み込み ──────────────────────────────────────────────────────────

def load_data() -> list:
    if not DATA_FILE.exists():
        return []
    with open(DATA_FILE, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


# ── 給与換算 ───────────────────────────────────────────────────────────────

def to_monthly(row: dict, field: str = "salary_min"):
    """給与を月額（万円）に換算。算出できない場合は None。"""
    try:
        val = int(row[field])
        if not val:
            return None
        t = row.get("salary_type", "")
        if t == "monthly":
            return val / 10_000
        elif t == "annual":
            return val / 10_000 / 12
        elif t == "hourly":
            return val * 160 / 10_000
        elif t == "daily":
            return val * 20 / 10_000
        elif t == "unknown":
            # 10万円以上なら月給とみなす（LUMOのプレフィックスなし形式など）
            if val >= 100_000:
                return val / 10_000
            elif val < 5_000:        # 時給相当
                return val * 160 / 10_000
        return None
    except (ValueError, TypeError, KeyError):
        return None


def fmt_man(v) -> str:
    return f"{v:.1f}" if v is not None else "—"


# ── グラフデータ ───────────────────────────────────────────────────────────

def build_range_chart_data(rows: list) -> dict:
    """会社別 給与レンジ浮動棒グラフ用データ（Chart.js floating bar）"""
    bucket: dict = defaultdict(list)
    for r in rows:
        mn = to_monthly(r, "salary_min")
        mx = to_monthly(r, "salary_max")
        if mn and mx:
            bucket[r["company"]].append((mn, mx))

    labels, data, colors = [], [], []
    for i, co in enumerate(COMPANIES):
        vals = bucket.get(co, [])
        if not vals:
            continue
        avg_min = round(statistics.mean(v[0] for v in vals), 1)
        avg_max = round(statistics.mean(v[1] for v in vals), 1)
        labels.append(co)
        data.append([avg_min, avg_max])
        colors.append(PALETTE[i % len(PALETTE)])

    return {
        "labels": labels,
        "datasets": [{
            "label": "給与レンジ（万円/月）",
            "data": data,
            "backgroundColor": colors,
            "borderColor": colors,
            "borderWidth": 2,
            "borderSkipped": False,
        }]
    }


def build_qual_chart_data(rows: list) -> dict:
    """資格別×会社別 平均月給グラフ"""
    bucket: dict = defaultdict(list)
    for r in rows:
        v = to_monthly(r)
        if v and r["qualification"] in QUALIFICATIONS:
            bucket[(r["company"], r["qualification"])].append(v)

    datasets = []
    for i, qual in enumerate(QUALIFICATIONS):
        data = []
        for co in COMPANIES:
            vals = bucket.get((co, qual), [])
            data.append(round(statistics.mean(vals), 1) if vals else None)
        datasets.append({
            "label": qual,
            "data": data,
            "backgroundColor": PALETTE[i % len(PALETTE)] + "CC",
            "borderColor": PALETTE[i % len(PALETTE)],
            "borderWidth": 1,
            "spanGaps": True,
        })

    return {"labels": COMPANIES, "datasets": datasets}


def build_trend_chart_data(rows: list) -> dict:
    """月次推移グラフ：会社別 平均月給（万円）の時系列折れ線グラフ用データ"""
    # month → company → [salary values]
    bucket: dict = defaultdict(lambda: defaultdict(list))
    for r in rows:
        v = to_monthly(r)
        d = r.get("date", "")
        if v and d:
            month = d[:7]  # YYYY-MM
            bucket[month][r["company"]].append(v)

    months = sorted(bucket.keys())
    if not months:
        return {"labels": [], "datasets": []}

    # データのある会社だけ表示
    active_companies = [co for co in COMPANIES
                        if any(co in bucket[m] for m in months)]

    datasets = []
    for i, co in enumerate(active_companies):
        data = []
        for m in months:
            vals = bucket[m].get(co, [])
            data.append(round(statistics.mean(vals), 1) if vals else None)
        datasets.append({
            "label": co,
            "data": data,
            "borderColor": PALETTE[i % len(PALETTE)],
            "backgroundColor": PALETTE[i % len(PALETTE)] + "22",
            "borderWidth": 2,
            "pointRadius": 4,
            "pointHoverRadius": 6,
            "tension": 0.3,
            "fill": False,
            "spanGaps": True,
        })

    return {"labels": months, "datasets": datasets}


def build_qual_trend_chart_data(rows: list) -> dict:
    """月次推移グラフ：資格別 平均月給（万円）の時系列折れ線グラフ用データ"""
    bucket: dict = defaultdict(lambda: defaultdict(list))
    for r in rows:
        v = to_monthly(r)
        d = r.get("date", "")
        q = r.get("qualification", "")
        if v and d and q in QUALIFICATIONS:
            month = d[:7]
            bucket[month][q].append(v)

    months = sorted(bucket.keys())
    if not months:
        return {"labels": [], "datasets": []}

    datasets = []
    for i, qual in enumerate(QUALIFICATIONS):
        data = []
        for m in months:
            vals = bucket[m].get(qual, [])
            data.append(round(statistics.mean(vals), 1) if vals else None)
        datasets.append({
            "label": qual,
            "data": data,
            "borderColor": PALETTE[i % len(PALETTE)],
            "backgroundColor": PALETTE[i % len(PALETTE)] + "22",
            "borderWidth": 2,
            "pointRadius": 4,
            "pointHoverRadius": 6,
            "tension": 0.3,
            "fill": False,
            "spanGaps": True,
        })

    return {"labels": months, "datasets": datasets}


def build_area_chart_data(rows: list) -> dict:
    """エリア別×資格別 平均月給グラフ"""
    bucket: dict = defaultdict(list)
    for r in rows:
        v = to_monthly(r)
        if v and r["qualification"] in QUALIFICATIONS:
            bucket[(r["area"], r["qualification"])].append(v)

    datasets = []
    for i, qual in enumerate(QUALIFICATIONS):
        data = []
        for area in AREAS:
            vals = bucket.get((area, qual), [])
            data.append(round(statistics.mean(vals), 1) if vals else None)
        datasets.append({
            "label": qual,
            "data": data,
            "backgroundColor": PALETTE[i % len(PALETTE)] + "CC",
            "borderColor": PALETTE[i % len(PALETTE)],
            "borderWidth": 1,
            "spanGaps": True,
        })

    return {"labels": AREAS, "datasets": datasets}


# ── 比較表 ─────────────────────────────────────────────────────────────────

def build_comparison_table(rows: list) -> str:
    """会社別×資格別 給与比較テーブル HTML"""
    bucket: dict = defaultdict(list)
    for r in rows:
        mn = to_monthly(r, "salary_min")
        mx = to_monthly(r, "salary_max")
        if mn and r["qualification"]:
            bucket[(r["company"], r["qualification"])].append((mn, mx or mn))

    active_companies = [co for co in COMPANIES
                        if any((co, q) in bucket for q in QUALIFICATIONS)]

    header = "<tr><th>資格</th>" + "".join(f"<th>{co}</th>" for co in active_companies) + "</tr>"

    body = ""
    for qual in QUALIFICATIONS:
        row_html = f"<tr><td class='qual-cell'>{qual}</td>"
        for co in active_companies:
            vals = bucket.get((co, qual), [])
            if vals:
                avg_mn = statistics.mean(v[0] for v in vals)
                avg_mx = statistics.mean(v[1] for v in vals)
                n = len(vals)
                cell = (f"<td class='salary-ok'>"
                        f"<span class='range'>{fmt_man(avg_mn)}〜{fmt_man(avg_mx)}万</span>"
                        f"<span class='cnt'>n={n}</span></td>")
            else:
                cell = "<td class='no-data'>—</td>"
            row_html += cell
        row_html += "</tr>"
        body += row_html

    return f"<table class='cmp-tbl'><thead>{header}</thead><tbody>{body}</tbody></table>"


# ── 求人一覧行 ─────────────────────────────────────────────────────────────

def build_table_rows(rows: list) -> str:
    html = ""
    for r in sorted(rows, key=lambda x: (x.get("company", ""), x.get("qualification", ""))):
        mn = to_monthly(r, "salary_min")
        mx = to_monthly(r, "salary_max")
        has_salary = "1" if mn else "0"
        salary_disp = r.get("salary_raw") or "—"
        range_disp = (f"{fmt_man(mn)}〜{fmt_man(mx)}万" if mn else "")
        source = "Indeed" if "indeed.com" in r.get("source_url", "") else "採用ページ"
        src_cls = "src-indeed" if source == "Indeed" else "src-career"
        area = r.get("area", "その他")
        url = r.get("source_url", "")
        title = (r.get("job_title") or "")[:50]
        qual = r.get("qualification") or "—"
        html += (
            f'<tr data-company="{r.get("company","")}" '
            f'data-qual="{r.get("qualification","")}" '
            f'data-area="{area}" data-source="{source}" '
            f'data-salary="{has_salary}">'
            f"<td>{r.get('company','')}</td>"
            f"<td>{qual}</td>"
            f"<td class='title-cell'>{title}</td>"
            f"<td><span class='badge badge-{area}'>{area}</span></td>"
            f"<td class='salary-raw'>{salary_disp}</td>"
            f"<td class='salary-range'>{range_disp}</td>"
            f"<td><span class='badge {src_cls}'>{source}</span></td>"
            f"<td><a href='{url}' target='_blank' rel='noopener'>🔗</a></td>"
            f"</tr>\n"
        )
    return html


# ── 月別タブコンテンツ ─────────────────────────────────────────────────────

def build_monthly_tabs(rows: list) -> tuple:
    """月別データのタブボタンとコンテンツHTMLを返す (buttons_html, panes_html)"""
    from collections import defaultdict

    # 月ごとにデータを振り分け
    by_month: dict = defaultdict(list)
    for r in rows:
        d = r.get("date", "")
        if d:
            by_month[d[:7]].append(r)

    months = sorted(by_month.keys(), reverse=True)  # 新しい月が先
    if not months:
        return "", "<p style='color:#999;font-size:13px'>データがありません</p>"

    btn_html = ""
    pane_html = ""

    for idx, month in enumerate(months):
        month_rows = by_month[month]
        is_active = idx == 0
        active_cls = " active" if is_active else ""
        yr, mo = month.split("-")
        label = f"{yr}年{int(mo)}月"
        cnt = len(month_rows)

        btn_html += (
            f'<button class="tab-btn{active_cls}" '
            f'onclick="switchMonthTab(\'{month}\')">'
            f'{label} <span style="font-size:10px;opacity:.75">({cnt}件)</span>'
            f'</button>\n'
        )

        # 月別サマリー
        with_sal = sum(1 for r in month_rows if to_monthly(r))
        companies_this = sorted({r.get("company","") for r in month_rows if r.get("company")})

        # 月別比較表（その月のデータだけで計算）
        bucket: dict = defaultdict(list)
        for r in month_rows:
            mn = to_monthly(r, "salary_min")
            mx = to_monthly(r, "salary_max")
            if mn and r.get("qualification"):
                bucket[(r["company"], r["qualification"])].append((mn, mx or mn))

        active_cos = [co for co in COMPANIES if any((co, q) in bucket for q in QUALIFICATIONS)]
        if active_cos:
            header = "<tr><th>資格</th>" + "".join(f"<th>{co}</th>" for co in active_cos) + "</tr>"
            body = ""
            for qual in QUALIFICATIONS:
                row_html = f"<tr><td class='qual-cell'>{qual}</td>"
                for co in active_cos:
                    vals = bucket.get((co, qual), [])
                    if vals:
                        import statistics as _s
                        avg_mn = _s.mean(v[0] for v in vals)
                        avg_mx = _s.mean(v[1] for v in vals)
                        n = len(vals)
                        row_html += (f"<td class='salary-ok'>"
                                     f"<span class='range'>{fmt_man(avg_mn)}〜{fmt_man(avg_mx)}万</span>"
                                     f"<span class='cnt'>n={n}</span></td>")
                    else:
                        row_html += "<td class='no-data'>—</td>"
                row_html += "</tr>"
                body += row_html
            cmp = f"<table class='cmp-tbl'><thead>{header}</thead><tbody>{body}</tbody></table>"
        else:
            cmp = "<p style='color:#999;font-size:13px'>給与データなし</p>"

        # 月別求人テーブル行
        rows_html = ""
        for r in sorted(month_rows, key=lambda x: (x.get("company",""), x.get("qualification",""))):
            mn = to_monthly(r, "salary_min")
            mx = to_monthly(r, "salary_max")
            salary_disp = r.get("salary_raw") or "—"
            range_disp = (f"{fmt_man(mn)}〜{fmt_man(mx)}万" if mn else "")
            source = "Indeed" if "indeed.com" in r.get("source_url","") else "採用ページ"
            src_cls = "src-indeed" if source == "Indeed" else "src-career"
            area = r.get("area","その他")
            url = r.get("source_url","")
            title = (r.get("job_title") or "")[:50]
            qual = r.get("qualification") or "—"
            rows_html += (
                f"<tr>"
                f"<td>{r.get('company','')}</td>"
                f"<td>{qual}</td>"
                f"<td class='title-cell'>{title}</td>"
                f"<td><span class='badge badge-{area}'>{area}</span></td>"
                f"<td class='salary-raw'>{salary_disp}</td>"
                f"<td class='salary-range'>{range_disp}</td>"
                f"<td><span class='badge {src_cls}'>{source}</span></td>"
                f"<td><a href='{url}' target='_blank' rel='noopener'>🔗</a></td>"
                f"</tr>\n"
            )

        pane_html += f"""
<div id="month-{month}" class="tab-pane{active_cls}">
  <div class="month-stats">
    <span class="mstat"><b>{cnt}</b>件収集</span>
    <span class="mstat"><b>{with_sal}</b>件給与あり</span>
    <span class="mstat">対象企業: <b>{', '.join(companies_this) or '—'}</b></span>
  </div>
  <h3 style="font-size:13px;font-weight:700;margin:14px 0 8px;color:#444">給与比較表</h3>
  <div class="tbl-wrap">{cmp}</div>
  <h3 style="font-size:13px;font-weight:700;margin:18px 0 8px;color:#444">求人一覧</h3>
  <div class="tbl-wrap">
    <table class="list-tbl">
      <thead><tr>
        <th>企業</th><th>資格</th><th>求人タイトル</th><th>エリア</th>
        <th>給与（原文）</th><th>月額換算</th><th>ソース</th><th>URL</th>
      </tr></thead>
      <tbody>{rows_html}</tbody>
    </table>
  </div>
</div>
"""

    return btn_html, pane_html


# ── HTML生成 ───────────────────────────────────────────────────────────────

def generate_html(rows: list) -> str:
    salary_rows      = [r for r in rows if to_monthly(r)]
    chart_range      = build_range_chart_data(rows)
    chart_qual       = build_qual_chart_data(rows)
    chart_area       = build_area_chart_data(rows)
    chart_trend_co   = build_trend_chart_data(rows)
    chart_trend_qual = build_qual_trend_chart_data(rows)
    cmp_table        = build_comparison_table(rows)
    table_rows       = build_table_rows(rows)
    monthly_btns, monthly_panes = build_monthly_tabs(rows)

    today           = date.today().strftime("%Y年%m月%d日")
    total           = len(rows)
    with_salary     = len(salary_rows)
    companies_found = len({r["company"] for r in rows})
    months_count    = len(set(r["date"][:7] for r in rows if r.get("date")))

    options_company = "\n".join(f'<option value="{c}">{c}</option>' for c in COMPANIES)
    options_qual    = "\n".join(f'<option value="{q}">{q}</option>' for q in QUALIFICATIONS)
    options_area    = "\n".join(f'<option value="{a}">{a}</option>' for a in AREAS)

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>福祉・保育業界 給与水準レポート</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js"></script>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Helvetica Neue',sans-serif;background:#f0f2f7;color:#1a1a2e;font-size:14px;line-height:1.5}}
a{{color:#FF6753;text-decoration:none}}
/* ── Header ── */
header{{background:linear-gradient(135deg,#FF6753 0%,#cc3520 100%);color:#fff;padding:24px 32px 20px}}
header h1{{font-size:22px;font-weight:700;letter-spacing:-.3px}}
header p{{font-size:12px;opacity:.8;margin-top:6px}}
/* ── タブ ── */
.tab-btns{{display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap}}
.tab-btn{{padding:6px 16px;border:1px solid #ffc9c3;border-radius:20px;background:#fff;
          font-size:12px;cursor:pointer;color:#555;transition:all .15s}}
.tab-btn.active{{background:#FF6753;color:#fff;border-color:#FF6753;font-weight:600}}
.tab-pane{{display:none}}.tab-pane.active{{display:block}}
/* ── Layout ── */
.container{{max-width:1320px;margin:0 auto;padding:20px 16px 40px}}
.grid2{{display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px}}
.grid3{{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-bottom:20px}}
@media(max-width:900px){{.grid2,.grid3{{grid-template-columns:1fr}}}}
/* ── Stats ── */
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin-bottom:20px}}
.stat{{background:#fff;border-radius:10px;padding:16px 20px;box-shadow:0 1px 4px rgba(0,0,0,.08);border-top:3px solid #FF6753}}
.stat .num{{font-size:32px;font-weight:800;color:#FF6753;line-height:1}}
.stat .label{{font-size:11px;color:#888;margin-top:5px}}
/* ── Card ── */
.card{{background:#fff;border-radius:10px;padding:22px 24px;box-shadow:0 1px 4px rgba(0,0,0,.08);margin-bottom:20px}}
.card h2{{font-size:14px;font-weight:700;margin-bottom:16px;color:#1a1a2e;
          border-left:3px solid #FF6753;padding-left:10px;display:flex;align-items:center;gap:6px}}
.card h2 .sub{{font-size:11px;color:#888;font-weight:400}}
/* ── 比較表 ── */
.cmp-tbl{{width:100%;border-collapse:collapse;font-size:13px}}
.cmp-tbl th{{background:#fff0ee;padding:8px 14px;text-align:center;
             border:1px solid #e0e7ff;white-space:nowrap;font-size:12px}}
.cmp-tbl td{{padding:8px 14px;border:1px solid #f0f0f0;vertical-align:middle}}
.qual-cell{{font-weight:600;white-space:nowrap;background:#fff8f7;font-size:12px}}
.salary-ok{{text-align:center}}
.salary-ok .range{{font-weight:700;color:#FF6753;display:block;font-size:13px}}
.salary-ok .cnt{{font-size:10px;color:#aaa;display:block;margin-top:1px}}
.no-data{{text-align:center;color:#ccc;font-size:18px}}
/* ── フィルターバー ── */
.filter-bar{{display:flex;gap:8px;flex-wrap:wrap;align-items:center;
             background:#fff8f7;padding:12px 14px;border-radius:8px;margin-bottom:14px}}
.filter-bar select{{padding:6px 10px;border:1px solid #ffc9c3;border-radius:6px;
                    font-size:12px;background:#fff;color:#333;cursor:pointer}}
.filter-bar label{{font-size:12px;display:flex;align-items:center;gap:5px;
                   cursor:pointer;color:#555}}
.filter-bar input[type=checkbox]{{cursor:pointer}}
.result-count{{margin-left:auto;font-size:12px;color:#888}}
/* ── テーブル ── */
.tbl-wrap{{overflow-x:auto}}
table.list-tbl{{width:100%;border-collapse:collapse;font-size:12px}}
.list-tbl th{{background:#fff0ee;text-align:left;padding:8px 10px;
              border-bottom:2px solid #ffd5d0;white-space:nowrap;font-size:12px;
              position:sticky;top:0;z-index:1}}
.list-tbl td{{padding:7px 10px;border-bottom:1px solid #f3f3f3;vertical-align:middle}}
.list-tbl tr:hover td{{background:#fff8f7}}
.title-cell{{max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}}
.salary-raw{{color:#555;max-width:180px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}}
.salary-range{{font-weight:700;color:#FF6753;white-space:nowrap}}
/* ── バッジ ── */
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;white-space:nowrap}}
.badge-首都圏{{background:#fff0ee;color:#FF6753}}
.badge-関西  {{background:#fce8e6;color:#c5221f}}
.badge-東海  {{background:#fef7e0;color:#b06000}}
.badge-その他{{background:#e6f4ea;color:#137333}}
.src-indeed{{background:#fff3cd;color:#856404}}
.src-career{{background:#e2f0fb;color:#0c5460}}
/* ── ソート矢印 ── */
.list-tbl th.sortable{{cursor:pointer;user-select:none}}
.list-tbl th.sortable:hover{{background:#ffd5d0}}
.sort-asc::after{{content:" ↑"}}
.sort-desc::after{{content:" ↓"}}
/* ── 月別サマリー ── */
.month-stats{{display:flex;gap:16px;flex-wrap:wrap;padding:10px 14px;
              background:#fff8f7;border-radius:8px;margin-bottom:12px;font-size:12px;color:#555}}
.mstat b{{color:#FF6753}}
/* ── フッター ── */
footer{{text-align:center;font-size:11px;color:#bbb;padding:20px}}
</style>
</head>
<body>
<header>
  <h1>📊 福祉・保育業界 給与水準レポート</h1>
  <p>最終更新: {today}　｜　対象7社・5資格　｜　毎月1日 9:00 JST 自動更新</p>
</header>

<div class="container">

  <!-- ── サマリーカード ── -->
  <div class="stats">
    <div class="stat"><div class="num">{total}</div><div class="label">累計収集件数</div></div>
    <div class="stat"><div class="num">{with_salary}</div><div class="label">給与記載あり</div></div>
    <div class="stat"><div class="num">{companies_found}</div><div class="label">対象企業数</div></div>
    <div class="stat"><div class="num">{len(QUALIFICATIONS)}</div><div class="label">対象資格数</div></div>
    <div class="stat"><div class="num">{months_count}</div><div class="label">累計調査月数</div></div>
  </div>

  <!-- ── 月次推移 ── -->
  <div class="card">
    <h2>📈 月次給与推移 <span class="sub">（調査月ごとの平均月給 万円/月）</span></h2>
    <div class="tab-btns">
      <button class="tab-btn active" onclick="switchTab('trend','company')">企業別</button>
      <button class="tab-btn"        onclick="switchTab('trend','qual')">資格別</button>
    </div>
    <div id="trend-company" class="tab-pane active">
      <canvas id="trendCompanyChart" height="100"></canvas>
    </div>
    <div id="trend-qual" class="tab-pane">
      <canvas id="trendQualChart" height="100"></canvas>
    </div>
  </div>

  <!-- ── グラフ行 ── -->
  <div class="grid2">
    <div class="card">
      <h2>🏢 企業別 給与レンジ <span class="sub">（平均最低〜最高 万円/月）</span></h2>
      <canvas id="rangeChart" height="200"></canvas>
    </div>
    <div class="card">
      <h2>📍 エリア別×資格別 平均月給 <span class="sub">（万円/月）</span></h2>
      <canvas id="areaChart" height="200"></canvas>
    </div>
  </div>

  <div class="card">
    <h2>📋 資格別×企業別 平均月給 <span class="sub">（万円/月）</span></h2>
    <canvas id="qualChart" height="100"></canvas>
  </div>

  <!-- ── 比較表 ── -->
  <div class="card">
    <h2>📊 会社別・資格別 給与比較表 <span class="sub">（平均 最低〜最高 万円/月）</span></h2>
    <div class="tbl-wrap">{cmp_table}</div>
  </div>

  <!-- ── 月別データ ── -->
  <div class="card">
    <h2>🗓️ 月別データ <span class="sub">（調査月ごとの収集データ）</span></h2>
    <div class="tab-btns" id="monthTabBtns">
{monthly_btns}
    </div>
{monthly_panes}
  </div>

  <!-- ── 求人一覧 ── -->
  <div class="card">
    <h2>📋 求人一覧（全期間）</h2>
    <div class="filter-bar">
      <select id="fcCompany" onchange="applyFilter()">
        <option value="">企業：すべて</option>
        {options_company}
      </select>
      <select id="fcQual" onchange="applyFilter()">
        <option value="">資格：すべて</option>
        {options_qual}
      </select>
      <select id="fcArea" onchange="applyFilter()">
        <option value="">エリア：すべて</option>
        {options_area}
      </select>
      <select id="fcSource" onchange="applyFilter()">
        <option value="">ソース：すべて</option>
        <option value="Indeed">Indeed</option>
        <option value="採用ページ">採用ページ</option>
      </select>
      <label>
        <input type="checkbox" id="fcSalary" onchange="applyFilter()" checked>
        給与あり のみ
      </label>
      <span class="result-count" id="resultCount"></span>
    </div>
    <div class="tbl-wrap">
      <table class="list-tbl">
        <thead>
          <tr>
            <th class="sortable" onclick="sortTable(0)">企業</th>
            <th class="sortable" onclick="sortTable(1)">資格</th>
            <th>求人タイトル</th>
            <th class="sortable" onclick="sortTable(3)">エリア</th>
            <th>給与（原文）</th>
            <th class="sortable" onclick="sortTable(5)">月額換算</th>
            <th>ソース</th>
            <th>URL</th>
          </tr>
        </thead>
        <tbody id="tblBody">
{table_rows}
        </tbody>
      </table>
    </div>
  </div>

</div>
<footer>データソース: Indeed Japan・各社採用ページ　｜　自動収集・給与調査目的　｜　<a href="https://github.com/ryuzohirano0824-design/salary-research">GitHub</a></footer>

<script>
/* ── 共通オプション（折れ線）── */
const lineOpts = {{
  responsive: true,
  interaction: {{ mode: 'index', intersect: false }},
  plugins: {{ legend: {{ position: 'top', labels: {{ font: {{ size: 10 }}, boxWidth: 12 }} }} }},
  scales: {{
    y: {{ title: {{ display: true, text: '万円/月' }}, beginAtZero: false }},
    x: {{ ticks: {{ font: {{ size: 11 }} }} }}
  }}
}};

/* ── Chart: 月次推移 企業別 ── */
new Chart(document.getElementById('trendCompanyChart'), {{
  type: 'line',
  data: {json.dumps(chart_trend_co, ensure_ascii=False)},
  options: lineOpts
}});

/* ── Chart: 月次推移 資格別 ── */
new Chart(document.getElementById('trendQualChart'), {{
  type: 'line',
  data: {json.dumps(chart_trend_qual, ensure_ascii=False)},
  options: lineOpts
}});

/* ── タブ切り替え（トレンドグラフ）── */
function switchTab(group, name) {{
  document.querySelectorAll(`[id^="${{group}}-"]`).forEach(el => el.classList.remove('active'));
  event.target.closest('.tab-btns').querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById(`${{group}}-${{name}}`).classList.add('active');
  event.target.classList.add('active');
}}

/* ── 月別タブ切り替え ── */
function switchMonthTab(month) {{
  document.querySelectorAll('[id^="month-"]').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('#monthTabBtns .tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('month-' + month).classList.add('active');
  event.target.classList.add('active');
}}

/* ── Chart: 企業別給与レンジ（浮動棒）── */
new Chart(document.getElementById('rangeChart'), {{
  type: 'bar',
  data: {json.dumps(chart_range, ensure_ascii=False)},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ display: false }},
      tooltip: {{
        callbacks: {{
          label: ctx => {{
            const d = ctx.raw;
            return Array.isArray(d) ? `${{d[0]}}〜${{d[1]}}万円/月` : d + '万円/月';
          }}
        }}
      }}
    }},
    scales: {{
      y: {{ title: {{ display: true, text: '万円/月' }}, min: 0 }},
      x: {{ ticks: {{ font: {{ size: 11 }} }} }}
    }}
  }}
}});

/* ── Chart: エリア別 ── */
new Chart(document.getElementById('areaChart'), {{
  type: 'bar',
  data: {json.dumps(chart_area, ensure_ascii=False)},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ position: 'top', labels: {{ font: {{ size: 10 }}, boxWidth: 12 }} }} }},
    scales: {{
      y: {{ title: {{ display: true, text: '万円/月' }}, beginAtZero: true }},
      x: {{ ticks: {{ font: {{ size: 11 }} }} }}
    }}
  }}
}});

/* ── Chart: 資格別×企業別 ── */
new Chart(document.getElementById('qualChart'), {{
  type: 'bar',
  data: {json.dumps(chart_qual, ensure_ascii=False)},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ position: 'top', labels: {{ font: {{ size: 10 }}, boxWidth: 12 }} }} }},
    scales: {{
      y: {{ title: {{ display: true, text: '万円/月' }}, beginAtZero: true }},
      x: {{ ticks: {{ font: {{ size: 10 }} }} }}
    }}
  }}
}});

/* ── フィルター ── */
function applyFilter() {{
  const co  = document.getElementById('fcCompany').value;
  const qu  = document.getElementById('fcQual').value;
  const ar  = document.getElementById('fcArea').value;
  const src = document.getElementById('fcSource').value;
  const sal = document.getElementById('fcSalary').checked;
  let visible = 0;
  document.querySelectorAll('#tblBody tr').forEach(tr => {{
    const match =
      (!co  || tr.dataset.company === co) &&
      (!qu  || tr.dataset.qual    === qu) &&
      (!ar  || tr.dataset.area    === ar) &&
      (!src || tr.dataset.source  === src) &&
      (!sal || tr.dataset.salary  === '1');
    tr.style.display = match ? '' : 'none';
    if (match) visible++;
  }});
  document.getElementById('resultCount').textContent = visible + ' 件表示中';
}}

/* ── ソート ── */
let sortState = {{}};
function sortTable(col) {{
  const tbody = document.getElementById('tblBody');
  const rows  = Array.from(tbody.querySelectorAll('tr'));
  const asc   = !(sortState[col] === 'asc');
  sortState    = {{}};
  sortState[col] = asc ? 'asc' : 'desc';

  rows.sort((a, b) => {{
    const av = a.cells[col]?.textContent.trim() || '';
    const bv = b.cells[col]?.textContent.trim() || '';
    const an = parseFloat(av), bn = parseFloat(bv);
    if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
    return asc ? av.localeCompare(bv, 'ja') : bv.localeCompare(av, 'ja');
  }});

  document.querySelectorAll('.list-tbl th').forEach((th, i) => {{
    th.classList.remove('sort-asc', 'sort-desc');
    if (i === col) th.classList.add(asc ? 'sort-asc' : 'sort-desc');
  }});
  rows.forEach(r => tbody.appendChild(r));
  applyFilter();
}}

/* 初期表示：給与ありのみ */
applyFilter();
</script>
</body>
</html>"""


def main() -> None:
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    rows = load_data()
    html = generate_html(rows)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(html)
    salary_count = sum(1 for r in rows if to_monthly(r))
    print(f"レポート生成完了: {OUTPUT_FILE}  ({len(rows)} 件 / 給与あり {salary_count} 件)")


if __name__ == "__main__":
    main()
