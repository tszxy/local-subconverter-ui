#!/bin/zsh
set -eu

cd /Users/zhang/Documents/Codex/2026-05-10/clash/subconverter
echo "Starting local subconverter from $(pwd) at $(date)" >> subconverter.launch.log
exec ./subconverter
