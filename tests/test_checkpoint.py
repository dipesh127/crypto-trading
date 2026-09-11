from pathlib import Path
from app.features.checkpoint import checkpoint_metadata

def test_checkpoint_metadata_has_pinning_fields():
    m=checkpoint_metadata(['a','b'],Path('app/features')); assert m['feature_code_version']; assert len(m['feature_code_sha256'])==64; assert len(m['schema_hash'])==64
