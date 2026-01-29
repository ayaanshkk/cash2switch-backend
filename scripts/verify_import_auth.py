import importlib
import traceback

try:
    importlib.import_module('backend.routes.auth_routes')
    print('IMPORT_OK')
except Exception:
    traceback.print_exc()
    raise
