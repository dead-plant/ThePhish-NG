"""Minimal in-memory stand-in for the redis-py client used by the tests.

Implements only the commands the analysis service uses (hashes, lists,
expiry, pub/sub and pipelines). Failures can be simulated per command by
adding the command name to fail_on.
"""

import redis


class FakePubSub:
    def __init__(self, server: "FakeRedis") -> None:
        self._server = server
        self.messages: list[dict] = []
        self.channels: set[str] = set()
        self.closed = False

    def subscribe(self, *channels: str) -> None:
        self._server.maybe_fail("subscribe")
        self.channels.update(channels)

    def get_message(self, ignore_subscribe_messages: bool = False, timeout: float | None = None) -> dict | None:
        self._server.maybe_fail("get_message")
        if self.messages:
            return self.messages.pop(0)
        return None

    def close(self) -> None:
        self.closed = True
        if self in self._server.pubsubs:
            self._server.pubsubs.remove(self)


class FakePipeline:
    def __init__(self, server: "FakeRedis") -> None:
        self._server = server
        self._commands: list[tuple] = []

    def hset(self, key, mapping):
        self._commands.append(("hset", (key,), {"mapping": mapping}))
        return self

    def hgetall(self, key):
        self._commands.append(("hgetall", (key,), {}))
        return self

    def rpush(self, key, *values):
        self._commands.append(("rpush", (key, *values), {}))
        return self

    def expire(self, key, seconds):
        self._commands.append(("expire", (key, seconds), {}))
        return self

    def execute(self):
        return [getattr(self._server, name)(*args, **kwargs) for name, args, kwargs in self._commands]


class FakeRedis:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}
        self.lists: dict[str, list[str]] = {}
        self.expirations: dict[str, int] = {}
        self.pubsubs: list[FakePubSub] = []
        self.published: list[tuple[str, str]] = []
        self.fail_on: set[str] = set()
        self.mute_publish = False

    def maybe_fail(self, command: str) -> None:
        if command in self.fail_on:
            raise redis.ConnectionError(f"simulated failure of {command}")

    def hset(self, key, mapping):
        self.maybe_fail("hset")
        self.hashes.setdefault(key, {}).update({field: str(value) for field, value in mapping.items()})
        return len(mapping)

    def hgetall(self, key):
        self.maybe_fail("hgetall")
        return dict(self.hashes.get(key, {}))

    def rpush(self, key, *values):
        self.maybe_fail("rpush")
        entries = self.lists.setdefault(key, [])
        entries.extend(str(value) for value in values)
        return len(entries)

    def lrange(self, key, start, end):
        self.maybe_fail("lrange")
        values = self.lists.get(key, [])
        if end < 0:
            end = len(values) + end
        return list(values[start:end + 1])

    def expire(self, key, seconds):
        self.maybe_fail("expire")
        self.expirations[key] = seconds
        return True

    def publish(self, channel, data):
        self.maybe_fail("publish")
        self.published.append((channel, data))
        if self.mute_publish:
            return 0
        receivers = 0
        for pubsub in self.pubsubs:
            if channel in pubsub.channels:
                pubsub.messages.append({"type": "message", "channel": channel, "data": data})
                receivers += 1
        return receivers

    def pipeline(self):
        self.maybe_fail("pipeline")
        return FakePipeline(self)

    def pubsub(self, ignore_subscribe_messages: bool = False):
        pubsub = FakePubSub(self)
        self.pubsubs.append(pubsub)
        return pubsub
