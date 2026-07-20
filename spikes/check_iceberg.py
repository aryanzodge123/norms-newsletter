# spikes/check_iceberg.py
import os
import pyarrow as pa
from dotenv import load_dotenv
from pyiceberg.catalog import load_catalog

load_dotenv()
catalog = load_catalog(
    "r2",
    **{
        "type": "rest",
        "uri": os.environ["R2_CATALOG_URI"],
        "warehouse": os.environ["R2_WAREHOUSE"],
        "token": os.environ["R2_TOKEN"],
    },
)
catalog.create_namespace_if_not_exists("spike")
table = catalog.create_table_if_not_exists(
    "spike.hello",
    schema=pa.schema([("id", pa.int64()), ("msg", pa.string())]),
)
table.append(pa.table({"id": [1], "msg": ["norm was here"]}))
print(table.scan().to_arrow().to_pydict())