"""Resource-limited bytes-only format parser process."""

import base64
import json
import sys


def main():
    try:
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
        resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
        request = json.loads(sys.stdin.buffer.read(2 * 1024 * 1024))
        from .binary_formats import process

        result = process(
            base64.b64decode(request["content"], validate=True),
            selection=request["selection"],
            strip=request["strip"],
        )
        result["status"] = "ok"
    except ImportError:
        result = {"status": "unsupported", "reason": "missing_format_dependency"}
    except Exception as error:  # noqa: BLE001 -- untrusted parser boundary emits no exception text
        from .binary_formats import FormatFault

        result = {
            "status": "unknown",
            "reason": str(error)
            if isinstance(error, FormatFault)
            else "malformed_container",
        }
    sys.stdout.write(json.dumps(result, ensure_ascii=True))


if __name__ == "__main__":
    main()
