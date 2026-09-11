from __future__ import annotations
import torch
from torch import nn
try:
    from stable_baselines3.common.torch_layers import BaseFeaturesExtractor
except ImportError:
    class BaseFeaturesExtractor(nn.Module):
        def __init__(self, observation_space, features_dim): super().__init__(); self._features_dim=features_dim

class TemporalConvBlock(nn.Module):
    def __init__(self, cin, cout, kernel=3, dilation=1):
        super().__init__(); pad=(kernel-1)*dilation//2
        self.conv=nn.Conv1d(cin,cout,kernel,padding=pad,dilation=dilation)
        self.norm=nn.BatchNorm1d(cout); self.act=nn.GELU(); self.skip=nn.Conv1d(cin,cout,1) if cin!=cout else nn.Identity()
    def forward(self,x): return self.act(self.norm(self.conv(x))+self.skip(x))

class SharedTCNExtractor(BaseFeaturesExtractor):
    """Shared temporal encoder; account state is concatenated after temporal pooling."""
    def __init__(self, observation_space, features_dim=256, channels=(64,96,128), account_dim=5):
        super().__init__(observation_space, features_dim)
        market_dim=observation_space["market"].shape[-1]
        layers=[]; cin=market_dim
        for i,c in enumerate(channels): layers.append(TemporalConvBlock(cin,c,dilation=2**i)); cin=c
        self.tcn=nn.Sequential(*layers)
        self.account=nn.Sequential(nn.Linear(account_dim,32),nn.LayerNorm(32),nn.GELU())
        self.proj=nn.Sequential(nn.Linear(cin+32,features_dim),nn.LayerNorm(features_dim),nn.GELU())
        for m in self.modules():
            if isinstance(m,(nn.Linear,nn.Conv1d)): nn.init.orthogonal_(m.weight); nn.init.zeros_(m.bias)
    def forward(self,obs):
        x=obs["market"].float().transpose(1,2); z=self.tcn(x).mean(dim=-1); a=self.account(obs["account"].float()); return self.proj(torch.cat([z,a],dim=-1))
