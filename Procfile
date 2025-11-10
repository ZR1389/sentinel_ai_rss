web: gunicorn main:app --bind 0.0.0.0:8080 --timeout 300 --worker-class gevent --worker-connections 100
worker: python3 scheduler.py
notify: python3 scheduler_notify.py