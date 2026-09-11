from __future__ import annotations
import os, json, logging
import aiohttp
log=logging.getLogger(__name__)

class AlertDispatcher:
    """Optional Telegram/Discord webhook notifier. No network calls occur when unconfigured."""
    def __init__(self,telegram_token='',telegram_chat_id='',discord_webhook=''):
        self.telegram_token=telegram_token; self.telegram_chat_id=telegram_chat_id; self.discord_webhook=discord_webhook
    @classmethod
    def from_env(cls):
        return cls(os.getenv('TELEGRAM_BOT_TOKEN',''),os.getenv('TELEGRAM_CHAT_ID',''),os.getenv('DISCORD_WEBHOOK_URL',''))
    @property
    def enabled(self): return bool((self.telegram_token and self.telegram_chat_id) or self.discord_webhook)
    async def send(self,message):
        if not self.enabled: return []
        results=[]
        timeout=aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            if self.telegram_token and self.telegram_chat_id:
                url=f'https://api.telegram.org/bot{self.telegram_token}/sendMessage'
                async with session.post(url,json={'chat_id':self.telegram_chat_id,'text':message}) as r: results.append(('telegram',r.status))
            if self.discord_webhook:
                async with session.post(self.discord_webhook,json={'content':message}) as r: results.append(('discord',r.status))
        return results
    async def risk(self,mode,decision,metrics=None):
        if decision.allowed and not decision.reasons: return
        await self.send(f'[{mode}] RISK {"PAUSED" if not decision.allowed else "FLAGGED"}: {", ".join(decision.reasons) or "none"} metrics={json.dumps(metrics or {},default=str)}')
    async def reconciliation(self,mode,result):
        if not result.get('ok',False): await self.send(f'[{mode}] RECONCILIATION MISMATCH: {json.dumps(result,default=str)}')
    async def exchange(self,mode,event,message): await self.send(f'[{mode}] {event}: {message}')
