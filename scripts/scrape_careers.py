#!/usr/bin/env python3
"""各社採用ページ直接スクレイピングスクリプト

各社の公式採用ページから求人情報を取得し salary_master.csv に追記する。
同一URLは重複追記しない。
"""

import csv
import logging
import re
import time
import warnings
from datetime import date
from pathlib import Path

from typing import Optional

import requests
import urllib3
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


def _get_insecure(url: str, timeout: int = 15) -> Optional[BeautifulSoup]:
    """SSL証明書検証をスキップしてGETする（証明書エラーのあるサイト用）。"""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", urllib3.exceptions.InsecureRequestWarning)
            r = requests.get(url, headers=HDR, timeout=timeout,
                             allow_redirects=True, verify=False)
        r.encoding = r.apparent_encoding
        return BeautifulSoup(r.text, "lxml")
    except Exception as e:
        logger.warning(f"  GET失敗（SSL無効） {url}: {e}")
        return None


# 資格キーワード → 正規資格名のマッピング
QUAL_PATTERNS = [
    ("児童発達支援管理責任者", ["児童発達支援管理責任者", "サービス管理責任者"]),
    ("児童指導員",             ["児童指導員", "指導員"]),
    ("保育士",                 ["保育士"]),
    ("作業療法士",             ["作業療法士", r"OT[・/）\s]", r"（OT）"]),
    ("理学療法士",             ["理学療法士", r"PT[・/）\s]", r"（PT）"]),
]


def detect_qualification(title: str) -> str:
    """求人タイトルから資格名を検出して返す。複数一致は最初のもの。"""
    for qual, patterns in QUAL_PATTERNS:
        for pat in patterns:
            if re.search(pat, title):
                return qual
    return ""


def detect_all_qualifications(title: str) -> list:
    """タイトルに含まれる全資格を返す（例: PT/OT → [理学療法士, 作業療法士]）。"""
    found = []
    for qual, patterns in QUAL_PATTERNS:
        for pat in patterns:
            if re.search(pat, title):
                found.append(qual)
                break
    return found or [""]


def _rows(company: str, title: str, location: str, salary_text: str, url: str) -> list:
    """資格を複数検出した場合は複数行に展開して返す。"""
    quals = detect_all_qualifications(title)
    return [_row(company, title, location, salary_text, url, q) for q in quals]


