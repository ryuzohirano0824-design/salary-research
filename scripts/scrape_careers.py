#!/usr/bin/env python3
"""各社採用ページ直接スクレイピングスクリプト

各社の公式採用ページから求人情報を取得し salary_master.csv に追記する。
同一URLは重複追記しない。
"""

import csv
import logging
import re
import time
from datetime import date
from pathlib import Path

from typing import Optional

import requests
from bs4 import BeautifulSoup

from scrape_indeed import (
    CSV_HEADERS,
    DATA_FILE,
    build_driver,
    classify_area,
    load_existing_urls,
    parse_salary,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

HDR = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ja-JP,ja;q=0.9,en;q=0.8",
}


def _get(url: str, timeout: int = 15) -> Optional[BeautifulSoup]:
    try:
        r = requests.get(url, headers=HDR, timeout=timeout, allow_redirects=True)
        r.encoding = r.apparent_encoding
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        logger.warning(f"  GET失敗 {url}: {e}")
        return None


def _row(company: str, title: str, location: str, salary_text: str, url: str) -> dict:
    s = parse_salary(salary_text)
    return {
        "date":         date.today().isoformat(),
        "company":      company,
        "qualification": "",
        "job_title":    title,
        "location":     location,
        "area":         classify_area(location),
        "salary_min":   s["min"],
        "salary_max":   s["max"],
        "salary_type":  s["type"],
        "salary_raw":   s["raw"],
        "source_url":   url,
    }


# ─── LUMO（Gotoschool） ────────────────────────────────────────────────────────

def scrape_lumo(existing_urls: set) -> list:
    base = "https://gotoschool.co.jp"
    soup = _get(f"{base}/recruit/")
    if not soup:
        return []

    job_paths = list(set([
        a["href"] for a in soup.find_all("a", href=True)
        if "/recruit/jobs/" in a.get("href", "")
    ]))

    results = []
    for path in job_paths:
        url = base + path if path.startswith("/") else path
        if url in existing_urls:
            continue

        detail = _get(url)
        if not detail:
            continue

        texts = [l.strip() for l in detail.get_text("\n").split("\n") if l.strip()]

        h1 = detail.find("h1")
        raw_title = h1.get_text(strip=True) if h1 else path
        # "職種名 | ページタイプ | 会社名" → 職種名のみ抽出
        title = raw_title.split("|")[0].strip() if "|" in raw_title else raw_title

        # 給与：「236,500～256,500円」「給与\n236,500～256,500円」形式
        salary_text = ""
        location = ""
        for i, t in enumerate(texts):
            if t in ("給与", "月給", "年収"):
                salary_text = texts[i + 1] if i + 1 < len(texts) else ""
            if "勤務地" in t and i + 1 < len(texts):
                location = texts[i + 1]

        results.append(_row("LUMO", title, location, salary_text, url))
        existing_urls.add(url)
        time.sleep(1.5)

    logger.info(f"  LUMO: {len(results)} 件")
    return results


# ─── TAKUMI（イニシアス） ─────────────────────────────────────────────────────

TAKUMI_PAGES = ["/p-01/", "/p-02/", "/p-03/", "/lp-4/", "/lp-5/"]

def scrape_takumi(existing_urls: set) -> list:
    base = "https://initias-recruit.jp"
    results = []

    for path in TAKUMI_PAGES:
        url = base + path
        if url in existing_urls:
            continue

        soup = _get(url)
        if not soup:
            continue

        texts = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]

        h1 = soup.find("h1")
        raw_title = h1.get_text(strip=True) if h1 else path
        title = raw_title.split("|")[0].strip() if "|" in raw_title else raw_title

        salary_text = ""
        location = ""
        for i, t in enumerate(texts):
            if t == "給与" and i + 1 < len(texts):
                salary_text = texts[i + 1]
            if "勤務地" in t and i + 1 < len(texts) and not location:
                location = texts[i + 1]

        results.append(_row("TAKUMI", title, location, salary_text, url))
        existing_urls.add(url)
        time.sleep(1.0)

    logger.info(f"  TAKUMI: {len(results)} 件")
    return results


