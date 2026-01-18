"# shop-backend" 

# Celery on Windows using Redis on Docker

# Terminal 2 - Celery worker (all queues)
celery -A backend worker -Q celery,customers,orders,payments,inventory --loglevel=info --pool=solo

# Terminal 3 - Celery Beat (for scheduled tasks)
celery -A backend beat --loglevel=info

celery -A backend worker --loglevel=info -Q orders -P solo

