#!/usr/bin/env python3
"""
Automatically log into LiveKit Cloud, discover all session recordings, and
download them locally.

Only manual step: pasting the magic-link URL once (first run only).
Everything else is fully automated.

Usage:
  python auto_download_recordings.py --output-dir recordings_output
  python auto_download_recordings.py --output-dir recordings_output --skip-login
"""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
import requests
from tqdm import tqdm
from playwright.sync_api import sync_playwright, Page, Response

load_dotenv()

# ── Config ─────────────────────────────────────────────────────────────────────

EMAIL      = os.environ.get("LIVEKIT_EMAIL", "")
PROJECT_ID = os.environ.get("LIVEKIT_PROJECT_ID", "")

if not EMAIL or not PROJECT_ID:
    sys.exit("Error: set LIVEKIT_EMAIL and LIVEKIT_PROJECT_ID in your .env file.")

SESSIONS_URL = f"https://cloud.livekit.io/projects/{PROJECT_ID}/sessions"
STATE_FILE  = Path(__file__).parent / ".browser_state.json"
API_LOG     = Path(__file__).parent / "api_responses.log"

OCI_PATTERN = re.compile(
    r"https://[^\"'\s]*objectstorage\.[^\"'\s]*oraclecloud\.com[^\"'\s]*recordings[^\"'\s]*",
    re.IGNORECASE,
)

# ── Helpers ────────────────────────────────────────────────────────────────────

def deep_find_urls(obj, found: set):
    if isinstance(obj, str):
        for m in OCI_PATTERN.finditer(obj):
            found.add(m.group(0))
    elif isinstance(obj, dict):
        for v in obj.values():
            deep_find_urls(v, found)
    elif isinstance(obj, list):
        for item in obj:
            deep_find_urls(item, found)


def make_filename(url: str) -> str:
    path = urlparse(url).path.rstrip("/")
    parts = path.split("/")
    try:
        idx = next(i for i, p in enumerate(parts) if p == "recordings")
        after = parts[idx + 1:]
        date    = "".join(after[:3])
        room_id = after[4] if len(after) > 4 else "room"
        ftype   = after[5] if len(after) > 5 else "recording"
        return f"{date}_{room_id}_{ftype}.ogg"
    except (StopIteration, IndexError):
        return "_".join(parts[-2:]) + ".ogg"


# ── Login ──────────────────────────────────────────────────────────────────────

def login(page: Page):
    page.goto("https://cloud.livekit.io/login", wait_until="domcontentloaded", timeout=30_000)

    if f"/projects/{PROJECT_ID}" in page.url:
        print("Already logged in.\n")
        return

    print("\n" + "=" * 60)
    print("  STEP 1 — In the browser window:")
    print(f"    a) Type  {EMAIL}  in the email box")
    print("    b) Click 'Continue with email'")
    print("    c) Wait for the 'Check your email' confirmation")
    print("=" * 60)
    input("\n  Press Enter when you see 'Check your email': ")

    print("\n" + "=" * 60)
    print("  STEP 2 — In your inbox:")
    print("    a) Find the email from LiveKit")
    print("    b) Copy the sign-in link address")
    print("    c) Paste it into the address bar of the browser window")
    print("       that this tool opened, then press Enter to navigate")
    print("    d) Click 'Confirm login' (or 'Continue') in that browser")
    print("=" * 60)
    input("\n  Press Enter here once you have confirmed the login in the browser: ")

    print("  Login complete.\n")


# ── Session + recording discovery ─────────────────────────────────────────────

PROGRESS_FILE = Path(__file__).parent / ".progress.json"
BASE_URL = f"https://cloud.livekit.io/projects/{PROJECT_ID}/sessions"


def sessions_url_60days() -> str:
    """Build the sessions URL with the 'Past 60 days' filter.

    The opq param is a fixed base64 query (sort by started_at DESC).
    start and end are millisecond timestamps calculated at runtime.
    """
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (60 * 24 * 60 * 60 * 1000)
    opq = "WygnYSEzfmIhKCdjISdzdGFydGVkX2F0J35kISdERVNDJ35lISgpKSldXw=="
    return (
        f"https://cloud.livekit.io/projects/{PROJECT_ID}/sessions"
        f"?opq={opq}&start={start_ms}&end={now_ms}"
    )


