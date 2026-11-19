# .env first: config.py reads EWS_DATASET at import, and the Claude client reads
# ANTHROPIC_API_KEY - both must see the file before anything else in ews loads.
from . import envfile

envfile.load()
