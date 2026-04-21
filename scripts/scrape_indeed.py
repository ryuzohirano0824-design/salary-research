#!/usr/bin/env python3
"""Indeed求人情報スクレイピングスクリプト

企業名＋資格名でIndeedを検索し、求人タイトル・給与・勤務地・URLを
salary_master.csv に追記する。同一URLは重複追記しない。
"""

import csv
import logging
import random
import re
import time
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
DATA_FILE = BASE_DIR / "data" / "salary_master.csv"

COMPANIES = [
    "リタリコ", "コペル", "LUMO", "TAKUMI",
    "ネイスプラス", "リーフプラス", "ビーマスポーツ",
]
QUALIFICATIONS = [
    "児童発達支援管理責任者", "児童指導員", "保育士",
    "作業療法士", "理学療法士",
]

CSV_HEADERS = [
    "date", "company", "qualification", "job_title",
    "location", "area", "salary_min", "salary_max",
    "salary_type", "salary_raw", "source_url",
]

KANTO  = ["東京", "神奈川", "埼玉", "千葉", "茨城", "栃木", "群馬"]
KANSAI = ["大阪", "京都", "兵庫", "奈良", "滋賀", "和歌山"]
TOKAI  = ["愛知", "静岡", "岐阜", "三重"]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ─── ユーティリティ ───────────────────────────────────────────────────────────


def classify_area(location: str) -> str:
    for pref in KANTO:
        if pref in location:
            return "首都圏"
    for pref in KANSAI:
        if pref in location:
            return "関西"
    for pref in TOKAI:
        if pref in location:
            return "東海"
    return "その他"


def parse_salary(text: str) -> dict:
    """日本語給与テキストをパースし min/max/type/raw を返す。"""
    if not text:
        return {"min": "", "max": "", "type": "", "raw": ""}

    raw = text.strip()
    clean = raw.replace(",", "").replace("，", "").replace("\u3000", " ").replace(" ", "")
    result = {"min": "", "max": "", "type": "", "raw": raw}

    def to_yen(val_str: str) -> str:
        return str(int(float(val_str) * 10_000))

    if "時給" in clean:
        result["type"] = "hourly"
        nums = re.findall(r"(\d+)", clean)
        if nums:
            result["min"] = nums[0]
            result["max"] = nums[1] if len(nums) > 1 else nums[0]
    elif "日給" in clean:
        result["type"] = "daily"
        nums = re.findall(r"(\d+)", clean)
        if nums:
            result["min"] = nums[0]
            result["max"] = nums[1] if len(nums) > 1 else nums[0]
    elif any(k in clean for k in ("月給", "月収")):
        result["type"] = "monthly"
        mans = re.findall(r"(\d+(?:\.\d+)?)万", clean)
        if mans:
            result["min"] = to_yen(mans[0])
            result["max"] = to_yen(mans[1]) if len(mans) > 1 else to_yen(mans[0])
        else:
            nums = re.findall(r"(\d{4,})", clean)
            if nums:
                result["min"] = nums[0]
                result["max"] = nums[1] if len(nums) > 1 else nums[0]
    elif any(k in clean for k in ("年収", "年給")):
        result["type"] = "annual"
        mans = re.findall(r"(\d+(?:\.\d+)?)万", clean)
        if mans:
            result["min"] = to_yen(mans[0])
            result["max"] = to_yen(mans[1]) if len(mans) > 1 else to_yen(mans[0])
    else:
        result["type"] = "unknown"
        mans = re.findall(r"(\d+(?:\.\d+)?)万", clean)
        if mans:
            result["min"] = to_yen(mans[0])
            result["max"] = to_yen(mans[1]) if len(mans) > 1 else to_yen(mans[0])

    return result