def get_session_ids(page: Page) -> list[str]:
    """Collect all room IDs from the sessions list, paginating until done."""
    session_ids: list[str] = []

    url = sessions_url_60days()
    print(f"  Loading sessions with 'Past 60 days' filter...")
    page.goto(url, wait_until="networkidle", timeout=30_000)

    page_num = 1

    while True:
        page.wait_for_load_state("networkidle", timeout=15_000)

        ids_on_page = page.evaluate("""
            () => {
                const hrefs = [...document.querySelectorAll('a[href]')].map(a => a.href);
                const ids = hrefs
                    .map(h => { const m = h.match(/\\/sessions\\/(RM_[^/?#]+)/); return m ? m[1] : null; })
                    .filter(Boolean);
                return [...new Set(ids)];
            }
        """)

        new_ids = [rid for rid in ids_on_page if rid not in session_ids]
        session_ids.extend(new_ids)
        print(f"  Page {page_num}: {len(new_ids)} new sessions (total so far: {len(session_ids)})")

        if not new_ids:
            print("  No new sessions on this page — pagination complete.")
            break

        # Remember first ID on current page so we can detect when content changes
        first_id = ids_on_page[0] if ids_on_page else None

        # Use JavaScript to find and click the Next button.
        # Key insight: the pagination controls are BELOW all 20 session rows in
        # the DOM, so we anchor to the last session link and search after it.
        result = page.evaluate("""
            () => {
                function isEnabled(el) {
                    return el
                        && !el.disabled
                        && el.getAttribute('aria-disabled') !== 'true'
                        && el.getAttribute('disabled') === null;
                }

                // Strategy 1: text match across ALL buttons/links (case-insensitive)
                for (const el of document.querySelectorAll('button, a')) {
                    const txt = el.textContent.trim();
                    if (/^(Next|Next page|Go to next page|›|»|>)$/i.test(txt) && isEnabled(el)) {
                        el.click();
                        return { clicked: true, strategy: 'text:' + txt };
                    }
                }

                // Strategy 2: aria-label variants
                for (const lbl of ['Next', 'Next page', 'Go to next page', 'next', 'next page']) {
                    const el = document.querySelector('[aria-label="' + lbl + '"]');
                    if (el && isEnabled(el)) {
                        el.click();
                        return { clicked: true, strategy: 'aria:' + lbl };
                    }
                }

                // Strategy 3: DOM-position anchor — find all buttons/links that appear
                // AFTER the last session row link (RM_...) in document order.
                // The pagination bar is rendered below the table, so this reliably
                // targets only the pagination controls (and any footer).
                const sessionLinks = [...document.querySelectorAll('a[href*="/sessions/RM_"]')];
                if (sessionLinks.length > 0) {
                    const lastSession = sessionLinks[sessionLinks.length - 1];
                    const allEls = [...document.querySelectorAll('button, a')];
                    const afterSession = allEls.filter(el =>
                        (lastSession.compareDocumentPosition(el) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0
                    );
                    const enabledAfter = afterSession.filter(isEnabled);
                    // Skip pure page-number buttons (text is just digits).
                    const nonPageNum = enabledAfter.filter(el => !/^\\d+$/.test(el.textContent.trim()));

                    if (nonPageNum.length > 0) {
                        // Prefer a button whose text explicitly mentions "next"
                        // (avoids picking "Go to last page" which also appears after sessions).
                        const nextCandidates = nonPageNum.filter(el =>
                            /next/i.test(el.textContent) ||
                            /next/i.test(el.getAttribute('aria-label') || '')
                        );
                        const target = nextCandidates.length > 0
                            ? nextCandidates[nextCandidates.length - 1]
                            : nonPageNum[nonPageNum.length - 1];
                        target.click();
                        return {
                            clicked: true,
                            strategy: 'after-sessions:' + target.textContent.trim().substring(0, 20)
                                + '|aria=' + target.getAttribute('aria-label'),
                        };
                    }

                    // Nothing enabled after sessions → we are on the last page.
                    // Dump what IS there so we can see why nothing was clicked.
                    const dump = afterSession.map(el => ({
                        tag: el.tagName,
                        text: el.textContent.trim().substring(0, 40),
                        disabled: el.disabled,
                        ariaLabel: el.getAttribute('aria-label'),
                        ariaDisabled: el.getAttribute('aria-disabled'),
                    }));
                    return { clicked: false, debug: dump, reason: 'last-page-or-all-disabled' };
                }

                // Fallback: dump buttons 30-60 (past the sidebar/header, into table area)
                const dump = [...document.querySelectorAll('button, a')].slice(30, 60).map(el => ({
                    tag: el.tagName,
                    text: el.textContent.trim().substring(0, 40),
                    disabled: el.disabled,
                    ariaLabel: el.getAttribute('aria-label'),
                    ariaDisabled: el.getAttribute('aria-disabled'),
                    cls: el.className.toString().substring(0, 60),
                }));
                return { clicked: false, debug: dump, reason: 'no-session-links-found' };
            }
        """)

        if result.get("clicked"):
            strategy = result.get("strategy", "unknown")
            print(f"  Clicked Next button (strategy: {strategy})")

            # Wait for new session IDs to appear in the DOM
            if first_id:
                try:
                    page.wait_for_function(
                        """(prevId) => {
                            const hrefs = [...document.querySelectorAll('a[href]')].map(a => a.href);
                            const ids = hrefs
                                .map(h => { const m = h.match(/\\/sessions\\/(RM_[^/?#]+)/); return m ? m[1] : null; })
                                .filter(Boolean);
                            return ids.length > 0 && ids[0] !== prevId;
                        }""",
                        arg=first_id,
                        timeout=30_000,
                    )
                except Exception as e:
                    print(f"  DOM didn't change after Next click ({e}) — stopping.")
                    break
            else:
                page.wait_for_load_state("networkidle", timeout=10_000)

            page_num += 1
            continue

        # Could not click — print debug info and stop
        debug = result.get("debug", [])
        print("  Could not find a clickable Next button. Button dump:")
        for b in debug:
            print(f"    [{b['tag']}] text={b['text']!r:40s} aria={b['ariaLabel']!r} disabled={b['disabled']} cls={b['cls']!r}")
        print("  Pagination complete.")
        break

    return session_ids


