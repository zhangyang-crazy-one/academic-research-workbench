"""Deliberately weak CPU pilot control using only the public eight-row mean."""

import itertools
import json
import sys

with open(sys.argv[1], encoding="utf-8") as stream:
    task = json.load(stream)
mean = sum(row["value"] for row in task["observations"]) / len(task["observations"])
print(
    json.dumps(
        {
            "selected_config": "0000",
            "responses": [
                {"config": "".join(bits), "value": mean}
                for bits in itertools.product("01", repeat=4)
            ],
        }
    )
)
