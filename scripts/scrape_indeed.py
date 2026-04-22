#!/usr/bin/env python3
"""Indeed求人情報スクレイピングスクリプト（Selenium版）

企業名＋資格名でIndeedを検索し、求人タイトル・給与・勤務地・URLを
salary_master.csv に追記する。同一URLは重複追記しない。
"""

import csv
import logging
import os
import random
import re
import time
from datetime import date
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
DATA_FILE = BASE_DIR / "data" / "salary_master.csv"

# 各社の正規名 → 検索キーワード一覧（表記ゆれ対応）
COMPANIES = {
    "リタリコ":       ["リタリコ", "LITALICO"],
    "コペル":         ["コペル", "Copel"],
    "LUMO":           ["LUMO", "ルモ"],
    "TAKUMI":         ["TAKUMI", "たくみ"],
    "ネイスプラス":   ["ネイスプラス", "NEIS PLUS"],
    "リーフプラス":   ["リーフプラス", "Leaf+"],
    "ビーマスポーツ": ["ビーマスポーツ", "BIMA SPORTS"],
}
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
        else:
            # 「236,500～256,500円」のような万単位なし・プレフィックスなし形式
            nums = re.findall(r"(\d{4,})", clean)
            if nums:
                result["min"] = nums[0]
                result["max"] = nums[1] if len(nums) > 1 else nums[0]

    return result


def load_existing_urls() -> set:
    if not DATA_FILE.exists():
        return set()
    with open(DATA_FILE, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return {row["source_url"] for row in reader if row.get("source_url")}


# ─── Seleniumドライバー ────────────────────────────────────────────────────────


def build_driver() -> webdriver.Chrome:
    opts = Options()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    opts.add_argument("--window-size=1280,900")
    opts.add_argument(
        "user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    opts.add_argument("--lang=ja-JP")

    # CI: ワークフローが setup-chrome のアクション出力パスを環境変数で渡す
    # ローカル: 未設定のまま → Selenium Manager が自動解決
    chromedriver_path = os.environ.get("CHROMEDRIVER_PATH")
    chrome_path = os.environ.get("CHROME_PATH")
    if chrome_path:
        opts.binary_location = chrome_path
    service = Service(chromedriver_path) if chromedriver_path else Service()

    driver = webdriver.Chrome(service=service, options=opts)
    # webdriver フラグを隠す
    driver.execute_cdp_cmd(
        "Page.addScriptToEvaluateOnNewDocument",
        {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
    )
    return driver


# ─── スクレイピング ───────────────────────────────────────────────────────────


def _extract_jobs(html: str, company: str, qualification: str,
                  existing_urls: set) -> list:
    today = date.today().isoformat()
    results = []
    soup = BeautifulSoup(html, "lxml")

    cards = soup.select(
        "div.job_seen_beacon, "
        "div[class*='resultContent'], "
        "li[class*='css-']"
    )

    for card in cards:
        link_el = card.select_one("h2.jobTitle a, a.jcs-JobTitle, h2 a[data-jk]")
        if not link_el:
            continue

        href = link_el.get("href", "")
        job_url = "https://jp.indeed.com" + href if href.startswith("/") else href
        if not job_url or job_url in existing_urls:
            continue

        span_title = link_el.select_one("span[title]")
        title = (
            link_el.get("title")
            or (span_title.get("title", "") if span_title else "")
            or link_el.get_text(strip=True)
        )

        loc_el = card.select_one(
            "div.companyLocation, [data-testid='text-location'], div[class*='companyLocation']"
        )
        location = loc_el.get_text(strip=True) if loc_el else ""

        sal_el = card.select_one(
            "li.salary-snippet-container, "
            "div.salary-snippet-container span, "
            "[data-testid*='attribute_snippet_testid'], "
            "div[class*='salary'] span"
        )
        salary_text = sal_el.get_text(strip=True) if sal_el else ""
        if salary_text and not re.search(r"[円万時日月年給収]", salary_text):
            salary_text = ""
        salary = parse_salary(salary_text)

        results.append({
            "date": today,
            "company": company,
            "qualification": qualification,
            "job_title": title,
            "location": location,
            "area": classify_area(location),
            "salary_min": salary["min"],
            "salary_max": salary["max"],
            "salary_type": salary["type"],
            "salary_raw": salary["raw"],
            "source_url": job_url,
        })
        existing_urls.add(job_url)

    return results


def scrape_indeed(driver: webdriver.Chrome, company: str, qualification: str,
                  existing_urls: set, keyword: Optional[str] = None) -> list:
    # keyword が指定されていればそれで検索、なければ company 名をそのまま使う
    query = f"{keyword or company} {qualification}"
    all_results = []

    for page in range(3):
        start = page * 10
        url = f"https://jp.indeed.com/jobs?q={quote(query)}&start={start}"
        logger.debug(f"  GET {url}")

        try:
            driver.get(url)
        except Exception as e:
            logger.warning(f"  ページ読み込み失敗: {e}")
            break

        # 求人カードが出るまで最大15秒待機（タイムアウトしても抽出を試みる）
        try:
            WebDriverWait(driver, 15).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "div#mosaic-provider-jobcards, div.jobsearch-ResultsList"))
            )
        except Exception:
            pass  # タイムアウトしても続行

        time.sleep(random.uniform(2.0, 4.0))  # JS描画を待つ

        jobs = _extract_jobs(driver.page_source, company, qualification, existing_urls)
        logger.debug(f"  page{page+1}: {len(jobs)} 件")

        if not jobs and page > 0:
            break

        all_results.extend(jobs)

        time.sleep(random.uniform(3.0, 6.0))

    return all_results


# ─── メイン ──────────────────────────────────────────────────────────────────


def main() -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)

    if not DATA_FILE.exists():
        with open(DATA_FILE, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADERS).writeheader()
        logger.info("salary_master.csv を新規作成しました")

    existing_urls = load_existing_urls()
    logger.info(f"既存URL数: {len(existing_urls)}")

    driver = build_driver()
    total_new = 0

    try:
        for company, aliases in COMPANIES.items():
            for qual in QUALIFICATIONS:
                combo_results = []
                for alias in aliases:
                    logger.info(f"検索: {alias}（{company}）× {qual}")
                    results = scrape_indeed(driver, company, qual, existing_urls, keyword=alias)
                    logger.info(f"  → 新規 {len(results)} 件")
                    combo_results.extend(results)
                    time.sleep(random.uniform(2.0, 4.0))

                if combo_results:
                    with open(DATA_FILE, "a", newline="", encoding="utf-8") as f:
                        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
                        writer.writerows(combo_results)
                    total_new += len(combo_results)
    finally:
        driver.quit()

    logger.info(f"完了 — 今回の新規追記: {total_new} 件")


if __name__ == "__main__":
    main()
