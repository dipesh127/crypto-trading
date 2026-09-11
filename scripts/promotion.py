#!/usr/bin/env python3
import argparse
from app.rl.promotion import ChampionRegistry

p=argparse.ArgumentParser(description="Human-governed champion/challenger workflow")
p.add_argument('command',choices=['status','register','promote','rollback'])
p.add_argument('--root',default='artifacts/models')
p.add_argument('--model'); p.add_argument('--metadata')
p.add_argument('--reviewer',default=''); p.add_argument('--human-signoff',action='store_true')
a=p.parse_args(); r=ChampionRegistry(a.root)
if a.command=='register':
    if not a.model or not a.metadata: raise SystemExit('--model and --metadata are required')
    print(r.register_challenger(a.model,a.metadata))
elif a.command=='promote':
    if not a.human_signoff or not a.reviewer.strip(): raise SystemExit('PROMOTION REQUIRES --human-signoff and --reviewer')
    print(r.promote_human(reviewer=a.reviewer))
elif a.command=='rollback':
    if not a.human_signoff or not a.reviewer.strip(): raise SystemExit('ROLLBACK REQUIRES --human-signoff and --reviewer')
    print(r.rollback_human(reviewer=a.reviewer))
else: print(r.status())
