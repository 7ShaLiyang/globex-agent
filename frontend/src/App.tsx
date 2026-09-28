import {useCallback,useEffect,useRef,useState} from 'react';
import {ArrowUp,ArrowUpRight,Check,ChevronRight,Globe2,Headphones,Heart,Layers3,LoaderCircle,MessageSquare,Minus,Package,Plus,Search,ShoppingBag,SlidersHorizontal,Sparkles,Trash2,X} from 'lucide-react';
import {api,bootstrap,connect,requestId} from './api';
import type {EventRow,Product,Session,Snapshot} from './types';
import ProductDetails from './ProductDetails';
type Tab='discover'|'cart'|'orders'|'preferences';
const empty:Snapshot={cart:{items:{},products:[],revision:0},orders:[],preferences:[],confirmations:[]};
const names:Record<string,string>={budget:'预算',brand:'品牌',category:'品类',currency:'货币',destination:'目的地',style:'风格'};
export default function App(){
 const [sessions,setSessions]=useState<Session[]>([]),[session,setSession]=useState('');
 const [health,setHealth]=useState<{mode:string;model?:string}>({mode:'demo'});
 const [snapshot,setSnapshot]=useState<Snapshot>(empty),[products,setProducts]=useState<Product[]>([]);
 const [events,setEvents]=useState<EventRow[]>([]),[input,setInput]=useState(''),[busy,setBusy]=useState(false),[actionBusy,setActionBusy]=useState(false);
 const [error,setError]=useState(''),[online,setOnline]=useState(false),[tab,setTab]=useState<Tab>('discover');
 const [query,setQuery]=useState(''),[mode,setMode]=useState('catalog'),[country,setCountry]=useState('US'),[currency,setCurrency]=useState('USD');
 const [compare,setCompare]=useState<string[]>([]),[showCompare,setShowCompare]=useState(false),[selectedProduct,setSelectedProduct]=useState<Product>(),[pref,setPref]=useState(''),[prefKey,setPrefKey]=useState('style');
 const catalog=useRef(new Map<string,Product>());products.forEach(p=>catalog.current.set(p.id,p));
 const [trace,setTrace]=useState(false);const end=useRef<HTMLDivElement>(null);const currentSession=useRef(session);currentSession.current=session;
 const refresh=useCallback(async(id:string)=>{const s=await api<Snapshot>(`/sessions/${id}/state`);if(currentSession.current===id)setSnapshot(s);},[]);
 useEffect(()=>{let active=true;(async()=>{
  await bootstrap();const [h,list,p]=await Promise.all([api<{mode:string;model?:string}>('/health'),api<Session[]>('/sessions'),api<{products:Product[]}>('/products')]);
  const ss=list.length?list:[await api<Session>('/sessions','POST')];if(!active)return;
  setHealth(h);setSessions(ss);setProducts(p.products);setSession(ss.find(s=>s.id===localStorage.getItem('globex_session'))?.id||ss[0].id);
 })().catch(e=>setError(String(e.message)));return()=>{active=false;};},[]);
 useEffect(()=>{
  if(!session)return;setEvents([]);setBusy(false);localStorage.setItem('globex_session',session);refresh(session).catch(e=>setError(e.message));
    const disconnect=connect(session,e=>{
   setEvents(old=>old.some(v=>v.seq===e.seq)?old:[...old,e]);
   if(e.type==='user_message'||e.type==='job_started')setBusy(true);
   if(e.type==='job_finished'){setBusy(false);if(e.data?.error)setError(e.data.error);}
   if(e.type==='tool_result'&&e.data?.result?.products){setProducts(e.data.result.products);setMode(e.data.result.mode||'catalog');}
   if(['job_finished','tool_result','confirm','reject','cart_set','order_propose','preference_propose'].includes(e.type))refresh(session).catch(()=>{});
  },setOnline);
    return ()=>disconnect();
 },[session,refresh]);
 useEffect(()=>{
    end.current?.scrollIntoView({behavior:'smooth'});
 },[events,busy]);
 useEffect(()=>{
  const openProduct=(event:MouseEvent)=>{
  const target=event.target as HTMLElement;
  if(target.closest('button'))return;
  const card=target.closest<HTMLElement>('.product');
  const title=card?.querySelector('h3')?.textContent;
  const product=products.find(item=>item.title===title);
  if(product)setSelectedProduct(product);
  };
  document.addEventListener('click',openProduct);
  return()=>document.removeEventListener('click',openProduct);
 },[products]);
 async function newSession(){try{const s=await api<Session>('/sessions','POST');setSessions(v=>[...v,s]);setSession(s.id);}catch(e){setError((e as Error).message);}}
 async function deleteSession(id:string){
  if(!window.confirm('删除这个会话及其历史记录？'))return;
  try{
   await api(`/sessions/${id}`,'DELETE');
   const remaining=sessions.filter(item=>item.id!==id);
   if(remaining.length){setSessions(remaining);if(session===id)setSession(remaining[0].id);}
   else{const created=await api<Session>('/sessions','POST');setSessions([created]);setSession(created.id);}
  }catch(e){setError((e as Error).message);}
 }
 async function send(value=input){
  if(!session||busy||!value.trim())return;setError('');setBusy(true);setInput('');
  try{await api(`/sessions/${session}/messages`,'POST',{text:value,request_id:requestId()});}
  catch(e){setBusy(false);setInput(value);setError((e as Error).message);}
 }
 async function action(name:string,args:Record<string,unknown>){
  if(actionBusy||!session)return;setActionBusy(true);setError('');
  try{await api(`/sessions/${session}/actions`,'POST',{action:name,args,request_id:requestId()});await refresh(session);
   const p=await api<{products:Product[]}>('/products');setProducts(old=>old.map(x=>p.products.find(y=>y.id===x.id)||x));
  }catch(e){setError((e as Error).message);}finally{setActionBusy(false);}
 }
 async function search(q=query){setError('');try{const p=await api<{products:Product[];mode:string}>('/products?q='+encodeURIComponent(q));setProducts(p.products);setMode(p.mode);}catch(e){setError((e as Error).message);}}
 const messages=events.filter(e=>['user_message','assistant_message'].includes(e.type));
 const finished=new Set(events.filter(e=>e.type==='job_finished').map(e=>e.job));
 const live=events.filter(e=>e.type==='text_delta'&&e.data?.agent==='CommerceConcierge'&&!finished.has(e.job)).map(e=>e.data?.text||'').join('');
 const count=Object.values(snapshot.cart.items).reduce((a,b)=>a+b,0);
 const taskEvent=[...events].reverse().find(e=>e.type==='task_plan');
 const tasks=taskEvent?.data?.tasks?.tasks||[];
 return <div className="shell">
  <aside className="rail"><a className="logo" href="/" aria-label="Globex"><Globe2 size={29}/></a><div className="rail-line"/>
   <button className="rail-button selected" title="购物助理"><MessageSquare size={21}/></button>
   <button className="rail-button" title="我的订单" onClick={()=>setTab('orders')}><Package size={21}/></button>
   <button className="rail-button" title="偏好" onClick={()=>setTab('preferences')}><Heart size={21}/></button>
   <div className="rail-bottom"><span className="avatar">G</span></div>
  </aside>
  <div className="workspace"><header><div className="brand">globex<span> / </span><small>购物工作台</small></div><div className="header-right"><span className={'connection '+(online?'online':'')}/><span>{online?'已连接':'连接恢复中'}</span><span className="beta">PREVIEW</span></div></header>
   <div className="mode-banner"><span><Sparkles size={14}/>{health.mode==='llm'?`LLM 模式 · ${health.model}`:'演示模式 · 规则回复，未调用大模型'}</span><span>模拟商品与交易 · 不产生真实付款</span></div>
   <main><section className="chat-panel"><div className="chat-toolbar"><div><span className="mini-label">YOUR COMMERCE CONCIERGE</span><h2>购物，聊聊就好。</h2></div><button className="icon-button" onClick={newSession} disabled={busy} title="新建对话"><Plus size={20}/></button></div>
    <div className="session-row"><MessageSquare size={14}/><select aria-label="选择会话" value={session} disabled={busy} onChange={e=>setSession(e.target.value)}>{sessions.map((s,i)=><option key={s.id} value={s.id}>购物对话 {i+1} · {s.id.slice(0,6)}</option>)}</select><button onClick={()=>setTrace(!trace)}><Layers3 size={14}/>执行轨迹</button><button aria-label="删除当前会话" title="删除当前会话" disabled={busy||!session} onClick={()=>deleteSession(session)}><Trash2 size={14}/></button></div>
    <div className="conversation">
     {messages.length===0&&<div className="welcome"><div className="welcome-symbol"><Globe2 size={38}/><span>✦</span></div><span className="eyebrow">LESS SEARCHING, MORE FINDING</span><h1>全球好物，<br/>从一句话开始。</h1><p>告诉我你在找什么。我来帮你挑选、比较，<br/>算清价格，再由你决定。</p><div className="suggestions">{['帮我找一款适合通勤的降噪耳机','推荐旅行背包和 USB-C 充电器','查看我的订单'].map((s,i)=><button key={s} onClick={()=>send(s)}><span>{i===0?<Headphones size={17}/>:i===1?<ShoppingBag size={17}/>:<Package size={17}/>} {s}</span><ArrowUpRight size={16}/></button>)}</div></div>}
     {messages.map(e=><div key={e.seq} className={'message '+(e.type==='user_message'?'user':'assistant')}><div className="message-meta">{e.type==='user_message'?'你':<><Globe2 size={15}/> GLOBEX ASSISTANT</>}</div><div className="bubble">{e.data?.text}</div></div>)}
     {busy&&<div className="working"><LoaderCircle size={16} className="spin"/><div>{live||'正在为你整理…'}</div></div>}
     {tasks.length>0&&<div className="task-list">{tasks.map(t=><div key={t.id}><span>{t.status==='completed'?'✓':'○'}</span>{t.subject}</div>)}</div>}
     {trace&&<div className="trace"><b>工具与任务轨迹</b>{events.filter(e=>['agent_event','tool_result','job_started','job_finished','task_plan'].includes(e.type)).slice(-20).map(e=><div key={e.seq}><span>#{e.seq}</span>{e.data?.tool_call_name||e.data?.tool||e.data?.type||e.type}</div>)}</div>}
     <div ref={end}/>
    </div>
    {error&&<div className="error" role="alert">{error}<button aria-label="关闭错误" onClick={()=>setError('')}><X size={14}/></button></div>}
    <form className="composer" onSubmit={e=>{e.preventDefault();send();}}><textarea value={input} maxLength={4000} onChange={e=>setInput(e.target.value)} placeholder="描述你想找的好物，或继续追问…" rows={2} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();send();}}}/><div><span><Sparkles size={14}/> 选品 · 比较 · 下单</span><button aria-label="发送" type="submit" disabled={busy||!session||!input.trim()}>{busy?<LoaderCircle size={19} className="spin"/>:<ArrowUp size={20}/>}</button></div></form><div className="composer-hint">Enter 发送 · Shift + Enter 换行 · 关键操作由你确认</div>
   </section>
   <section className="shopping-panel"><nav>{([['discover','发现好物'],['cart',`购物车${count?' · '+count:''}`],['orders','订单'],['preferences','偏好']] as [Tab,string][]).map(([k,t])=><button className={tab===k?'active':''} key={k} onClick={()=>setTab(k)}>{t}</button>)}</nav>
    <div className="shopping-scroll">
     {snapshot.confirmations.length>0&&<div className="confirmations">{snapshot.confirmations.map(p=><article key={p.id} className="confirm-card"><div className="confirm-heading"><span><Check size={15}/></span><b>{p.kind==='order'?'确认这笔订单':p.kind==='cancel_order'?'确认取消订单':'保存这条偏好？'}</b></div>{p.kind==='order'&&p.quote?<><p>{p.items?.map(i=>`${i.title} × ${i.quantity}`).join('、')}</p><div className="quote-grid"><span>商品</span><b>{p.quote.subtotal}</b><span>估算税费</span><b>{p.quote.tax}</b><span>运费</span><b>{p.quote.shipping}</b><span>合计 · {p.quote.currency}</span><strong>{p.quote.total}</strong></div><small>{p.quote.notice}</small></>:<p>{p.kind==='preference'?`${names[p.key||'']||p.key}：${p.value}`:`订单 ${p.order_id?.slice(0,8)}；取消后释放库存。`}</p>}<div className="confirm-actions"><button disabled={actionBusy} onClick={()=>action('reject',{proposal_id:p.id})}>暂不执行</button><button className="primary" disabled={actionBusy} onClick={()=>action('confirm',{proposal_id:p.id})}>确认{p.kind==='order'?'下单':p.kind==='preference'?'保存':'取消'}</button></div></article>)}</div>}
     {tab==='discover'&&<><div className="section-title"><div><span className="mini-label">CURATED FOR YOUR EVERYDAY</span><h2>发现一点新喜欢</h2></div><SlidersHorizontal size={19}/></div><form className="catalog-search" onSubmit={e=>{e.preventDefault();search();}}><Search size={16}/><input aria-label="搜索商品" value={query} onChange={e=>setQuery(e.target.value)} placeholder="搜索商品、用途或关键词"/><button type="submit"><ChevronRight size={18}/></button></form><div className="categories">{[['','全部好物'],['耳机','数码音频'],['旅行','旅行出行'],['家居','生活方式']].map(([q,label])=><button key={label} className={query===q?'chosen':''} onClick={()=>{setQuery(q);search(q);}}>{label}</button>)}</div><div className="catalog-meta"><span>{products.length} 件好物 · USD</span><span>{({'catalog':'精选目录','keyword_2gram':'关键词检索','embedding_only':'向量检索','embedding+rerank':'向量 + 重排'} as Record<string,string>)[mode]||mode}</span></div><div className="product-grid">{products.map(p=><article key={p.id} className="product"><div className={'product-art '+p.color}><span>{p.icon}</span><button aria-label={'对比 '+p.title} className={compare.includes(p.id)?'checked':''} onClick={()=>setCompare(v=>v.includes(p.id)?v.filter(id=>id!==p.id):v.length<3?[...v,p.id]:v)}>{compare.includes(p.id)?<Check size={15}/>:<Plus size={15}/>}</button><small>{p.category.toUpperCase()}</small></div><div className="product-details"><h3>{p.title}</h3><p>库存 {p.stock} · 商品 {p.id}</p><div><strong><small>$</small>{p.price}</strong><button aria-label={'加入购物车 '+p.title} disabled={actionBusy||p.stock===0} onClick={()=>action('cart_set',{product_id:p.id,quantity:Math.min((snapshot.cart.items[p.id]||0)+1,20)})}><Plus size={17}/></button></div></div></article>)}</div>{products.length===0&&<div className="empty-state"><Search/><h3>没有找到匹配商品</h3><p>试试更短的品类词，或让助理换个方向。</p></div>}<div className="editorial"><Globe2 size={24}/><div><b>好选择，也要清楚的价格。</b><p>结算前展示商品、运费与估算税费。</p></div><ArrowUpRight size={18}/></div></>}
     {tab==='cart'&&<><div className="section-title"><div><span className="mini-label">YOUR LITTLE FINDS</span><h2>购物车 <em>{count}</em></h2></div><ShoppingBag size={22}/></div>{snapshot.cart.products.length===0?<div className="empty-state"><ShoppingBag/><h3>好物还在路上</h3><p>从发现页选几件喜欢的吧。</p><button onClick={()=>setTab('discover')}>去挑选 <ArrowUpRight size={14}/></button></div>:<>{snapshot.cart.products.map(p=><div className="cart-item" key={p.id}><div className={'cart-art '+p.color}>{p.icon}</div><div><b>{p.title}</b><p>${p.price}</p><div className="quantity"><button disabled={actionBusy} onClick={()=>action('cart_set',{product_id:p.id,quantity:(p.quantity||1)-1})}><Minus size={13}/></button>{p.quantity}<button disabled={actionBusy||(p.quantity||0)>=20} onClick={()=>action('cart_set',{product_id:p.id,quantity:(p.quantity||1)+1})}><Plus size={13}/></button></div></div><button className="remove" title="移除" disabled={actionBusy} onClick={()=>action('cart_set',{product_id:p.id,quantity:0})}><Trash2 size={16}/></button></div>)}<div className="checkout"><label>目的地<select value={country} onChange={e=>setCountry(e.target.value)}><option value="US">美国 US</option><option value="CN">中国 CN</option><option value="DE">德国 DE</option></select></label><label>报价货币<select value={currency} onChange={e=>setCurrency(e.target.value)}><option>USD</option><option>CNY</option><option>EUR</option></select></label><button className="primary" disabled={actionBusy} onClick={()=>action('order_propose',{destination:country,currency})}>生成报价并核对 <ArrowUpRight size={17}/></button><small>点击后先展示报价，确认后才创建模拟订单。</small></div></>}</>}
   {tab==='orders'&&<><div className="section-title"><div><span className="mini-label">EVERY ORDER, IN ONE PLACE</span><h2>我的订单</h2></div><Package size={22}/></div>{snapshot.orders.length===0?<div className="empty-state"><Package/><h3>还没有订单</h3><p>确认购物车报价后，订单会显示在这里。</p></div>:snapshot.orders.slice().reverse().map(o=><article className="order" key={o.id}><div><code>#{o.id.slice(0,8)}</code><span className={o.status==='cancelled'?'cancelled':'order-status'}>{o.status==='created'?'已创建':o.status==='cancelled'?'已取消':o.status}</span></div><p>{o.items.map(p=>`${p.title} × ${p.quantity}`).join('、')}</p><footer><b>{o.quote.currency} {o.quote.total}</b></footer></article>)}</>}
     {tab==='preferences'&&<><div className="section-title"><div><span className="mini-label">A LITTLE MORE YOU</span><h2>你的购物偏好</h2></div><Heart size={22}/></div><p className="muted">只保存你亲自确认过的偏好。下一次对话会参考这些信息。</p>{snapshot.preferences.map(p=><div className="preference" key={p.id}><span>{names[p.id]||p.id}</span><b>{p.value}</b><Check size={15}/></div>)}<form className="preference-form" onSubmit={e=>{e.preventDefault();if(pref.trim())action('preference_propose',{key:prefKey,value:pref});}}><label>新增或修改偏好</label><select value={prefKey} onChange={e=>setPrefKey(e.target.value)}>{Object.entries(names).map(([k,v])=><option key={k} value={k}>{v}</option>)}</select><input value={pref} maxLength={200} onChange={e=>setPref(e.target.value)} placeholder="例如：喜欢简约风格"/><button disabled={actionBusy||!pref.trim()} className="primary">生成确认卡片</button></form></>}
    </div>{compare.length>0&&<div className="compare-bar"><span>已选 {compare.length}/3 件商品</span><button onClick={()=>setShowCompare(true)}>对比看看 <ArrowUpRight size={14}/></button><button aria-label="清空对比" onClick={()=>setCompare([])}><X size={16}/></button></div>}
   </section></main>
   </div>{selectedProduct&&<ProductDetails product={selectedProduct} onClose={()=>setSelectedProduct(undefined)} onAdd={()=>{action('cart_set',{product_id:selectedProduct.id,quantity:Math.min((snapshot.cart.items[selectedProduct.id]||0)+1,20)});setSelectedProduct(undefined);}}/>}{showCompare&&<div className="modal-backdrop" onClick={()=>setShowCompare(false)}><div className="modal" role="dialog" aria-modal="true" aria-label="商品对比" onClick={e=>e.stopPropagation()}><button className="modal-close" aria-label="关闭对比" onClick={()=>setShowCompare(false)}><X/></button><span className="mini-label">SIDE BY SIDE</span><h2>把选择看清楚</h2><div className="compare-table"><table><thead><tr><th>商品</th>{compare.map(id=><th key={id}>{catalog.current.get(id)?.title||id}</th>)}</tr></thead><tbody>{[['price','价格 USD'],['stock','库存'],['category','品类']].map(([k,label])=><tr key={k}><td>{label}</td>{compare.map(id=><td key={id}>{String(catalog.current.get(id)?.[k as keyof Product]??'请重新搜索该商品')}</td>)}</tr>)}</tbody></table></div></div></div>}
 </div>;
}