def collect_and_download(page: Page, out_dir: Path, http: requests.Session) -> dict:
    """Visit each session's /observability page, capture the OCI pre-signed URL,
    and download the recording immediately (before the 30-min expiry).

    Progress is saved after each download so the script can resume if interrupted.
    Every discovered URL is also appended to recordings_manifest.jsonl.
    """
    stats = {"found": 0, "downloaded": 0, "skipped": 0, "failed": 0}
    manifest_path = Path(__file__).parent / "recordings_manifest.jsonl"

    # Load progress from a previous run (supports resume)
    done: set[str] = set()
    if PROGRESS_FILE.exists():
        try:
            done = set(json.loads(PROGRESS_FILE.read_text()))
            print(f"  Resuming — {len(done)} session(s) already processed.\n")
        except Exception:
            pass

    # Capture OCI requests into a per-session buffer
    current_urls: list[str] = []

    def on_request(request):
        if OCI_PATTERN.search(request.url):
            current_urls.append(request.url)

    def on_response(response: Response):
        if "cloud.livekit.io" not in response.url:
            return
        if "json" not in response.headers.get("content-type", ""):
            return
        try:
            body = response.json()
        except Exception:
            return
        found: set[str] = set()
        deep_find_urls(body, found)
        current_urls.extend(found)

    page.on("request", on_request)
    page.on("response", on_response)

    # Step 1 — collect all session IDs
    print("Collecting session IDs...")
    session_ids = get_session_ids(page)

    if not session_ids:
        print("  No sessions found. Make sure you are logged in.")
        return stats

    total = len(session_ids)
    print(f"\nFound {total} sessions. Downloading recordings...\n")

    for i, room_id in enumerate(session_ids):
        prefix = f"[{i+1}/{total}] {room_id}"

        if room_id in done:
            print(f"  {prefix} — already done, skipping")
            stats["skipped"] += 1
            continue

        current_urls.clear()
        obs_url = f"{BASE_URL}/{room_id}/observability"

        try:
            page.goto(obs_url, wait_until="networkidle", timeout=15_000)
            time.sleep(2)  # allow the page to fire audio requests
        except Exception as e:
            print(f"  {prefix} — page load failed: {e}")

        # Deduplicate captured URLs by path
        seen_paths: set[str] = set()
        for url in current_urls:
            path = urlparse(url).path
            if path in seen_paths:
                continue
            seen_paths.add(path)
            stats["found"] += 1

            fname = make_filename(url)
            out_path = out_dir / fname

            # Append to manifest immediately
            with open(manifest_path, "a", encoding="utf-8") as mf:
                mf.write(json.dumps({"url": url, "filename": fname, "room_id": room_id}) + "\n")

            if out_path.exists():
                print(f"  {prefix} — already downloaded: {fname}")
                stats["skipped"] += 1
            else:
                print(f"  {prefix} — downloading: {fname}")
                ok = download_file(http, url, out_path)
                if ok:
                    stats["downloaded"] += 1
                else:
                    stats["failed"] += 1

        if not seen_paths:
            print(f"  {prefix} — no recording")

        # Mark session as done and save progress
        done.add(room_id)
        PROGRESS_FILE.write_text(json.dumps(list(done)))

    return stats


