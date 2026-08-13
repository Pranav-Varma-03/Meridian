import os
import sys
import types

# Test collection imports application modules before individual tests can
# monkeypatch Settings. Keep the suite independent of a developer's local
# telemetry configuration (for example, OBSERVABILITY_ENABLED=true in .env).
os.environ["OBSERVABILITY_ENABLED"] = "false"
# Router unit tests use an in-process ASGI client without Redis. Keep that
# isolated contract suite independent of a developer's production-safe local
# default, while dedicated rate-limit tests cover the fail-closed Redis path.
os.environ["RATE_LIMIT_ENABLED"] = "false"

if "pinecone" not in sys.modules:
    pinecone_stub = types.ModuleType("pinecone")

    class _DummyPinecone:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    pinecone_stub.Pinecone = _DummyPinecone
    sys.modules["pinecone"] = pinecone_stub
