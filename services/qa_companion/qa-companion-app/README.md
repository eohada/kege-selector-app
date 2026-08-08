# BooStudy QA Companion App
Desktop application for background Shadowplay (instant 15s replay capture) and bug reporting.

## Roadmap
1. `ring_buffer.py` - Core logic for taking screenshots 10fps and keeping last 15s in memory.
2. `recorder.py` - Logic to merge the 15s buffers into an mp4/webm utilizing opencv-python on hotkey trigger.
3. `api_client.py` - Connects to BooStudy backend (`/qa/ad-hoc`) to seamlessly send the report.
4. `tray_ui.py` - Minimalist GUI (PyQt6 / CustomTkinter) with fields identical to the web widget.
