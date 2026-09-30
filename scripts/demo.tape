# VHS tape — renders the RCM demo to demo.mp4 (a ~75s screen recording).
# Render from the repo root:  vhs scripts/demo.tape
# Requires: brew install vhs   (pulls ffmpeg + ttyd)
#
# Low framerate + modest resolution keep the temp-frame footprint small
# (terminal content is near-static, so 8 fps looks fine).

Output demo.mp4

Set Shell bash
Set Framerate 8
Set FontSize 18
Set Width 1120
Set Height 720
Set Padding 22
Set TypingSpeed 40ms

Type "RCM_DEMO_PACE=1 .venv/bin/python scripts/demo_837p.py"
Sleep 700ms
Enter

# Record through the whole paced run (~74s of holds) plus a moment at the end.
Sleep 80s
