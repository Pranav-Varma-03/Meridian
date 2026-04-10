import sys
import types

if "pinecone" not in sys.modules:
    pinecone_stub = types.ModuleType("pinecone")

    class _DummyPinecone:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    pinecone_stub.Pinecone = _DummyPinecone
    sys.modules["pinecone"] = pinecone_stub
