const number = v => v === null || v === undefined || String(v).trim() === '' || !Number.isFinite(Number(v)) ? null : Number(v);
const round = n => Math.round(n*100)/100;
function cutoff(news) {
 const raw=String(news?.published_at||news?.time||'');
 const m=raw.match(/(20\d{2})[-/.年](\d{1,2})[-/.月](\d{1,2})日?(?:[T\s]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?/);
 if(!m) return {event_published_at:raw,requested_cutoff:'',rule:'missing_time',precision:'unknown'};
 const exact=!!m[4]; const iso=`${m[1]}-${m[2].padStart(2,'0')}-${m[3].padStart(2,'0')}`;
 let instant=new Date(`${iso}T${m[4]?.padStart(2,'0')||'00'}:${m[5]||'00'}:${m[6]||'00'}+08:00`);
 if(exact && /(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw.trim())) instant=new Date(raw);
 if(!Number.isFinite(+instant)) return {event_published_at:raw,requested_cutoff:'',rule:'invalid_time',precision:'unknown'};
 const sh=new Date(+instant+8*3600000),day=sh.toISOString().slice(0,10);
 // 15:05 is the existing provider completion convention, recorded explicitly.
 const after=exact && sh.getUTCHours()*60+sh.getUTCMinutes()>=905;
 const requested=after?day:new Date(Date.parse(day+'T00:00:00Z')-86400000).toISOString().slice(0,10);
 return {event_published_at:raw,normalized_at:instant.toISOString(),timezone:'Asia/Shanghai',requested_cutoff:requested,rule:after?'after_1505_provider_completion_convention':'previous_completed_daily_bar',precision:exact?'minute':'date'};
}
function metrics(bars=[]) {
 const rows=bars.filter(b=>number(b.close)!==null && number(b.close)>0).slice(-60);
 if(!rows.length)return {observations:0};
 const last=rows.at(-1),ret=n=>rows.length>n?round((number(last.close)/number(rows.at(-1-n).close)-1)*100):null;
 const volumes=rows.slice(-25).map(b=>number(b.volume));
 let ratio=null;
 if(volumes.length===25 && volumes.every(v=>v!==null && v>=0)) {const prior=volumes.slice(0,20).reduce((a,b)=>a+b,0)/20; if(prior>0)ratio=round((volumes.slice(20).reduce((a,b)=>a+b,0)/5)/prior);}
 const high=Math.max(...rows.map(b=>number(b.close))),low=Math.min(...rows.map(b=>number(b.close)));
 return {observations:rows.length,window_start:rows[0].date,window_end:last.date,return_5d_pct:ret(5),return_20d_pct:ret(20),return_60d_pct:ret(59),return_60d_definition:'最近60条有效日线首尾涨跌幅（59个间隔）',volume_ratio_5d_to_prior20d:ratio,position_in_60d_range_pct:high!==low?round((last.close-low)/(high-low)*100):null,drawdown_from_60d_high_pct:round((last.close/high-1)*100),range_basis:'收盘价',price_adjustment:'供应方返回口径，未提供时不得假定复权一致'};
}
function excess(a,b) {
 const x=a.slice(-21),y=b.slice(-21);
 if(x.length!==21||y.length!==21||x.some((v,i)=>v.date!==y[i].date))return null;
 const am=metrics(x),bm=metrics(y);
 return am.return_20d_pct!==null&&bm.return_20d_pct!==null?round(am.return_20d_pct-bm.return_20d_pct):null;
}
function pricing(stockBars=[],marketBars=[],direction,industryBars=[]) {
 return {state:'无法判断',confidence:0,expected_direction:direction||'不确定',basis:['价格和成交量仅描述事前市场状态，不能据此确认这条事件已被提前定价。'],metrics:{stock:metrics(stockBars),market:metrics(marketBars),industry:metrics(industryBars),excess_return_20d_pct:excess(stockBars,marketBars),excess_industry_return_20d_pct:excess(stockBars,industryBars)},caveat:'事件定价还需当时公开的预期与事件关联证据。'};
}
module.exports={number,cutoff,metrics,pricing,excess};
