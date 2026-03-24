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
python auto_download_recordings.py
```

The script will prompt you to:
1. Type your email in the browser and click **Continue with email**.
2. Copy the magic-link from your inbox and paste it in the terminal.
3. Complete the sign-in in the browser, then press Enter.

Your session is saved to `.browser_state.json` for future runs.

### Subsequent runs (skip login)

```bash
python auto_download_recordings.py --skip-login
```

If the saved session has expired the script will tell you to re-run without
`--skip-login`.

### Custom output folder (optional)

By default the output folder is `recordings_output/<LIVEKIT_PROJECT_ID>`. You
can override it:

```bash
python auto_download_recordings.py --output-dir custom_folder --skip-login
```

## Output structure

All downloads live under `recordings_output/` (git-ignored), nested by project
ID. This keeps each project's files and state isolated, and nothing ever gets
accidentally committed.

```
recordings_output/
  p_xxxxxxxxxxxxxxx/        ← LIVEKIT_PROJECT_ID
    .progress.json            ← completed session IDs (enables resume)
    recordings_manifest.jsonl ← every discovered URL (for auditing)
    YYYY/
      MM/
        DD/
          HH/
            <room_id>.<room_name>.ogg
  p_yyyyyyyyyyyyyyy/        ← another project, fully separate
    .progress.json
    ...
```

| File | Description |
|------|-------------|
| `recordings_output/` | Git-ignored parent folder for all projects |
| `recordings_output/<project_id>/` | Root folder for a specific project |
| `recordings_output/<project_id>/.progress.json` | Completed session IDs (enables resume) |
| `recordings_output/<project_id>/recordings_manifest.jsonl` | Every discovered URL (for auditing) |
| `.browser_state.json` | Saved browser auth session (shared across projects) |

## Resume support

Progress is tracked per project in `recordings_output/<project_id>/.progress.json`.
If the script is interrupted, re-run the same command — already-processed
sessions are skipped automatically. Changing `LIVEKIT_PROJECT_ID` in `.env`
will resume from that project's own progress file.
