import unittest
from datetime import datetime, timedelta, timezone

from app.services.product_sync_service import ProductSyncManager


class FakePipeline:
    def __init__(self, redis):
        self.redis = redis
        self.commands = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def set(self, key, value, ex=None):
        self.commands.append(("set", key, value, ex))
        return self

    def lpush(self, key, value):
        self.commands.append(("lpush", key, value))
        return self

    def execute(self):
        for command in self.commands:
            if command[0] == "set":
                _, key, value, ex = command
                self.redis.set(key, value, ex=ex)
            elif command[0] == "lpush":
                _, key, value = command
                self.redis.lpush(key, value)
        return [True] * len(self.commands)


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.lists = {}

    def set(self, key, value, ex=None):
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def lpush(self, key, value):
        self.lists.setdefault(key, []).insert(0, value)
        return len(self.lists[key])

    def brpoplpush(self, source, destination, timeout=0):
        values = self.lists.get(source, [])
        if not values:
            return None
        value = values.pop()
        self.lpush(destination, value)
        return value

    def lrem(self, key, count, value):
        values = self.lists.get(key, [])
        original_length = len(values)
        self.lists[key] = [item for item in values if item != value]
        return original_length - len(self.lists[key])

    def lrange(self, key, start, end):
        values = self.lists.get(key, [])
        if end == -1:
            return list(values[start:])
        return list(values[start:end + 1])

    def pipeline(self):
        return FakePipeline(self)


class ProductSyncJobStoreTests(unittest.TestCase):
    def test_job_is_visible_to_another_process_manager(self) -> None:
        redis = FakeRedis()
        api_manager = ProductSyncManager(redis)
        worker_manager = ProductSyncManager(redis)
        job = api_manager.create([" fe04 ", "FE04", "tm32"])

        stored = worker_manager.get(job.id)

        self.assertIsNotNone(stored)
        self.assertEqual(stored["skus"], ["FE04", "TM32"])
        self.assertEqual(worker_manager.claim_next(), job.id)
        self.assertEqual(api_manager.get(job.id)["status"], "claimed")
        self.assertEqual(redis.lists[worker_manager.processing_key], [job.id])
        worker_manager.acknowledge(job.id)
        self.assertEqual(redis.lists[worker_manager.processing_key], [])
        self.assertIsNone(worker_manager.claim_next())

    def test_queue_keeps_fifo_order(self) -> None:
        redis = FakeRedis()
        manager = ProductSyncManager(redis)
        first = manager.create(["FE04"])
        second = manager.create(["TM32"])

        self.assertEqual(manager.claim_next(), first.id)
        manager.acknowledge(first.id)
        self.assertEqual(manager.claim_next(), second.id)

    def test_stale_job_is_requeued(self) -> None:
        redis = FakeRedis()
        manager = ProductSyncManager(redis)
        manager.stale_seconds = 10
        job = manager.create(["FE04"])
        self.assertEqual(manager.claim_next(), job.id)

        stored = manager._load(job.id)
        stored.heartbeat_at = (
            datetime.now(timezone.utc) - timedelta(seconds=20)
        ).isoformat()
        manager._save(stored)

        self.assertEqual(manager.recover_stale_jobs(), 1)
        recovered = manager.get(job.id)
        self.assertEqual(recovered["status"], "queued")
        self.assertEqual(manager.claim_next(), job.id)
        self.assertEqual(manager.get(job.id)["attempts"], 2)

    def test_stale_job_fails_after_max_attempts(self) -> None:
        redis = FakeRedis()
        manager = ProductSyncManager(redis)
        manager.stale_seconds = 10
        manager.max_attempts = 1
        job = manager.create(["FE04"])
        self.assertEqual(manager.claim_next(), job.id)

        stored = manager._load(job.id)
        stored.heartbeat_at = (
            datetime.now(timezone.utc) - timedelta(seconds=20)
        ).isoformat()
        manager._save(stored)

        self.assertEqual(manager.recover_stale_jobs(), 0)
        failed = manager.get(job.id)
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(redis.lists[manager.processing_key], [])

    def test_queued_job_can_be_cancelled(self) -> None:
        redis = FakeRedis()
        manager = ProductSyncManager(redis)
        job = manager.create(["FE04"])

        cancelled = manager.cancel(job.id)

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(redis.lists[manager.queue_key], [])
        self.assertIsNone(manager.claim_next())

    def test_claimed_job_receives_cancel_request(self) -> None:
        redis = FakeRedis()
        manager = ProductSyncManager(redis)
        job = manager.create(["FE04"])
        self.assertEqual(manager.claim_next(), job.id)

        cancelling = manager.cancel(job.id)

        self.assertEqual(cancelling["status"], "cancel_requested")
        self.assertTrue(manager._finish_cancelled(job.id))
        self.assertEqual(manager.get(job.id)["status"], "cancelled")

    def test_admin_sync_can_create_job_above_import_limit(self) -> None:
        redis = FakeRedis()
        manager = ProductSyncManager(redis)
        codes = [f"SKU{index:04d}" for index in range(1001)]

        with self.assertRaisesRegex(ValueError, "1.000"):
            manager.create(codes)

        job = manager.create(codes, max_skus=None)
        self.assertEqual(len(job.skus), 1001)


if __name__ == "__main__":
    unittest.main()
