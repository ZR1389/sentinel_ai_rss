web: exec uvicorn railway_health:app --host 0.0.0.0 --port $PORT --log-level info
health: python health_server.py
worker: python3 scheduler.py
notify: python3 scheduler_notify.py