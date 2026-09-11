from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import asyncio, json, shlex

@dataclass
class ChallengerState:
    status: str="IDLE"
    last_trigger: str=""
    last_run_at: str=""
    last_command: str=""
    last_exit_code: int|None=None
    artifact: str=""
    requires_human_promotion: bool=True

class ChallengerPipeline:
    """Runs retraining into challenger/shadow only. It can never promote to live automatically."""
    def __init__(self, state_path="artifacts/models/challenger_pipeline.json"):
        self.path=Path(state_path); self.path.parent.mkdir(parents=True,exist_ok=True); self.state=self._load()
    def _load(self):
        return ChallengerState(**json.loads(self.path.read_text())) if self.path.exists() else ChallengerState()
    def _save(self): self.path.write_text(json.dumps(asdict(self.state),indent=2,sort_keys=True))
    async def run(self, command:str, trigger:str):
        if self.state.status=="RUNNING": return False
        if self.state.last_trigger == trigger and self.state.status == "READY_FOR_REVIEW": return False
        self.state.status="RUNNING"; self.state.last_trigger=trigger; self.state.last_run_at=datetime.now(timezone.utc).isoformat(); self.state.last_command=command; self._save()
        try:
            proc=await asyncio.create_subprocess_exec(*shlex.split(command),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.STDOUT)
            out,_=await proc.communicate(); self.state.last_exit_code=proc.returncode
            self.state.status="READY_FOR_REVIEW" if proc.returncode==0 else "FAILED"
            self.state.artifact=out.decode(errors="replace")[-4000:]
            self._save(); return proc.returncode==0
        except Exception as exc:
            self.state.status="FAILED"; self.state.artifact=str(exc); self._save(); return False
    def status(self): return self.state
