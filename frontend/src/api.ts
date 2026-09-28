import type {EventRow} from './types';
let token=localStorage.getItem('globex_token')||'';
export async function api<T>(path:string,method='GET',body?:unknown):Promise<T>{
 const r=await fetch('/api'+path,{method,headers:{'Content-Type':'application/json',...(token?{Authorization:'Bearer '+token}:{})},body:body===undefined?undefined:JSON.stringify(body)});
 if(!r.ok){const data=await r.json().catch(()=>({detail:'网络请求失败'}));throw new Error(typeof data.detail==='string'?data.detail: '请求参数有误');}
 return r.json() as Promise<T>;
}
let boot:Promise<void>|undefined;
export function bootstrap(){
 if(!boot)boot=(async()=>{if(!token){const r=await api<{token:string}>('/guest','POST');token=r.token;localStorage.setItem('globex_token',token);}})();
 return boot;
}
export function connect(session:string,onEvent:(e:EventRow)=>void,onStatus:(s:boolean)=>void){
 let stopped=false,after=0,ws:WebSocket|undefined,retry:ReturnType<typeof setTimeout>|undefined;
 const deliver=(e:EventRow)=>{if(e.type==='heartbeat'||e.seq<=after)return;after=e.seq;onEvent(e);};
 const open=()=>{
  if(stopped)return;
  ws=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}/api/ws/${session}`);
  ws.onopen=()=>{onStatus(true);ws?.send(JSON.stringify({token,after}));};
  ws.onmessage=e=>{try{deliver(JSON.parse(e.data) as EventRow);}catch{/* malformed frame ignored */}};
  ws.onerror=()=>ws?.close();ws.onclose=()=>{onStatus(false);if(!stopped)retry=setTimeout(open,1800);};
 };
 // The SQLite event cursor also supports recovery when WebSocket is blocked by a proxy.
 const poll=setInterval(()=>{if(ws?.readyState!==WebSocket.OPEN)api<EventRow[]>(`/sessions/${session}/events?after=${after}`).then(rows=>{if(!stopped)rows.forEach(deliver);}).catch(()=>{});},2500);
 open();return()=>{stopped=true;clearInterval(poll);if(retry)clearTimeout(retry);ws?.close();};
}
export const requestId=()=>crypto.randomUUID();
