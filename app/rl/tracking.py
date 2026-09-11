from __future__ import annotations
import json
from pathlib import Path
try: import mlflow
except ImportError: mlflow=None

def _flat_metrics(metrics):
    out={}
    for k,v in metrics.items():
        if isinstance(v,(int,float)) and v == v: out[k]=float(v)
    return out

def log_run(params, metrics, artifacts=None, run_name=None, tags=None):
    """Log a complete run; falls back to a portable JSON manifest without MLflow installed."""
    if mlflow is None:
        p=Path(artifacts or 'artifacts'); p.mkdir(parents=True,exist_ok=True)
        (p/'run.json').write_text(json.dumps({'run_name':run_name,'params':params,'metrics':metrics,'tags':tags or {}},indent=2,default=str))
        return None
    with mlflow.start_run(run_name=run_name) as run:
        mlflow.log_params({k:v for k,v in params.items() if isinstance(v,(str,int,float,bool))})
        m=_flat_metrics(metrics); 
        if m: mlflow.log_metrics(m)
        if tags: mlflow.set_tags({k:str(v) for k,v in tags.items()})
        if artifacts:
            root=Path(artifacts)
            if root.exists():
                for f in root.rglob('*'):
                    if f.is_file(): mlflow.log_artifact(str(f), artifact_path=str(f.parent.relative_to(root)) if f.parent!=root else None)
        return run.info.run_id
