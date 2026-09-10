import importlib.util
import json
import os
from pathlib import Path
import unittest
import uuid

SPEC = importlib.util.spec_from_file_location(
    "redis_acl", Path(__file__).resolve().parents[1] / "redis-acl.py"
)
acl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(acl)


def credentials():
    return {
        name: str(index) * 96 for index, name in enumerate(acl.PRINCIPALS.values(), 1)
    } | {"REDIS_PASSWORD": "synthetic-admin-" * 4}


class ACLPlanTests(unittest.TestCase):
    def test_artifact_hashes_passwords_and_plan_is_repeatable(self):
        values = credentials()
        output = acl.render(values)
        for value in values.values():
            self.assertNotIn(value, output)
            self.assertNotIn(value, json.dumps(acl.plan(values)))
        self.assertEqual(acl.plan(values), acl.plan(values))

    def test_cache_and_broker_scopes_do_not_overlap(self):
        lines = acl.render(credentials()).splitlines()
        cache = next(row for row in lines if row.startswith("user kairos_cache "))
        self.assertIn("~kairos:cache:v2:*", cache)
        self.assertNotIn(" +evalsha", cache)
        self.assertNotIn(" &", cache)
        for row in lines[1:]:
            self.assertIn(" reset on #", row)
            self.assertNotIn(" +@all", row)
            for denied in (
                "+config",
                "+acl",
                "+flushall",
                "+flushdb",
                "+keys",
                "+scan",
                "+migrate",
                "+module",
                "+debug",
            ):
                self.assertNotIn(denied, row)
        for row in lines[2:]:
            self.assertIn("~kairos:broker:v1:*", row)
            self.assertIn("&kairos:broker:v1:*", row)
            self.assertNotIn("cache:v2", row)

    def test_shared_or_malformed_credentials_rejected(self):
        for change in (
            {"KAIROS_REDIS_CACHE_PASSWORD": "2" * 96},
            {"KAIROS_REDIS_CACHE_PASSWORD": "short"},
            {"REDIS_PASSWORD": "short"},
        ):
            with self.subTest(change=list(change)), self.assertRaises(ValueError):
                acl.render(credentials() | change)

    def test_changed_plan_refuses_write(self):
        with self.assertRaisesRegex(ValueError, "plan_changed"):
            acl.write_artifact("/should/not/be/written", credentials(), "different")


@unittest.skipUnless(
    os.environ.get("KAIROS_TEST_REDIS_ACL") == "1",
    "dedicated disposable Redis ACL fixture required",
)
class IsolatedRedisACLTests(unittest.TestCase):
    """Never configures users: root starts a dedicated Redis with rendered test ACL."""

    def setUp(self):
        import redis

        host = os.environ.get("KAIROS_TEST_REDIS_ACL_HOST", "")
        port = int(os.environ["KAIROS_TEST_REDIS_ACL_PORT"])
        if not (host in {"127.0.0.1", "localhost"} or host.startswith("kairos-test-")):
            self.fail("Explicit isolated Redis fixture hostname required")
        self.redis = redis
        self.values = credentials()
        self.clients = {
            user: redis.Redis(
                host=host,
                port=port,
                username=user,
                password=self.values[key],
                socket_timeout=3,
            )
            for user, key in acl.PRINCIPALS.items()
        }
        self.nonce = uuid.uuid4().hex
        self.addCleanup(lambda: [client.close() for client in self.clients.values()])

    def test_service_accounts_cannot_reset_cache_nonces_or_read_privileged_values(self):
        key = acl.CACHE_PREFIX + "1:kairos:mcp:used:" + self.nonce
        cache = self.clients["kairos_cache"]
        self.assertTrue(cache.set(key, b"j:true", nx=True, ex=120))
        for user, broker in self.clients.items():
            if user == "kairos_cache":
                continue
            for operation in (
                lambda: broker.get(key),
                lambda: broker.delete(key),
                lambda: broker.set(key, b"0"),
                lambda: broker.execute_command("FLUSHDB"),
                lambda: broker.execute_command("ACL", "LIST"),
                lambda: broker.execute_command("CONFIG", "GET", "*"),
            ):
                with self.assertRaises(self.redis.exceptions.ResponseError):
                    operation()
            own = acl.BROKER_PREFIX + self.nonce + user
            self.assertTrue(broker.set(own, b"task", ex=120))
            self.assertEqual(broker.get(own), b"task")
            with self.assertRaises(self.redis.exceptions.ResponseError):
                cache.get(own)
            with self.assertRaises(self.redis.exceptions.ResponseError):
                broker.publish(acl.CACHE_PREFIX + "signal", "bad")
        self.assertIsNone(cache.set(key, b"j:true", nx=True, ex=120))
        self.assertEqual(cache.get(key), b"j:true")

    def test_lua_cannot_bypass_key_acl(self):
        broker = self.clients["kairos_worker_broker"]
        digest = broker.script_load("return redis.call('GET', ARGV[1])")
        with self.assertRaises(self.redis.exceptions.ResponseError):
            broker.evalsha(digest, 0, acl.CACHE_PREFIX + "1:protected")

    def test_cache_atomic_increment_and_json_types(self):
        cache = self.clients["kairos_cache"]
        key = acl.CACHE_PREFIX + "1:counter:" + self.nonce
        self.assertTrue(cache.set(key, 0, nx=True, ex=120))
        self.assertEqual(cache.incr(key), 1)
        self.assertEqual(cache.get(key), b"1")

    def test_real_kombu_publish_consume_and_ack_use_broker_namespace(self):
        from kombu import Connection
        from urllib.parse import quote

        def connection(user):
            options = self.clients[user].connection_pool.connection_kwargs
            return Connection(
                "redis://"
                + user
                + ":"
                + quote(self.values[acl.PRINCIPALS[user]], safe="")
                + "@"
                + options["host"]
                + ":"
                + str(options["port"])
                + "/0",
                transport_options={"global_keyprefix": acl.BROKER_PREFIX},
            )

        name = "kairos-test-" + self.nonce
        with connection("kairos_api_broker") as producer:
            with producer.SimpleQueue(name) as queue:
                queue.put({"event": "synthetic"}, serializer="json")
        with connection("kairos_worker_broker") as consumer:
            with consumer.SimpleQueue(name) as queue:
                message = queue.get(block=True, timeout=3)
                self.assertEqual(message.payload, {"event": "synthetic"})
                message.ack()


if __name__ == "__main__":
    unittest.main()