def load_existing_urls() -> set:
    if not DATA_FILE.exists():
        return set()
    with open(DATA_FILE, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return {row["source_url"] for row in reader if row.get("source_url")}


# ─── スクレイピング ───────────────────────────────────────────────────────────


def _extract_jobs(soup: BeautifulSoup, company: str, qualification: str,
                  existing_urls: set) -> list:
    """BeautifulSoupオブジェクトから求人情報を抽出する。"""
    today = date.today().isoformat()
    results = []

    # Indeed のカード要素（構造変更に備え複数セレクタ）
    cards = soup.select(
        "div.job_seen_beacon, "
        "div[class*='resultContent'], "
        "li.css-5lfssm"
    )

    for card in cards:
        # ── タイトル・URL ──
        link_el = card.select_one("h2.jobTitle a, a.jcs-JobTitle, h2 a[data-jk]")
        if not link_el:
            continue

        href = link_el.get("href", "")
        job_url = (
            "https://jp.indeed.com" + href if href.startswith("/") else href
        )
        if not job_url or job_url in existing_urls:
            continue

        title = (
            link_el.get("title")
            or link_el.select_one("span[title]", ).get("title", "") if link_el.select_one("span[title]") else ""
            or link_el.get_text(strip=True)
        )

        # ── 企業名 ──
        co_el = card.select_one(
            "span.companyName, [data-testid='company-name'], span[class*='companyName']"
        )
        company_name = co_el.get_text(strip=True) if co_el else company

        # ── 勤務地 ──
        loc_el = card.select_one(
            "div.companyLocation, [data-testid='text-location'], div[class*='companyLocation']"
        )
        location = loc_el.get_text(strip=True) if loc_el else ""

        # ── 給与 ──
        sal_el = card.select_one(
            "div.salary-snippet-container span, "
            "div.metadata.salary-snippet-container span, "
            "[data-testid='attribute_snippet_testid'], "
            "div[class*='salary'] span"
        )
        salary_text = sal_el.get_text(strip=True) if sal_el else ""
        # 給与でなく他情報が入ることがあるのでフィルタ
        if salary_text and not re.search(r"[円万時日月年給収]", salary_text):
            salary_text = ""
        salary = parse_salary(salary_text)

        area = classify_area(location)

        results.append({
            "date": today,
            "company": company,
            "qualification": qualification,
            "job_title": title,
            "location": location,
            "area": area,
            "salary_min": salary["min"],
            "salary_max": salary["max"],
            "salary_type": salary["type"],
            "salary_raw": salary["raw"],
            "source_url": job_url,
        })
        existing_urls.add(job_url)

    return results


def scrape_indeed(company: str, qualification: str, existing_urls: set) -> list:
    """IndeedでcompanyとqualificationのAND検索を行い求人リストを返す。"""
    query = f"{company} {qualification}"
    all_results = []

    for page in range(3):  # 最大3ページ（約30件）
        start = page * 10
        url = (
            "https://jp.indeed.com/jobs"
            f"?q={requests.utils.quote(query)}&start={start}"
        )
        logger.debug(f"  GET {url}")

        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 403:
                logger.warning("  アクセス制限 (403) — スキップ")
                break
            if resp.status_code != 200:
                logger.warning(f"  HTTP {resp.status_code}")
                break

            soup = BeautifulSoup(resp.text, "lxml")
            jobs = _extract_jobs(soup, company, qualification, existing_urls)

            if not jobs and page > 0:
                break  # 追加ページに結果なし

            all_results.extend(jobs)

        except requests.RequestException as e:
            logger.error(f"  リクエストエラー: {e}")
            break

        wait = random.uniform(4.0, 8.0)
        logger.debug(f"  待機 {wait:.1f}s")
        time.sleep(wait)

    return all_results


# ─── メイン ──────────────────────────────────────────────────────────────────


def main() -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    # CSVが存在しない場合はヘッダー行を作成
    if not DATA_FILE.exists():
        with open(DATA_FILE, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADERS).writeheader()
        logger.info("salary_master.csv を新規作成しました")

    existing_urls = load_existing_urls()
    logger.info(f"既存URL数: {len(existing_urls)}")

    total_new = 0

    for company in COMPANIES:
        for qual in QUALIFICATIONS:
            logger.info(f"検索: {company} × {qual}")
            results = scrape_indeed(company, qual, existing_urls)
            logger.info(f"  → 新規 {len(results)} 件")

            if results:
                with open(DATA_FILE, "a", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
                    writer.writerows(results)
                total_new += len(results)

            time.sleep(random.uniform(2.0, 4.0))

    logger.info(f"完了 — 今回の新規追記: {total_new} 件")


if __name__ == "__main__":
    main()
