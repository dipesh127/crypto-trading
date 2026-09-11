#!/usr/bin/env python3
import json
from pathlib import Path
from app.governance.capital import CapitalRampController
from app.governance.challenger import ChallengerPipeline
print(json.dumps({'capital_ramp':CapitalRampController().state.__dict__,'challenger':ChallengerPipeline().status().__dict__},indent=2))
