import sys
import os
import time
from flask import Flask, jsonify, send_file
from flask_cors import CORS
from recorder import ShadowplayRecorder

app = Flask(__name__)
CORS(app)

recorder = ShadowplayRecorder(fps=10, buffer_seconds=15)
recorder.start()

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "running", "buffer_size": len(recorder.frames_buffer)})

@app.route('/capture', methods=['POST', 'GET'])
def capture_replay():
    """Веб-виджет дергает этот эндпоинт, чтобы получить свежее видео"""
    vid_path = os.path.join(os.getcwd(), f"instant_replay.mp4")
    
    final_path = recorder.save_replay(vid_path)
    
    if final_path and os.path.exists(final_path):
        return send_file(final_path, as_attachment=True, mimetype='video/mp4')
    
    return jsonify({"error": "Failed to generate video"}), 500

if __name__ == '__main__':
    print("========================================")
    print("BooStudy QA Companion Daemon running!")
    print("Listening on http://127.0.0.1:4444")
    print("========================================")
    app.run(host='127.0.0.1', port=4444, debug=False, use_reloader=False)
