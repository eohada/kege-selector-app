"""
Multiprocess Test Server for BooStudy OS Sprint 3.1.
Runs an authentic independent Flask-SocketIO worker in a separate OS process,
connected to a real TCP Redis message queue and PostgreSQL/SQLite DB.
"""
import argparse
import os
import sys

from werkzeug.serving import make_server


def run_worker():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--redis", type=str, required=True)
    parser.add_argument("--db", type=str, required=True)
    parser.add_argument("--channel", type=str, default="sprint3_1_mp_chan")
    args = parser.parse_args()

    os.environ["DATABASE_URL"] = args.db
    os.environ["REDIS_URL"] = args.redis
    os.environ["BOOSTUDY_SKIP_DATABASE_BOOTSTRAP"] = "1"
    os.environ["BOOSTUDY_BACKGROUND_WORKERS_ENABLED"] = "0"
    os.environ["FORCE_SOCKETIO_MESSAGE_QUEUE"] = "1"
    os.environ["SOCKETIO_CHANNEL"] = args.channel

    from app import create_app, db
    from app.lessons.lesson_socket import register_lesson_socket
    from flask import jsonify, request, session
    from flask_socketio import SocketIO

    app = create_app({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": args.db,
        "REDIS_URL": args.redis,
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "sprint3_1_multiprocess_secret",
    })

    # Register SocketIO with message queue
    sio = SocketIO(
        app,
        message_queue=args.redis,
        channel=args.channel,
        async_mode="threading",
        cors_allowed_origins="*",
    )
    register_lesson_socket(sio, app=app)
    app.socketio = sio

    @app.route("/health")
    def health():
        return jsonify({"status": "ok", "port": args.port})

    @app.route("/api/internal/auth_session", methods=["POST"])
    def auth_session():
        if not app.config.get("TESTING"):
            return jsonify({"error": "forbidden", "message": "Test auth endpoint is only available in TESTING mode"}), 403
        import traceback
        try:
            from flask_login import login_user
            from app.models import User
            data = request.get_json(force=True) or {}
            user_id = data.get("user_id")
            user = db.session.get(User, user_id)
            if user:
                login_user(user)
                session["_user_id"] = str(user_id)
                session["sandbox_role"] = data.get("role", "student")
                return jsonify({"status": "authenticated", "user_id": user_id, "role": user.role})
            session["_user_id"] = str(user_id)
            session["sandbox_role"] = data.get("role", "student")
            return jsonify({"status": "authenticated_fallback", "user_id": user_id})
        except Exception as exc:
            traceback.print_exc()
            return jsonify({"error": str(exc), "trace": traceback.format_exc()}), 500

    # Run Werkzeug threaded server
    server = make_server("127.0.0.1", args.port, app.wsgi_app, threaded=True)
    print(f"WORKER_READY:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run_worker()
