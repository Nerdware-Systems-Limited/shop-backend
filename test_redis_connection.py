import os
import django
from dotenv import load_dotenv

load_dotenv()
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

import redis
from django.conf import settings

print("=" * 60)
print("Celery Queue Inspection")
print("=" * 60)

broker_url = settings.CELERY_BROKER_URL
print(f"\nBroker: {broker_url}")

try:
    r = redis.from_url(broker_url, decode_responses=False)
    r.ping()
    print("✅ Connected to Redis")
    
    # Check the celery queue
    queue_length = r.llen('celery')
    print(f"\n📊 Tasks in 'celery' queue: {queue_length}")
    
    if queue_length > 0:
        print("\n📋 Tasks waiting in queue:")
        tasks = r.lrange('celery', 0, -1)
        for i, task in enumerate(tasks, 1):
            print(f"  {i}. {task[:100]}...")
    
    # Check all celery-related keys
    print("\n🔍 All Celery keys in Redis:")
    keys = r.keys('celery*')
    for key in keys:
        if isinstance(key, bytes):
            key = key.decode('utf-8')
        print(f"  - {key}")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()

print("=" * 60)