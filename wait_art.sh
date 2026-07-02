#!/bin/bash
while true; do
  STATUS=$(grep -m 1 '"art_status"' output/world_creator_drafts/creator_20260608_051817_8e89884e/draft_manifest.json | awk -F'"' '{print $4}')
  if [ "$STATUS" != "art_running" ]; then
    echo "Art worker finished with status: $STATUS"
    exit 0
  fi
  sleep 10
done
