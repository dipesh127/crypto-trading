import json, hashlib, subprocess
from .pipeline import FEATURE_CODE_VERSION, schema_hash

def code_fingerprint(package_dir):
    h=hashlib.sha256()
    for p in sorted(package_dir.rglob('*.py')):
        h.update(p.read_bytes())
    return h.hexdigest()

def checkpoint_metadata(feature_columns, package_dir, scaler_state=None):
    return {'feature_code_version':FEATURE_CODE_VERSION,'feature_code_sha256':code_fingerprint(package_dir),'schema_hash':schema_hash(feature_columns),'feature_columns':list(feature_columns),'scaler':scaler_state}

def save_metadata(path, metadata):
    with open(path,'w',encoding='utf-8') as f: json.dump(metadata,f,indent=2,sort_keys=True)


def save_regime_state(path, classifier):
    from pathlib import Path
    import pickle
    if classifier.model is None:
        raise RuntimeError('cannot persist an unfitted regime classifier')
    p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('wb') as f: pickle.dump(classifier.state_dict(),f,protocol=pickle.HIGHEST_PROTOCOL)
    return p

def load_regime_state(path):
    from pathlib import Path
    import pickle
    from .regime import MarketRegimeClassifier
    with Path(path).open('rb') as f: state=pickle.load(f)
    clf=MarketRegimeClassifier(n_regimes=state['n_regimes'],method=state['method'],random_state=state.get('random_state',42))
    clf.columns=state['columns']; clf.label_map={int(k):int(v) for k,v in state.get('label_map',{}).items()}; clf.model=state['model']
    return clf


def validate_checkpoint_runtime(metadata, feature_columns, package_dir=None):
    from pathlib import Path
    package_dir=Path(package_dir or 'app/features')
    expected=schema_hash(feature_columns)
    if metadata.get('schema_hash') and metadata['schema_hash'] != expected:
        raise RuntimeError('checkpoint feature schema does not match requested inference features')
    runtime=code_fingerprint(package_dir)
    if metadata.get('feature_code_sha256') and metadata['feature_code_sha256'] != runtime:
        raise RuntimeError('checkpoint feature code fingerprint does not match runtime package')
    scaler=metadata.get('scaler')
    if not scaler or scaler.get('columns') is None or scaler.get('params') is None:
        raise RuntimeError('checkpoint is missing a persisted training-fitted scaler')
    if not set(feature_columns).issubset(set(scaler['columns'])):
        raise RuntimeError('checkpoint scaler does not cover all inference features')
    return True
