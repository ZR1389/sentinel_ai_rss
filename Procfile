web: gunicorn main:app --bind 0.0.0.0:8080 --timeout 120 --worker-class gevent --worker-connections 100
health: python health_server.py
worker: python3 scheduler.py
notify: python3 scheduler_notify.py