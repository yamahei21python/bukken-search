"""一覧・詳細スクレイパー共有処理。HTTP取得と待機だけを集約。"""
import random
import time
from typing import Final

import requests
from bs4 import BeautifulSoup

HEADERS: Final = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36"
}
RETRY_STATUS_CODES: Final = frozenset((429, 500, 502, 503, 504))


def fetch_soup(url: str, retry: int = 3,
               retry_delay: float = 2) -> BeautifulSoup:
    """URL取得。429/5xxと通信例外を線形バックオフで再試行。"""
    for attempt in range(retry):
        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
            if response.status_code in RETRY_STATUS_CODES:
                if attempt == retry - 1:
                    response.raise_for_status()
                time.sleep(retry_delay * (attempt + 1))
                continue
            response.raise_for_status()
            return BeautifulSoup(response.text, "lxml")
        except requests.RequestException:
            if attempt == retry - 1:
                raise
            time.sleep(retry_delay * (attempt + 1))
    raise RuntimeError(f"fetch failed after {retry}: {url}")


def sleep_with_jitter(seconds: float, jitter: float) -> None:
    """基準秒数に0〜jitter秒を加えて待機。"""
    time.sleep(seconds + random.uniform(0, jitter))
