# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Lint:**
```bash
flake8 .
```

**Test:**
```bash
pytest
# Run a single test file:
pytest tests/test_analysis.py
```

**Install dependencies (local development):**
```bash
pip install -r requirements.txt
```

**Full system installation (Raspberry Pi only):**
```bash
curl -s https://raw.githubusercontent.com/cincyjosh/BirdNET-Pi/main/newinstaller.sh | bash
```

## Architecture

BirdNET-Pi is a real-time acoustic bird classification system targeting Raspberry Pi. It records audio, runs ML inference, stores detections in SQLite, serves a PHP web UI via Caddy, and sends notifications via Apprise.

### Data Flow

```
USB mic → [birdnet_recording.sh] → WAV files in ~/BirdSongs/StreamData/
  → [inotify] → [birdnet_analysis.py]
      → TFLite inference → Detection objects
      → [reporting queue]
          → extract audio clip (sox)
          → generate spectrogram
          → write to SQLite (birds.db)
          → send notifications (Apprise)
          → upload to BirdWeather (optional)
```

### Key Components

**Analysis Pipeline** (`scripts/birdnet_analysis.py`, `scripts/utils/`)
- `birdnet_analysis.py`: Main daemon — watches `StreamData/` via inotify, loads TFLite models, runs inference with overlapping audio chunks, filters human speech for privacy
- `utils/models.py`: Wraps multiple model architectures (BirdNET v1, v2.4 FP16, Perch, BirdNET-Go); handles location-based species filtering by lat/lon + week
- `utils/analysis.py`: Core inference logic (audio loading via librosa, chunking, scoring)
- `utils/reporting.py`: Processes detections — extracts clips, generates spectrograms, writes DB, dispatches notifications
- `utils/classes.py`: `Detection` and `ParseFileName` dataclasses
- `utils/helpers.py`: Config loading from `birdnet.conf` (INI format)
- `utils/db.py`: SQLite query functions
- `utils/notifications.py`: Apprise integration (90+ platforms, MQTT support)

**Web Interface** (`scripts/*.php`, `homepage/`)
- PHP + HTML/CSS/JS, served by Caddy with PHP-FPM
- Pages: overview (daily counts), play (audio + metadata), spectrogram, stats, settings, tools (backup/restore, service controls)
- Default auth: HTTP Basic, user `birdnet`, no password
- `homepage/index.php` is the main entry; `homepage/views.php` handles view components

**Database**
- SQLite at `scripts/birds.db`
- Main table: `detections` (date, time, species, confidence, file paths)

**Services** (systemd, defined in `templates/`)
- `birdnet_recording.service` — audio capture
- `birdnet_analysis.service` — inference daemon
- `http.service` — Caddy web server

**Models** (`model/`)
- TFLite model files + label files per model version
- `model/l18n/` — 45+ language JSON files for localized species names

### Linting Rules

`.flake8` sets max line length to 160 and max complexity to 15.

### CI

- `python-ci.yml`: flake8 on PRs touching `**.py`, tested against Python 3.9, 3.11, 3.13
- `python-app.yml`: flake8 + pytest on push to `main`/`test_me` and PRs to `main`, using Python 3.11

### License

CC BY-NC-SA 4.0 — no commercial use permitted.
