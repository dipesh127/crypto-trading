import React,{useEffect,useRef,useState} from "react";
import {createChart,LineSeries} from "lightweight-charts";

export default function EquityChart({mode}){
 const ref=useRef(null), [visible,setVisible]=useState({PAPER_TESTNET:true,LIVE:false,BACKTEST:true});
 const [series,setSeries]=useState({PAPER_TESTNET:[],LIVE:[],BACKTEST:[]});
 useEffect(()=>{let dead=false; const end=new Date(),start=new Date(end-90*86400000);
  Promise.all(Object.keys(series).map(async m=>{try{const r=await fetch(`/api/timeseries/equity?mode=${encodeURIComponent(m)}&start=${start.toISOString()}&end=${end.toISOString()}&points=2500`); const d=await r.json(); return [m,d.points||[]]}catch{return [m,[]]}})).then(rows=>{if(!dead)setSeries(Object.fromEntries(rows))});
  return()=>{dead=true}},[mode]);
 useEffect(()=>{if(!ref.current)return; const chart=createChart(ref.current,{height:460,layout:{background:{color:"transparent"},textColor:"#ddd"},grid:{vertLines:{visible:false},horzLines:{visible:false}},rightPriceScale:{borderVisible:false},timeScale:{borderVisible:false}});
  const colors={PAPER_TESTNET:"#55e39a",LIVE:"#ff5c70",BACKTEST:"#6ea8fe"}; const handles=[]; for(const [name,rows] of Object.entries(series)){if(!visible[name]||!rows.length)continue; const line=chart.addSeries(LineSeries,{lineWidth:2,color:colors[name]}); line.setData(rows.map(r=>({time:Math.floor(Number(r[0])),value:Number(r[1])})).filter(x=>Number.isFinite(x.value))); handles.push(line)}
  const ro=new ResizeObserver(()=>chart.applyOptions({width:ref.current.clientWidth})); ro.observe(ref.current); chart.timeScale().fitContent(); return()=>{ro.disconnect();chart.remove()};
 },[series,visible]);
 return <><div className="toolbar"><label><input type="checkbox" checked={visible.PAPER_TESTNET} onChange={e=>setVisible(v=>({...v,PAPER_TESTNET:e.target.checked}))}/> Paper</label><label><input type="checkbox" checked={visible.LIVE} onChange={e=>setVisible(v=>({...v,LIVE:e.target.checked}))}/> Live</label><label><input type="checkbox" checked={visible.BACKTEST} onChange={e=>setVisible(v=>({...v,BACKTEST:e.target.checked}))}/> Backtest</label></div><div ref={ref} style={{width:"100%"}}/></>;
}