# ─── リタリコ（Selenium） ─────────────────────────────────────────────────────

def scrape_litalico(driver, existing_urls: set) -> list:
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By

    base = "https://recruit.litalico.jp"
    results = []

    try:
        driver.get(base + "/")
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, "lxml")

        # 求人一覧リンクを収集
        job_links = list(set([
            a["href"] for a in soup.find_all("a", href=True)
            if re.search(r"/jobs?/|/career/|/position", a.get("href", ""))
            and "litalico" in a.get("href", "")
        ]))[:20]

        if not job_links:
            # TOPに求人カードがある場合
            cards = soup.select("article, li[class*='job'], div[class*='job']")
            for card in cards[:15]:
                a_el = card.find("a", href=True)
                if a_el:
                    job_links.append(a_el["href"])

        for href in job_links:
            url = href if href.startswith("http") else base + href
            if url in existing_urls:
                continue

            driver.get(url)
            time.sleep(2)
            detail_soup = BeautifulSoup(driver.page_source, "lxml")
            texts = [l.strip() for l in detail_soup.get_text("\n").split("\n") if l.strip()]

            h1 = detail_soup.find("h1")
            title = h1.get_text(strip=True) if h1 else url

            salary_text = ""
            location = ""
            for i, t in enumerate(texts):
                if re.search(r"^(給与|月給|年収|時給)$", t) and i + 1 < len(texts):
                    salary_text = texts[i + 1]
                if re.search(r"^(勤務地|勤務場所)$", t) and i + 1 < len(texts) and not location:
                    location = texts[i + 1]

            results.append(_row("リタリコ", title, location, salary_text, url))
            existing_urls.add(url)
            time.sleep(2)

    except Exception as e:
        logger.warning(f"  リタリコ取得エラー: {e}")

    logger.info(f"  リタリコ: {len(results)} 件")
    return results


# ─── ビーマスポーツ（Selenium） ───────────────────────────────────────────────

def scrape_bima(driver, existing_urls: set) -> list:
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.common.by import By

    base = "https://www.biimasports-recruit.com"
    results = []

    try:
        driver.get(base + "/")
        time.sleep(3)
        soup = BeautifulSoup(driver.page_source, "lxml")

        job_links = list(set([
            a["href"] for a in soup.find_all("a", href=True)
            if re.search(r"/jobs?/|/recruit/|/career/|/position", a.get("href", ""))
        ]))[:20]

        for href in job_links:
            url = href if href.startswith("http") else base + href
            if url in existing_urls:
                continue

            driver.get(url)
            time.sleep(2)
            detail_soup = BeautifulSoup(driver.page_source, "lxml")
            texts = [l.strip() for l in detail_soup.get_text("\n").split("\n") if l.strip()]

            h1 = detail_soup.find("h1")
            title = h1.get_text(strip=True) if h1 else url

            salary_text = ""
            location = ""
            for i, t in enumerate(texts):
                if re.search(r"^(給与|月給|年収|時給)$", t) and i + 1 < len(texts):
                    salary_text = texts[i + 1]
                if re.search(r"^(勤務地|勤務場所)$", t) and i + 1 < len(texts) and not location:
                    location = texts[i + 1]

            results.append(_row("ビーマスポーツ", title, location, salary_text, url))
            existing_urls.add(url)
            time.sleep(2)

    except Exception as e:
        logger.warning(f"  ビーマスポーツ取得エラー: {e}")

    logger.info(f"  ビーマスポーツ: {len(results)} 件")
    return results


# ─── コペル ───────────────────────────────────────────────────────────────────

