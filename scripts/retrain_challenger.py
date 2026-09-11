#!/usr/bin/env python3
import argparse, asyncio
from app.governance.challenger import ChallengerPipeline
p=argparse.ArgumentParser(description='Run retraining into challenger/shadow; never promotes')
p.add_argument('--command',required=True); p.add_argument('--trigger',required=True)
a=p.parse_args(); ok=asyncio.run(ChallengerPipeline().run(a.command,a.trigger)); raise SystemExit(0 if ok else 1)
