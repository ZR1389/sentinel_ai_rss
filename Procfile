web: uvicorn health_check:app --host 0.0.0.0 --port $PORT
health: python health_server.py
worker: python3 scheduler.py
notify: python3 scheduler_notify.py