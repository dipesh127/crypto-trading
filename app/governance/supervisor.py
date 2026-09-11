from __future__ import annotations
from dataclasses import dataclass
import asyncio, logging, json, time
from pathlib import Path
from .challenger import ChallengerPipeline

log=logging.getLogger(__name__)
@dataclass(frozen=True)
class GovernanceConfig:
    health_interval_seconds: float=5.0
    retrain_check_interval_seconds: float=60.0
    retrain_command: str=""
    scheduled_retrain_hours: float=168.0
    retrain_on_flags: tuple[str,...]=("rolling_sharpe_decay","feature_psi_drift","feature_kl_drift")
    retrain_state_path: str="data/retrain_schedule.json"

class LiveGovernanceSupervisor:
    """Long-running production supervisor. Monitoring may pause trading; retraining only creates challengers."""
    def __init__(self, *, risk, execution, reconciler=None, config=None, challenger=None, on_pause=None):
        self.risk=risk; self.execution=execution; self.reconciler=reconciler; self.cfg=config or GovernanceConfig(); self.challenger=challenger or ChallengerPipeline(); self.on_pause=on_pause; self.stop_event=asyncio.Event()
        self.tasks=[]
    async def start(self):
        self.stop_event.clear(); self.tasks=[asyncio.create_task(self._monitor()),asyncio.create_task(self._retrain_watch())]
    async def stop(self):
        self.stop_event.set()
        for t in self.tasks: t.cancel()
        await asyncio.gather(*self.tasks,return_exceptions=True); self.tasks=[]
    async def _monitor(self):
        while not self.stop_event.is_set():
            if self.risk.paused:
                log.critical("LIVE GOVERNANCE PAUSE flags=%s",self.risk.flags)
                if self.on_pause:
                    result=self.on_pause(self.risk.flags)
                    if asyncio.iscoroutine(result): await result
            await asyncio.sleep(self.cfg.health_interval_seconds)
    async def _retrain_watch(self):
        state_path=Path(getattr(self.cfg,"retrain_state_path","data/retrain_schedule.json")); state_path.parent.mkdir(parents=True,exist_ok=True)
        try: last_scheduled=float(json.loads(state_path.read_text()).get("last_scheduled_epoch",0))
        except Exception: last_scheduled=0.0
        while not self.stop_event.is_set():
            now=time.time()
            if self.cfg.retrain_command and self.cfg.scheduled_retrain_hours > 0 and now-last_scheduled >= self.cfg.scheduled_retrain_hours*3600:
                await self.challenger.run(self.cfg.retrain_command, "scheduled")
                last_scheduled=now
                try: state_path.write_text(json.dumps({"last_scheduled_epoch":last_scheduled},indent=2))
                except Exception: pass
            if self.cfg.retrain_command and self.risk.paused:
                triggers=[x for x in self.risk.flags if x in self.cfg.retrain_on_flags]
                if triggers and self.challenger.status().status != "RUNNING":
                    await self.challenger.run(self.cfg.retrain_command, ",".join(triggers))
            await asyncio.sleep(self.cfg.retrain_check_interval_seconds)
