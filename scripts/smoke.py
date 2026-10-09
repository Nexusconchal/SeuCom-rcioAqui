import sys
import time
import urllib.request

origin = sys.argv[1]
for attempt in range(30):
    try:
        with urllib.request.urlopen(origin + "/health", timeout=2) as result:
            assert result.status == 200
        with urllib.request.urlopen(origin + "/", timeout=2) as result:
            assert result.status == 200
            assert "SeuComércioAqui" in result.read().decode("utf-8")
        print("Container de produção respondendo.")
        break
    except (OSError, AssertionError):
        if attempt == 29:
            raise
        time.sleep(1)
