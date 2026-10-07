import sys

# The verified worker inventory must remain unchanged after its first launch.
sys.dont_write_bytecode = True

from piper.chatterbox_worker.main import main

raise SystemExit(main())
