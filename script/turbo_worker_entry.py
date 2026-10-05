import sys

# Source-only frozen dependencies live inside the verified payload. Python
# caches there would change its inventory and prevent the next startup.
sys.dont_write_bytecode = True

from piper.turbo_worker.main import main
raise SystemExit(main())
