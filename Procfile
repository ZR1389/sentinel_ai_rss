web: gunicorn main:app --bind 0.0.0.0:$PORT --timeout 300 --workers 2
health: python health_server.py
worker: python3 scheduler.py
notify: python3 scheduler_notify.py