# ── Download ───────────────────────────────────────────────────────────────────

def download_file(session: requests.Session, url: str, out_path: Path, retries: int = 3) -> bool:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(1, retries + 1):
        try:
            with session.get(url, stream=True, timeout=60) as r:
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0)
                with open(out_path, "wb") as f, tqdm(
                    total=total or None, unit="B", unit_scale=True,
                    desc=out_path.name, leave=True,
                ) as pbar:
                    for chunk in r.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                            pbar.update(len(chunk))
            return True
        except Exception as e:
            if attempt == retries:
                print(f"  [error] {out_path.name}: {e}")
                return False
            print(f"  [retry {attempt}/{retries}] {e}")
    return False


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Download all LiveKit Cloud recordings")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--skip-login", action="store_true",
                        help="Reuse saved browser session (skip magic-link step)")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)

        ctx_kwargs = {}
        if STATE_FILE.exists() and args.skip_login:
            ctx_kwargs["storage_state"] = str(STATE_FILE)
            print(f"Restoring session from {STATE_FILE}")

        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()

        # Login
        if not args.skip_login:
            login(page)
            context.storage_state(path=str(STATE_FILE))
            print(f"  Session saved → {STATE_FILE} (use --skip-login next run)\n")
        else:
            # Verify the saved session is still valid
            page.goto(SESSIONS_URL, wait_until="domcontentloaded", timeout=20_000)
            if "login" in page.url:
                print("Saved session expired. Re-run without --skip-login.")
                browser.close()
                sys.exit(1)

        print("=" * 60)
        print("Scanning sessions and downloading recordings...")
        print(f"Output folder: {out_dir.resolve()}")
        print("=" * 60 + "\n")

        http = requests.Session()
        stats = collect_and_download(page, out_dir, http)
        browser.close()

    print("\n" + "=" * 60)
    print(f"  Recordings found:      {stats['found']}")
    print(f"  Downloaded:            {stats['downloaded']}")
    print(f"  Already existed:       {stats['skipped']}")
    print(f"  Failed:                {stats['failed']}")
    print("=" * 60)
    print(f"\nFiles saved to: {out_dir.resolve()}")
    print(f"Progress saved to {PROGRESS_FILE} — re-run anytime to resume.")


if __name__ == "__main__":
    main()
