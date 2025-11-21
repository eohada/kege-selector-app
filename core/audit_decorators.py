
from functools import wraps
from flask import request, g
import time

from .audit_logger import audit_logger

def log_action(action: str, entity: str = None, get_entity_id=None):

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            start_time = time.time()
            status = 'success'
            entity_id = None
            error = None

            try:
                response = f(*args, **kwargs)

                if get_entity_id and hasattr(response, 'get_json'):
                    try:
                        json_data = response.get_json()
                        if json_data:
                            entity_id = get_entity_id(json_data)
                    except:
                        pass

                if hasattr(response, 'status_code'):
                    if response.status_code >= 400:
                        status = 'error'
                    elif response.status_code >= 300:
                        status = 'warning'

                duration_ms = int((time.time() - start_time) * 1000)

                audit_logger.log(
                    action=action,
                    entity=entity,
                    entity_id=entity_id,
                    status=status,
                    metadata={
                        'route': request.endpoint,
                        'method': request.method,
                        'status_code': response.status_code if hasattr(response, 'status_code') else None
                    },
                    duration_ms=duration_ms
                )

                return response
            except Exception as e:
                duration_ms = int((time.time() - start_time) * 1000)
                error = str(e)

                audit_logger.log_error(
                    action=action,
                    entity=entity,
                    error=error,
                    metadata={
                        'route': request.endpoint,
                        'method': request.method
                    }
                )

                raise

        return decorated_function
    return decorator