def _row(company: str, title: str, location: str, salary_text: str, url: str,
         qualification: str = "") -> dict:
    s = parse_salary(salary_text)
    return {
        "date":          date.today().isoformat(),
        "company":       company,
        "qualification": qualification or detect_qualification(title),
        "job_title":     title,
        "location":      location,
        "area":          classify_area(location),
        "salary_min":    s["min"],
        "salary_max":    s["max"],
        "salary_type":   s["type"],
        "salary_raw":    s["raw"],
        "source_url":    url,
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

        # LUMO: h1は空でtitleタグに「職種名 | 採用種別 | 会社名」が入る
        title_tag = detail.find("title")
        raw_title = title_tag.get_text(strip=True) if title_tag else path
        title = raw_title.split("|")[0].strip() if "|" in raw_title else raw_title

        # 給与：「236,500～256,500円」「給与\n236,500～256,500円」形式
        salary_text = ""
        location = ""
        for i, t in enumerate(texts):
            if t in ("給与", "月給", "年収"):
                salary_text = texts[i + 1] if i + 1 < len(texts) else ""
            if "勤務地" in t and i + 1 < len(texts):
                location = texts[i + 1]

        results.extend(_rows("LUMO", title, location, salary_text, url))
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

        results.extend(_rows("TAKUMI", title, location, salary_text, url))
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


# ─── ビーマスポーツ ────────────────────────────────────────────────────────────

def scrape_bima(existing_urls: set) -> list:
    """biima.co.jp/sports/recruit/ から募集要項を取得。"""
    url = "https://biima.co.jp/sports/recruit/"
    if url in existing_urls:
        return []

    soup = _get(url)
    if not soup:
        return []

    texts = [l.strip() for l in soup.get_text("\n").split("\n") if l.strip()]

    # 正社員 / アルバイト の各募集要項セクションを探す
    results = []
    for section_title in ["正社員募集要項", "アルバイト募集要項"]:
        if section_title not in texts:
            continue
        idx = texts.index(section_title)
        chunk = texts[idx: idx + 40]

        salary_text = ""
        location = ""
        for i, t in enumerate(chunk):
            if t == "給与" and i + 1 < len(chunk):
                salary_text = chunk[i + 1]
            if t == "勤務地" and i + 1 < len(chunk) and not location:
                location = chunk[i + 1]

        job_url = f"{url}#{section_title}"
        if job_url not in existing_urls:
            results.append(_row("ビーマスポーツ", f"コーチスタッフ（{section_title}）", location, salary_text, job_url))
            existing_urls.add(job_url)

    logger.info(f"  ビーマスポーツ: {len(results)} 件")
    return results


# ─── コペル ───────────────────────────────────────────────────────────────────

# 首都圏・関西・東海に絞った都道府県リスト（kurazemi.saiyo-job.jp のパス形式）
COPEL_PREF_PATHS = [
    "knto/tokyo", "knto/kanagawa", "knto/saitama", "knto/chiba",
    "knsi/osaka", "knsi/kyoto", "knsi/hyogo", "knsi/nara",
    "toki/aichi", "toki/shizuoka",
]

def scrape_copel(existing_urls: set) -> list:
    """コペル採用（kurazemi.saiyo-job.jp）から求人詳細をスクレイピング。"""
    base = "https://kurazemi.saiyo-job.jp"
    results = []

    for pref_path in COPEL_PREF_PATHS:
        list_url = f"{base}/dsaiyo/vvvo/pc_job/list/all/{pref_path}"
        pref_soup = _get(list_url)
        if not pref_soup:
            continue

        # 求人詳細リンク: /dsaiyo/vvvo/pc_job/show/{office_id}/{job_id}
        job_links = list(dict.fromkeys([
            base + a["href"]
            for a in pref_soup.find_all("a", href=True)
            if re.match(r"^/dsaiyo/vvvo/pc_job/show/", a.get("href", ""))
        ]))

        for job_url in job_links[:5]:  # 各都道府県上位5件
            if job_url in existing_urls:
                continue

            detail = _get(job_url)
            if not detail:
                continue

            texts = [l.strip() for l in detail.get_text("\n").split("\n") if l.strip()]

            # タイトル: h1は教室名のことがあるため、
            # 【正社員】【パート】などが含まれる行を優先して職種名とする
            title = ""
            for t in texts[:20]:
                if re.search(r"(指導員|療法士|保育士|管理責任者|支援員|教室長)", t):
                    title = t
                    break
            if not title:
                h1 = detail.find("h1") or detail.find("h2")
                title = h1.get_text(strip=True) if h1 else ""

            salary_text = ""
            location = ""
            for i, t in enumerate(texts):
                if re.search(r"^(給与|月給|時給|年収)$", t) and i + 1 < len(texts):
                    salary_text = texts[i + 1]
                if re.search(r"^(勤務地|勤務場所|アクセス)$", t) and not location:
                    nxt = texts[i + 1] if i + 1 < len(texts) else ""
                    if re.match(r"^〒", nxt) and i + 2 < len(texts):
                        location = texts[i + 2]
                    elif nxt:
                        location = nxt

            results.extend(_rows("コペル", title, location, salary_text, job_url))
            existing_urls.add(job_url)
            time.sleep(1.5)

    logger.info(f"  コペル: {len(results)} 件")
    return results


# ─── ネイスプラス ─────────────────────────────────────────────────────────────

def scrape_neis(existing_urls: set) -> list:
    """ネイスプラスの求人詳細ページ（/recruit/career/job-description/---id-N.html）をスクレイピング。
    まずインデックスページからリンクを収集し、見つからなければ既知IDで補完する。
    """
    base = "https://ne-is.com"
    career_index = f"{base}/recruit/career/"

    # インデックスページからリンクを収集
    index_soup = _get(career_index)
    job_links = []
    if index_soup:
        for a in index_soup.find_all("a", href=True):
            href = a["href"]
            if "job-description" in href and href.endswith(".html"):
                url = href if href.startswith("http") else base + "/" + href.lstrip("/")
                if url not in job_links:
                    job_links.append(url)

    # インデックスから取れなければ既知IDで補完
    if not job_links:
        known_ids = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]
        job_links = [
            f"{base}/recruit/career/job-description/---id-{i}.html"
            for i in known_ids
        ]

    results = []
    for url in job_links:
        if url in existing_urls:
            continue

        detail = _get(url)
        if not detail:
            continue

        texts = [l.strip() for l in detail.get_text("\n").split("\n") if l.strip()]

        # 職種・勤務場所・給与をラベル→次行パターンで抽出
        title = ""
        salary_text = ""
        location = ""
        for i, t in enumerate(texts):
            if t == "職種" and i + 1 < len(texts) and not title:
                title = texts[i + 1]
            if re.search(r"^(給与|月給|時給|年収)$", t) and i + 1 < len(texts) and not salary_text:
                salary_text = texts[i + 1]
            if re.search(r"^(勤務場所|勤務地)$", t) and i + 1 < len(texts) and not location:
                location = texts[i + 1]

        if not title:
            h1 = detail.find("h1")
            title = h1.get_text(strip=True) if h1 else url

        # 職種・給与が両方空のページ（採用TOPや説明ページ等）はスキップ
        if not title or not salary_text:
            logger.debug(f"  スキップ（データ不足）: {url}")
            existing_urls.add(url)  # 再取得しないよう登録だけする
            continue

        results.extend(_rows("ネイスプラス", title, location, salary_text, url))
        existing_urls.add(url)
        time.sleep(1.0)

    logger.info(f"  ネイスプラス: {len(results)} 件")
    return results


