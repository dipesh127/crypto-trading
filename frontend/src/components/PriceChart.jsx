import React,{useEffect,useRef,useState} from 'react'
import {createChart,CandlestickSeries,LineSeries,createSeriesMarkers} from 'lightweight-charts'

export default function PriceChart({mode,symbol}){
 const ref=useRef(), [ma,setMa]=useState(true),[bb,setBb]=useState(false),[signals,setSignals]=useState(true),[rsi,setRsi]=useState(false)
 useEffect(()=>{let chart,series,maSeries,bbU,bbL,markerApi,rsiSeries,liveWs;let dead=false
  ;(async()=>{
   const end=new Date(),start=new Date(end-7*86400000)
   const d=await fetch(`/api/timeseries/price?mode=${mode}&symbol=${symbol}&start=${start.toISOString()}&end=${end.toISOString()}&points=2000`).then(r=>r.json()); if(dead)return
   const candles=(d.points||[]).map(p=>({time:p[0],open:Number(p[1]),high:Number(p[2]),low:Number(p[3]),close:Number(p[4])}))
   chart=createChart(ref.current,{layout:{background:{color:'#0b1020'},textColor:'#aab4cc'},grid:{vertLines:{color:'#172036'},horzLines:{color:'#172036'}},width:ref.current.clientWidth,height:360})
   series=chart.addSeries(CandlestickSeries,{}); series.setData(candles)
   if(ma){maSeries=chart.addSeries(LineSeries,{lineWidth:1});maSeries.setData(candles.map((x,i)=>{const s=candles.slice(Math.max(0,i-19),i+1);return {time:x.time,value:s.reduce((a,b)=>a+b.close,0)/s.length}}))}
   if(bb){bbU=chart.addSeries(LineSeries,{lineWidth:1});bbL=chart.addSeries(LineSeries,{lineWidth:1});bbU.setData(candles.map((x,i)=>{const z=candles.slice(Math.max(0,i-19),i+1).map(a=>a.close),m=z.reduce((a,b)=>a+b,0)/z.length,sd=Math.sqrt(z.reduce((a,b)=>a+(b-m)**2,0)/Math.max(1,z.length-1));return {time:x.time,value:m+2*sd}}));bbL.setData(candles.map((x,i)=>{const z=candles.slice(Math.max(0,i-19),i+1).map(a=>a.close),m=z.reduce((a,b)=>a+b,0)/z.length,sd=Math.sqrt(z.reduce((a,b)=>a+(b-m)**2,0)/Math.max(1,z.length-1));return {time:x.time,value:m-2*sd}}))}
   if(rsi){rsiSeries=chart.addSeries(LineSeries,{lineWidth:1,priceScaleId:'rsi'});rsiSeries.applyOptions({priceScaleId:'rsi'});rsiSeries.setData(candles.map((x,i)=>{const z=candles.slice(Math.max(1,i-13),i+1).map((a,j)=>j? a.close-candles[Math.max(0,i-13)+j-1].close:0).filter(Number.isFinite),up=z.filter(v=>v>0).reduce((a,b)=>a+b,0)/(z.length||1),dn=-z.filter(v=>v<0).reduce((a,b)=>a+b,0)/(z.length||1);return {time:x.time,value:dn===0?100:100-100/(1+up/dn)}}))}
   if(signals){const sig=await fetch(`/api/signals?mode=${mode}&symbol=${symbol}&start=${start.toISOString()}&end=${end.toISOString()}`).then(r=>r.json()).catch(()=>({rows:[]}));if(!dead)markerApi=createSeriesMarkers(series,(sig.rows||[]).map(x=>{const sell=['SELL','SHORT','EXIT'].includes(String(x.signal).toUpperCase());return {time:Math.floor(Date.parse(x.ts)/1000),position:sell?'aboveBar':'belowBar',color:sell?'#ff5c70':'#55e39a',shape:sell?'arrowDown':'arrowUp',text:x.signal}}))}
   const wsUrl=(location.protocol==='https:'?'wss://':'ws://')+location.host+'/ws/live'; liveWs=new WebSocket(wsUrl); liveWs.onopen=()=>liveWs.send(JSON.stringify({action:'subscribe',mode,symbols:[symbol],channels:['market']})); liveWs.onmessage=e=>{try{const x=JSON.parse(e.data);if(x.type!=='market_tick'||x.kind!=='kline'||x.symbol!==symbol||x.mode&&x.mode!==mode)return;const k=x.data;if(!k)return;series.update({time:Math.floor(Number(k.open_time||k.t||Date.now())/1000),open:Number(k.open||k.o||k.close),high:Number(k.high||k.h||k.close),low:Number(k.low||k.l||k.close),close:Number(k.close||k.c)})}catch{}}
   chart.timeScale().fitContent(); const ro=new ResizeObserver(()=>chart.applyOptions({width:ref.current.clientWidth}));ro.observe(ref.current)
   return()=>ro.disconnect()
  })(); return()=>{dead=true;liveWs?.close();markerApi?.detach?.();chart?.remove()}
 },[mode,symbol,ma,bb,signals,rsi])
 return <><div className="toolbar"><label><input type="checkbox" checked={ma} onChange={e=>setMa(e.target.checked)}/> MA</label><label><input type="checkbox" checked={bb} onChange={e=>setBb(e.target.checked)}/> Bollinger</label><label><input type="checkbox" checked={signals} onChange={e=>setSignals(e.target.checked)}/> Signals</label><label><input type="checkbox" checked={rsi} onChange={e=>setRsi(e.target.checked)}/> RSI</label></div><div ref={ref}/></>
}
