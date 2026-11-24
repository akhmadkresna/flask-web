# Cast to TV

A small Flask web app. Open it on your phone, pick a video, and it plays on your TV
over the local network (DLNA/UPnP — works with most Samsung, LG, Sony, Philips, etc.
smart TVs, plus Kodi/VLC renderers).

## Run (on a computer on the same Wi-Fi as the TV)

    python3 -m venv .venv && . .venv/bin/activate
    pip install -r requirements.txt
    python app.py

Open the printed `http://<computer-ip>:5000` URL on your phone.

- **Upload from phone** — pick a video, it uploads and starts casting.
- **Library** — anything in `media/` (or `$MEDIA_DIR`) is listed; tap Cast.
- **Video link** — paste a direct `.mp4` URL; the TV fetches it itself.
- Play/pause, seek, ±10s, volume from the phone.

## Notes

- The server must run on a device on the same LAN as the TV (laptop, Raspberry Pi,
  NAS). It cannot run in a cloud host, since it must reach the TV and the TV must reach it.
- TV not found? Make sure the TV is on, enable "DLNA / media sharing / network standby"
  in its settings, and allow UDP 1900 + TCP 5000 through your computer's firewall.
  As a fallback, paste the TV's description URL under "TV not found?".
- TVs decode H.264 MP4 most reliably. MKV/HEVC support varies by model.
