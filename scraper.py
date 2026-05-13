"""
ekantipur.com Playwright scraper (sync API, Python 3.11+).

TASK 1 — Top 5 मनोरञ्जन (entertainment) stories from the /entertainment listing.
  The live site uses div.category-inner-wrapper rows (no <main> or <article>).

TASK 2 — Cartoon of the day: homepage block section.e-section with .cartoon-slider
  (heading links to /cartoon). Active slide uses lazy images (data-src).
  Cartoonist line often appears only on /cartoon under .cartoon-description — we
  merge that in after matching alt or image URL.

Output: output.json with ensure_ascii=False for Nepali/Devanagari.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse, urljoin

from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

BASE_URL = "https://ekantipur.com"
OUTPUT_PATH = Path(__file__).resolve().parent / "output.json"
HEADLESS = False
DEFAULT_TIMEOUT_MS = 30_000


def _abs_url(page_url: str, href: str | None) -> str | None:
    if not href:
        return None
    # Keep query string (required for assets-cdn-api.ekantipur.com/thumb.php?src=...)
    return urljoin(page_url, href)


def _txt(locator) -> str:
    try:
        t = locator.inner_text(timeout=2_000)
        return (t or "").strip()
    except (PlaywrightTimeout, Exception):
        return ""


def _first_img_src(card, page_url: str) -> str | None:
    """Resolve thumbnail URL from src, data-src, or data-original (lazy loading)."""
    for sel in ("img[src]", "img[data-src]", "img[data-original]"):
        try:
            img = card.locator(sel).first
            if not img.count():
                continue
            for attr in ("src", "data-src", "data-original"):
                try:
                    raw = img.get_attribute(attr)
                    if raw and not raw.startswith("data:"):
                        if raw.startswith("//"):
                            raw = "https:" + raw
                        return _abs_url(page_url, raw)
                except Exception:
                    continue
        except Exception:
            continue
    return None


def _section_category_label(page) -> str:
    """Nepali section label from listing header (e.g. मनोरञ्जन)."""
    try:
        loc = page.locator("header.detail-header .category-name").first
        if loc.count():
            t = _txt(loc)
            if t:
                return t
    except Exception:
        pass
    return "मनोरञ्जन"


def _pick_category_label(card, default: str) -> str:
    """Subcategory chip on the card when present; else section default."""
    candidates = (
        "[class*='category']",
        "[class*='tag']",
        "[class*='label']",
        "[class*='kicker']",
    )
    for sel in candidates:
        try:
            loc = card.locator(sel).first
            if not loc.count():
                continue
            text = _txt(loc)
            if text and len(text) < 40 and text != default:
                return text
        except Exception:
            continue
    return default


def _pick_author(card) -> str | None:
    try:
        loc = card.locator("div.author-name a[href*='/author/']").first
        if loc.count():
            name = _txt(loc)
            return name or None
    except Exception:
        pass
    try:
        a = card.locator("a[href*='/author/']").first
        if a.count():
            name = _txt(a)
            return name or None
    except Exception:
        pass
    for sel in ("[class*='author']", "[class*='byline']"):
        try:
            loc = card.locator(sel).first
            if not loc.count():
                continue
            name = _txt(loc)
            if name:
                return name
        except Exception:
            continue
    return None


def _dedupe_href(href: str | None, seen: set[str]) -> bool:
    if not href:
        return False
    if href in seen:
        return False
    seen.add(href)
    return True


def _thumb_asset_key(url: str | None) -> str | None:
    """Stable key inside thumb.php?src=... for matching homepage vs /cartoon."""
    if not url:
        return None
    try:
        if "thumb.php" in url:
            q = parse_qs(urlparse(url).query)
            src = q.get("src", [None])[0]
            if src:
                return unquote(src)
        return unquote(urlparse(url).path)
    except Exception:
        return None


def _parse_cartoon_caption(text: str) -> tuple[str, str]:
    """Split 'Title - Author' from .cartoon-description paragraph."""
    text = text.strip()
    parts = re.split(r"\s*-\s*", text, maxsplit=1)
    if len(parts) == 2:
        left, right = parts[0].strip(), parts[1].strip()
        return left, right
    return text, ""


def scrape_entertainment_top5(page) -> list[dict[str, Any]]:
    listing_url = f"{BASE_URL}/entertainment"
    page.goto(listing_url, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)

    try:
        page.wait_for_load_state("networkidle", timeout=DEFAULT_TIMEOUT_MS)
    except PlaywrightTimeout:
        pass

    try:
        page.wait_for_selector("div.category-inner-wrapper", timeout=DEFAULT_TIMEOUT_MS)
    except PlaywrightTimeout:
        page.wait_for_selector("body", timeout=DEFAULT_TIMEOUT_MS)

    default_cat = _section_category_label(page)
    results: list[dict[str, Any]] = []
    seen_hrefs: set[str] = set()

    cards = page.locator("div.category-inner-wrapper")
    try:
        n = cards.count()
        for i in range(min(n, 20)):
            if len(results) >= 5:
                break
            card = cards.nth(i)
            try:
                link_el = card.locator("div.category-description h2 a").first
                if not link_el.count():
                    link_el = card.locator("h2 a[href*='/entertainment/']").first
                href = link_el.get_attribute("href") if link_el.count() else None
                abs_h = _abs_url(page.url, href)
                if not abs_h or "/entertainment/" not in abs_h or not abs_h.endswith(".html"):
                    continue
                if not _dedupe_href(abs_h, seen_hrefs):
                    continue

                title = _txt(link_el) if link_el.count() else ""
                image_url = _first_img_src(card.locator("div.category-image").first, page.url)
                if not image_url:
                    image_url = _first_img_src(card, page.url)

                category = _pick_category_label(card, default_cat)
                author = _pick_author(card)

                if title and image_url:
                    results.append(
                        {
                            "title": title,
                            "image_url": image_url,
                            "category": category,
                            "author": author,
                        }
                    )
            except Exception:
                continue
    except Exception:
        pass

    return results[:5]


def _wait_cartoon_img_ready(img_locator, page, attempts: int = 40) -> str | None:
    """Poll until lazy image exposes a real http(s) URL."""
    for _ in range(attempts):
        try:
            u = img_locator.get_attribute("src") or img_locator.get_attribute("data-src")
            if u and u.startswith("http"):
                return u
            if u and u.startswith("//"):
                return "https:" + u
        except Exception:
            pass
        try:
            page.wait_for_timeout(150)
        except Exception:
            break
    return None


def scrape_cartoon_of_the_day(page) -> dict[str, Any]:
    page.goto(BASE_URL, wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
    try:
        page.wait_for_load_state("networkidle", timeout=DEFAULT_TIMEOUT_MS)
    except PlaywrightTimeout:
        pass

    title = ""
    image_url: str | None = None
    author = ""

    try:
        page.wait_for_selector("section.e-section .cartoon-slider", timeout=DEFAULT_TIMEOUT_MS)
        section = page.locator("section.e-section").filter(has=page.locator(".cartoon-slider")).first
        slide = section.locator(".swiper-slide-active").first
        slide.wait_for(state="visible", timeout=15_000)

        img = slide.locator("img").first
        image_url = _wait_cartoon_img_ready(img, page)
        a = slide.locator("a.loading-img").first
        if a.count():
            href_a = a.get_attribute("href")
            if href_a and href_a.startswith("http"):
                image_url = href_a

        try:
            title = (img.get_attribute("alt") or "").strip()
        except Exception:
            title = ""
    except Exception:
        pass

    hero_key = _thumb_asset_key(image_url)
    hero_alt = title

    try:
        page.goto(f"{BASE_URL}/cartoon", wait_until="domcontentloaded", timeout=DEFAULT_TIMEOUT_MS)
        try:
            page.wait_for_load_state("networkidle", timeout=DEFAULT_TIMEOUT_MS)
        except PlaywrightTimeout:
            pass
        page.wait_for_selector("section.cartoon-main-wrapper .cartoon-wrapper", timeout=DEFAULT_TIMEOUT_MS)

        wrappers = page.locator("section.cartoon-main-wrapper .cartoon-wrapper")
        n = min(wrappers.count(), 20)
        chosen = None
        for i in range(n):
            w = wrappers.nth(i)
            try:
                wkey = _thumb_asset_key(
                    _first_img_src(w.locator("div.cartoon-image").first, page.url)
                )
                walt = ""
                try:
                    im = w.locator("div.cartoon-image img").first
                    if im.count():
                        walt = (im.get_attribute("alt") or "").strip()
                except Exception:
                    pass
                if hero_key and wkey and hero_key == wkey:
                    chosen = w
                    break
                if hero_alt and walt and hero_alt == walt:
                    chosen = w
                    break
            except Exception:
                continue
        if chosen is None and n:
            chosen = wrappers.nth(0)

        if chosen is not None:
            try:
                cap = _txt(chosen.locator("div.cartoon-description p").first)
                left, right = _parse_cartoon_caption(cap)
                if left:
                    title = left
                if right:
                    author = right
            except Exception:
                pass

        # Recurring strip: today's image row may omit the cartoonist while another
        # card on the same page shares the same caption prefix (e.g. 'गजब छ बा').
        if not author and title:
            prefix = re.sub(r"[!?।\s]+$", "", title).strip()[:12]
            for i in range(n):
                w = wrappers.nth(i)
                try:
                    cap = _txt(w.locator("div.cartoon-description p").first)
                    left, right = _parse_cartoon_caption(cap)
                    if not right:
                        continue
                    if left and prefix and (left.startswith(prefix) or prefix in left):
                        author = right
                        if left:
                            title = left
                        break
                except Exception:
                    continue
    except Exception:
        pass

    return {
        "title": title or "",
        "image_url": image_url or "",
        "author": author or "",
    }


def main() -> None:
    payload: dict[str, Any] = {
        "entertainment_news": [],
        "cartoon_of_the_day": {},
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(
            locale="ne-NP",
            viewport={"width": 1280, "height": 900},
        )
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        try:
            try:
                payload["entertainment_news"] = scrape_entertainment_top5(page)
            except Exception as exc:
                payload["entertainment_news"] = []
                payload["_error_entertainment"] = repr(exc)

            try:
                payload["cartoon_of_the_day"] = scrape_cartoon_of_the_day(page)
            except Exception as exc:
                payload["cartoon_of_the_day"] = {
                    "title": "",
                    "image_url": "",
                    "author": "",
                }
                payload["_error_cartoon"] = repr(exc)

        finally:
            context.close()
            browser.close()

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