def scrape_copel(existing_urls: set) -> list:
    """コペルの採用ページ（クラ・ゼミ saiyo-job.jp システム）をスクレイピング。"""
    base_url = "https://copelplus.copel.co.jp/saiyou/"
    soup = _get(base_url)
    if not soup:
        return []

    # 都道府県リンクを取得
    pref_links = list(set([
        a["href"] for a in soup.find_all("a", href=True)
        if "saiyo-job.jp" in a.get("href", "")
    ]))

    results = []
    for pref_url in pref_links[:10]:  # 主要10都道府県
        pref_soup = _get(pref_url)
        if not pref_soup:
            continue

        job_links = [
            a["href"] for a in pref_soup.find_all("a", href=True)
            if "saiyo-job.jp" in a.get("href", "") and "/pc_job/detail/" in a.get("href", "")
        ]

        for job_url in job_links[:5]:
            if job_url in existing_urls:
                continue

            detail = _get(job_url)
            if not detail:
                continue

            texts = [l.strip() for l in detail.get_text("\n").split("\n") if l.strip()]
            h1 = detail.find("h1") or detail.find("h2")
            title = h1.get_text(strip=True) if h1 else ""

            salary_text = ""
            location = ""
            for i, t in enumerate(texts):
                if re.search(r"^(給与|月給|時給|年収)$", t) and i + 1 < len(texts):
                    salary_text = texts[i + 1]
                if re.search(r"^(勤務地|勤務場所|アクセス)$", t) and i + 1 < len(texts) and not location:
                    location = texts[i + 1]

            results.append(_row("コペル", title, location, salary_text, job_url))
            existing_urls.add(job_url)
            time.sleep(1.5)

    logger.info(f"  コペル: {len(results)} 件")
    return results


# ─── ネイスプラス ─────────────────────────────────────────────────────────────

def scrape_neis(existing_urls: set) -> list:
    """ネイスプラスの採用ページをスクレイピング。"""
    base = "https://ne-is.com"
    soup = _get(f"{base}/recruit/")
    if not soup:
        return []

    # 仕事紹介などのリンクを探す
    job_links = list(set([
        a["href"] for a in soup.find_all("a", href=True)
        if re.search(r"/recruit/(?!$|#|people)", a.get("href", ""))
    ]))

    results = []
    visited = {f"{base}/recruit/"}

    for href in job_links[:10]:
        url = href if href.startswith("http") else base + href
        if url in existing_urls or url in visited:
            continue
        visited.add(url)

        detail = _get(url)
        if not detail:
            continue

        texts = [l.strip() for l in detail.get_text("\n").split("\n") if l.strip()]
        h1 = detail.find("h1")
        title = h1.get_text(strip=True) if h1 else url

        salary_text = ""
        location = ""
        for i, t in enumerate(texts):
            if re.search(r"^(給与|月給|時給|年収)$", t) and i + 1 < len(texts):
                salary_text = texts[i + 1]
            if re.search(r"^(勤務地|勤務場所)$", t) and i + 1 < len(texts) and not location:
                location = texts[i + 1]

        results.append(_row("ネイスプラス", title, location, salary_text, url))
        existing_urls.add(url)
        time.sleep(1.0)

    logger.info(f"  ネイスプラス: {len(results)} 件")
    return results


# ─── メイン ──────────────────────────────────────────────────────────────────

def main() -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not DATA_FILE.exists():
        with open(DATA_FILE, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADERS).writeheader()

    existing_urls = load_existing_urls()
    logger.info(f"既存URL数: {len(existing_urls)}")

    all_results = []

    # requests で取得できる社
    logger.info("LUMO スクレイピング開始")
    all_results.extend(scrape_lumo(existing_urls))

    logger.info("TAKUMI スクレイピング開始")
    all_results.extend(scrape_takumi(existing_urls))

    logger.info("コペル スクレイピング開始")
    all_results.extend(scrape_copel(existing_urls))

    logger.info("ネイスプラス スクレイピング開始")
    all_results.extend(scrape_neis(existing_urls))

    # Selenium が必要な社
    logger.info("Selenium ドライバー起動")
    driver = build_driver()
    try:
        logger.info("リタリコ スクレイピング開始")
        all_results.extend(scrape_litalico(driver, existing_urls))

        logger.info("ビーマスポーツ スクレイピング開始")
        all_results.extend(scrape_bima(driver, existing_urls))
    finally:
        driver.quit()

    if all_results:
        with open(DATA_FILE, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADERS).writerows(all_results)

    logger.info(f"完了 — 採用ページ新規追記: {len(all_results)} 件")


if __name__ == "__main__":
    main()
