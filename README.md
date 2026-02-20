# LiveKit Recordings Downloader

Automates bulk download of LiveKit Cloud session recordings using browser
automation (Playwright). Discovers every session in the last 60 days, captures
the OCI pre-signed download URLs, and saves the recordings locally.

## How it works

1. Opens a Chromium browser and logs you in via a magic-link email (first run only).
2. Navigates the LiveKit Cloud sessions list (paginated, last 60 days).
3. Visits each session's observability page and intercepts the Oracle Cloud
   pre-signed audio URLs.
4. Downloads every `.ogg` recording with progress bars and resume support.

## Setup

```bash
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
```

Edit `.env` with your values:

```env
LIVEKIT_EMAIL=your.email@example.com
LIVEKIT_PROJECT_ID=p_xxxxxxxxxxxxxxx   # visible in your LiveKit Cloud project URL
```

## Usage

### First run (login required)

```bash
python auto_download_recordings.py --output-dir recordings_output
```

The script will prompt you to:
1. Type your email in the browser and click **Continue with email**.
2. Copy the magic-link from your inbox and paste it in the terminal.
3. Complete the sign-in in the browser, then press Enter.

Your session is saved to `.browser_state.json` for future runs.

### Subsequent runs (skip login)

```bash
python auto_download_recordings.py --output-dir recordings_output --skip-login
```

If the saved session has expired the script will tell you to re-run without
`--skip-login`.

## Resume support

Progress is tracked in `.progress.json`. If the script is interrupted, re-run
the same command — already-processed sessions are skipped automatically.

## Output

| File | Description |
|------|-------------|
| `recordings_output/` | Downloaded `.ogg` files |
| `recordings_manifest.jsonl` | Every discovered URL (for auditing) |
| `.progress.json` | Completed session IDs (enables resume) |
| `.browser_state.json` | Saved browser auth session |
