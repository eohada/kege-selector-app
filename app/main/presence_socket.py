"""Socket.IO namespace /presence — подписка на live-обновления статуса конкретного пользователя.

Клиент отправляет: emit('watch', {user_id: 42})   → подписывается на комнату presence:42
Клиент отправляет: emit('unwatch', {user_id: 42}) → отписывается

Сервер шлёт в комнату presence:<user_id>:
    presence_update  { user_id, online, activity }

Событие presence_update отправляется из presence_ping (app/main/routes.py) каждый раз,
когда пользователь 42 шлёт heartbeat.
"""

import logging

logger = logging.getLogger(__name__)


def register_presence_socket(socketio) -> None:
    from flask import request
    from flask_login import current_user
    from flask_socketio import join_room, leave_room

    @socketio.on('connect', namespace='/presence')
    def _on_connect():
        if not getattr(current_user, 'is_authenticated', False):
            return False
        return True

    @socketio.on('disconnect', namespace='/presence')
    def _on_disconnect():
        pass

    @socketio.on('watch', namespace='/presence')
    def _on_watch(data):
        """Подписаться на обновления присутствия пользователя user_id."""
        if not getattr(current_user, 'is_authenticated', False):
            return
        try:
            user_id = int(data.get('user_id', 0))
            if user_id > 0:
                join_room(f'presence:{user_id}')
        except Exception as exc:
            logger.debug('presence watch error: %s', exc)

    @socketio.on('unwatch', namespace='/presence')
    def _on_unwatch(data):
        """Отписаться от обновлений присутствия пользователя user_id."""
        if not getattr(current_user, 'is_authenticated', False):
            return
        try:
            user_id = int(data.get('user_id', 0))
            if user_id > 0:
                leave_room(f'presence:{user_id}')
        except Exception as exc:
            logger.debug('presence unwatch error: %s', exc)
