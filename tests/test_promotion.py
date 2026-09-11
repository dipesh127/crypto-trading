from pathlib import Path
from app.rl.promotion import ChampionRegistry

def test_promotion_rollback(tmp_path):
    r=ChampionRegistry(tmp_path/'models')
    r.register_challenger('c1.zip','c1.json'); r.promote(); r.register_challenger('c2.zip','c2.json'); r.promote(); x=r.rollback(); assert x['model']=='c1.zip'
