import json
import sys
import tempfile
from pathlib import Path

from .store import Rejected, Store


def demo():
    with tempfile.TemporaryDirectory(prefix="maintenance-desk-") as temporary:
        path = Path(temporary) / "sandbox.sqlite"
        store = Store(path)
        job = store.submit("synthetic-period-001", 2)
        print("job:", json.dumps(job, sort_keys=True))
        try:
            store.apply(job["id"])
        except Rejected as error:
            print("before approval:", error)
        store.approve(job["id"], job["digest"])
        store.close()
        store = Store(path)
        receipt = store.apply(job["id"])
        print("after restart:", json.dumps(receipt, sort_keys=True))
        print("duplicate returns same receipt:", store.apply(job["id"]) == receipt)
        print("final sandbox:", json.dumps(store.target(), sort_keys=True))
        store.close()


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        demo()
    else:
        from .cli import main
        main()
