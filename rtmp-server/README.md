# MediaMTX ingest server for VideoMemory (RTMP / SRT / WebRTC-WHIP)

Android (or any client) can push video via **RTMP**, **SRT**, or **WebRTC/WHIP** to this server. VideoMemory pulls via **RTSP** from the same server. The included `mediamtx.yml` accepts arbitrary paths (via `paths: all_others`), so keys like `/live/front-door` work without extra config.

## Install MediaMTX

**macOS (Homebrew):**
```bash
brew install mediamtx
```

**Or download a binary:**
1. [Releases](https://github.com/bluenviron/mediamtx/releases) — pick your OS (e.g. `mediamtx_*_darwin_amd64.tar.gz` or `arm64` for Apple Silicon).
2. Extract and put `mediamtx` in your PATH or in this folder.

**Docker:**
```bash
docker run --rm -it -p 1935:1935 -p 8554:8554 bluenviron/mediamtx:latest
```

## Run

From this directory (optional: use the included config):

```bash
./run.sh
```

Or run MediaMTX directly:

```bash
mediamtx mediamtx.yml
# or with default config:
mediamtx
```

Ports (defaults):

- **RTMP** 1935 — Android app pushes to `rtmp://YOUR_IP:1935/live/streamkey`
- **SRT** 8890 — Publish using `srt://YOUR_IP:8890?streamid=publish:live/streamkey`
- **WHIP (WebRTC ingest)** 8889 — Publish using `http://YOUR_IP:8889/live/streamkey/whip` (WHIP-capable client)
- **WebRTC ICE UDP** 8189/udp — required for low-latency WebRTC media path in many setups
- **RTSP** 8554 — VideoMemory pulls from `rtsp://YOUR_IP:8554/live/streamkey` (VideoMemory derives this from the RTMP URL you add)

Use your machine’s LAN IP (e.g. `192.168.1.42`) so the phone and VideoMemory can reach it.
