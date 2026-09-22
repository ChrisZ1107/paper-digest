#!/usr/bin/env bash
set -euo pipefail
cd /home/chris/paper-digest-github
/usr/bin/git pull --rebase
/usr/bin/python3 youtube_monitor.py
if ! /usr/bin/git diff --quiet -- public/youtube-feed.xml state/youtube.json; then
  /usr/bin/git add public/youtube-feed.xml state/youtube.json
  /usr/bin/git commit -m "Update AIPaperSlop paper feed"
  /usr/bin/git push origin main
fi
/usr/bin/gh workflow run daily.yml --repo ChrisZ1107/paper-digest -f regenerate=false
