"""Async code checking task — runs student code in isolation."""
import subprocess
import tempfile
import os
import time
from celery_app import celery


@celery.task(bind=True, max_retries=2, default_retry_delay=5)
def check_code_task(
    self,
    code: str,
    language: str = 'python3',
    test_input: str = '',
    expected_output: str = '',
    time_limit: int = 10,
):
    """Execute student code in a subprocess with resource limits.

    Returns dict with success, output, error, execution_time.
    """
    lang_config = {
        'python3': {'ext': '.py', 'cmd': ['python3']},
        'python': {'ext': '.py', 'cmd': ['python3']},
    }

    cfg = lang_config.get(language)
    if cfg is None:
        return {
            'success': False,
            'output': '',
            'error': f'Unsupported language: {language}',
            'execution_time': 0.0,
        }

    tmp_dir = tempfile.mkdtemp(prefix='boostudy_')
    src_path = os.path.join(tmp_dir, f'solution{cfg["ext"]}')

    try:
        with open(src_path, 'w', encoding='utf-8') as f:
            f.write(code)

        start = time.monotonic()
        result = subprocess.run(
            cfg['cmd'] + [src_path],
            input=test_input,
            capture_output=True,
            text=True,
            timeout=time_limit,
            cwd=tmp_dir,
            env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'},
        )
        elapsed = round(time.monotonic() - start, 3)

        stdout = result.stdout or ''
        stderr = result.stderr or ''

        if result.returncode != 0:
            return {
                'success': False,
                'output': stdout.strip(),
                'error': stderr.strip(),
                'execution_time': elapsed,
            }

        success = True
        if expected_output:
            success = stdout.strip() == expected_output.strip()

        return {
            'success': success,
            'output': stdout.strip(),
            'error': stderr.strip(),
            'execution_time': elapsed,
        }

    except subprocess.TimeoutExpired:
        return {
            'success': False,
            'output': '',
            'error': f'Time limit exceeded ({time_limit}s)',
            'execution_time': float(time_limit),
        }
    except MemoryError:
        return {
            'success': False,
            'output': '',
            'error': 'Memory limit exceeded',
            'execution_time': 0.0,
        }
    except Exception as exc:
        self.retry(exc=exc)
    finally:
        try:
            os.unlink(src_path)
            os.rmdir(tmp_dir)
        except OSError:
            pass
