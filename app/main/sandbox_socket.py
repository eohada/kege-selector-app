from __future__ import annotations
import logging
from flask import request
from flask_socketio import emit, join_room
from typing import Any

logger = logging.getLogger(__name__)

_sandbox_rooms = {}  # room_id -> { "sync_enabled": bool, "task_states": dict, "live_input": str, "current_task": int, "messages": list }

def register_sandbox_socket(socketio):
    """Регистрация сокет-событий для изолированной песочницы"""
    @socketio.on('connect', namespace='/sandbox')
    def on_connect():
        return True

    @socketio.on('join', namespace='/sandbox')
    def on_join(data):
        room_id = (data.get('room_id') or '').strip()
        if not room_id:
            return
        role = data.get('role', 'student')
        
        join_room(room_id)
        
        if room_id not in _sandbox_rooms:
            _sandbox_rooms[room_id] = {
                "sync_enabled": False,
                # 0: pending, 1: done, -1: error, 2: wait_review
                "task_states": {i: 0 for i in range(1, 11)},
                "live_input": "",
                "current_task": 4,
                "messages": []
            }
        
        # Отправляем полное начальное состояние комнаты
        emit('room_state', _sandbox_rooms[room_id], room=request.sid)
        logger.info(f"[Sandbox] Client {request.sid} ({role}) joined room {room_id}")

    @socketio.on('toggle_sync', namespace='/sandbox')
    def on_toggle_sync(data):
        room_id = data.get('room_id')
        is_synced = data.get('is_synced')
        if room_id in _sandbox_rooms:
            _sandbox_rooms[room_id]['sync_enabled'] = is_synced
            # Распространяем статус всем в комнате
            emit('sync_toggled', {'is_synced': is_synced}, room=room_id)

    @socketio.on('force_switch_tab', namespace='/sandbox')
    def on_switch_tab(data):
        room_id = data.get('room_id')
        tab_id = data.get('tab_id')
        if room_id in _sandbox_rooms and _sandbox_rooms[room_id]['sync_enabled']:
            # Внимание: include_self=False, чтобы препод не зациклил сам себя
            emit('switch_tab', {'tab_id': tab_id}, room=room_id, include_self=False)

    @socketio.on('student_input', namespace='/sandbox')
    def on_student_input(data):
        room_id = data.get('room_id')
        text = data.get('text')
        task_id = data.get('task_id')
        if room_id in _sandbox_rooms:
            _sandbox_rooms[room_id]['live_input'] = text
            emit('live_typing', {'text': text, 'task_id': task_id}, room=room_id, include_self=False)

    @socketio.on('submit_answer', namespace='/sandbox')
    def on_submit_answer(data):
        room_id = data.get('room_id')
        task_id = int(data.get('task_id', 0))
        text = data.get('text', '')
        if room_id in _sandbox_rooms:
            _sandbox_rooms[room_id]['task_states'][task_id] = 2 # 2 = Ожидает проверки
            _sandbox_rooms[room_id]['live_input'] = text
            emit('answer_submitted', {'task_id': task_id, 'text': text}, room=room_id)

    @socketio.on('send_message', namespace='/sandbox')
    def on_send_message(data):
        room_id = data.get('room_id')
        sender = data.get('sender', 'unknown')
        text = data.get('text', '')
        
        msg = {'sender': sender, 'text': text}
        if room_id in _sandbox_rooms:
            _sandbox_rooms[room_id]['messages'].append(msg)
            # Отправка ВО ВСЮ КОМНАТУ
            emit('new_message', msg, room=room_id)

    @socketio.on('change_task', namespace='/sandbox')
    def on_change_task(data):
        room_id = data.get('room_id')
        task_id = int(data.get('task_id'))
        
        if room_id in _sandbox_rooms:
            _sandbox_rooms[room_id]['current_task'] = task_id
            _sandbox_rooms[room_id]['live_input'] = "" # Очистка инпута при смене задачи
            emit('task_changed', {'task_id': task_id}, room=room_id)

    @socketio.on('evaluate_task', namespace='/sandbox')
    def on_evaluate_task(data):
        room_id = data.get('room_id')
        task_id = int(data.get('task_id'))
        status = data.get('status')
        
        if room_id in _sandbox_rooms:
            numeric_status = 1 if status == 'approve' else -1
            _sandbox_rooms[room_id]['task_states'][task_id] = numeric_status
            
            next_task = None
            if numeric_status == 1:
                # Ищем следующую
                for i in range(task_id + 1, 11):
                    if _sandbox_rooms[room_id]['task_states'][i] == 0:
                        next_task = i
                        _sandbox_rooms[room_id]['current_task'] = next_task
                        break
            
            _sandbox_rooms[room_id]['live_input'] = ""
            emit('task_evaluated', {
                'task_id': task_id, 
                'status': numeric_status,
                'next_task': next_task
            }, room=room_id)

    # --- Доска: Синхронизация холста ---
    @socketio.on('draw_event', namespace='/sandbox')
    def on_draw_event(data):
        room_id = data.get('room_id')
        if room_id in _sandbox_rooms:
            emit('draw_event', data, room=room_id, include_self=False)

    @socketio.on('clear_whiteboard', namespace='/sandbox')
    def on_clear_whiteboard(data):
        room_id = data.get('room_id')
        if room_id in _sandbox_rooms:
            emit('clear_whiteboard', {}, room=room_id, include_self=False)
