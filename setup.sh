#!/data/data/com.termux/files/usr/bin/bash
# Auto installer untuk agent MIRA AI V1

pkg update -y && pkg upgrade -y
pkg install python git -y

echo "✅ Python & git siap dipasang."
echo "👉 Sekarang run: python3 mira_agent.py status"