# ─── リーフラス ───────────────────────────────────────────────────────────────

def scrape_leafras(existing_urls: set) -> list:
    """リーフラス株式会社（LEIF）採用ページをスクレイピング。
    https://leafras.co.jp/recruit/ から求人リンクを収集し各ページをパース。
    """
    base = "https://leafras.co.jp"
    results = []

    index_soup = _get_insecure(f"{base}/recruit/")
    job_links = []
    if index_soup:
        for a in index_soup.find_all("a", href=True):
            href = a["href"]
            full = href if href.startswith("http") else base + href.lstrip(".")
            if "leafras.co.jp" in full and re.search(r"/recruit/", full) \
                    and full != f"{base}/recruit/" and full not in job_links:
                job_links.append(full)
        if not job_links:
            job_links = [f"{base}/recruit/"]

    for url in job_links[:20]:
        if url in existing_urls:
            continue

        detail = _get_insecure(url)
        if not detail:
            continue

        texts = [l.strip() for l in detail.get_text("\n").split("\n") if l.strip()]

        h1 = detail.find("h1")
        title = h1.get_text(strip=True) if h1 else ""
        if not title:
            title_tag = detail.find("title")
            title = title_tag.get_text(strip=True).split("|")[0].strip() if title_tag else url

        salary_text = ""
        location = ""
        for i, t in enumerate(texts):
            if re.search(r"^(給与|月給|時給|年収|賃金)$", t) and i + 1 < len(texts) and not salary_text:
                salary_text = texts[i + 1]
            if re.search(r"^(勤務地|勤務場所|就業場所)$", t) and i + 1 < len(texts) and not location:
                location = texts[i + 1]

        if not salary_text:
            continue

        results.extend(_rows("リーフラス", title, location, salary_text, url))
        existing_urls.add(url)
        time.sleep(1.5)

    logger.info(f"  リーフラス: {len(results)} 件")
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

    logger.info("ビーマスポーツ スクレイピング開始")
    all_results.extend(scrape_bima(existing_urls))

    logger.info("リーフラス スクレイピング開始")
    all_results.extend(scrape_leafras(existing_urls))

    # Selenium が必要な社（DNS sandbox制限のためHeadless Chromeを使用）
    logger.info("Selenium ドライバー起動")
    driver = build_driver()
    try:
        logger.info("リタリコ スクレイピング開始")
        all_results.extend(scrape_litalico(driver, existing_urls))
    finally:
        driver.quit()

    if all_results:
        with open(DATA_FILE, "a", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=CSV_HEADERS).writerows(all_results)

    logger.info(f"完了 — 採用ページ新規追記: {len(all_results)} 件")


if __name__ == "__main__":
    main()
