// Shared event/sector evidence records. No individual company analysis.
function units(source) {
  const text = String(source.content || '');
  const result = [];
  // Fixed offsets are stable across batches and do not rely on model-generated quotations.
  for (let offset = 0; offset < text.length; offset += 480) {
    result.push({id: `${source.id}:p${result.length + 1}`, text: text.slice(offset, offset + 600)});
  }
  return result;
}
function sourcePolicy(item) {
 let host='';try{host=new URL(item.url||'').hostname.toLowerCase();}catch{}
 const authority=item.source_authority||item.authority_level||'';
 const commentary=/(^|\.)(toutiao\.com|xueqiu\.com|guba\.eastmoney\.com|guba\.10jqka\.com\.cn|baijiahao\.baidu\.com|zhihu\.com|weibo\.com)$/.test(host);
 const media=/(^|\.)(tmtpost\.com|stcn\.com|cnstock\.com|yicai\.com|cls\.cn|xinhuanet\.com|cctv\.com|people\.com\.cn|10jqka\.com\.cn|eastmoney\.com|sina\.com\.cn)$/.test(host);
 if(commentary)return {fact_eligible:false,evidence_use:'context_only',reliability_reason:'commentary_or_aggregator_unverified'};
 if(authority==='other'&&!media)return {fact_eligible:false,evidence_use:'context_only',reliability_reason:'publisher_not_verified'};
 return {fact_eligible:true,evidence_use:['official','company','exchange'].includes(authority)?'primary_material':'reported_material',reliability_reason:authority||'provided_material'};
}
function sourceInput(run, limit = 24000) {
  const available=run.sources.filter(s=>s.eligible).sort((a,b)=>Number(b.method==='input')-Number(a.method==='input'));
  const output = [];
  for (const source of available) {
    if (limit <= 0) break;
    if(source.fact_eligible===false){output.push({id:source.id,title:source.title,url:source.url,publisher:source.publisher||source.source,evidence_use:'context_only',reliability_reason:source.reliability_reason,content:'',evidence_units:[]});continue;}
    const all = units(source);
    const ordered = all;
    const selected = [];
    let sourceBudget = Math.min(6000, limit);
    for (const unit of ordered) {
      if (unit.text.length > sourceBudget) continue;
      selected.push(unit); sourceBudget -= unit.text.length; limit -= unit.text.length;
    }
    if (!selected.length && source.content) continue;
    const metadata={id:source.id,title:source.title,url:source.url,publisher:source.publisher||source.source,published_at:source.published_at,updated_at:source.updated_at,method:source.method,evidence_level:source.evidence_level,fact_eligible:source.fact_eligible!==false,evidence_use:source.evidence_use||'provided_material',reliability_reason:source.reliability_reason};
    output.push({...metadata, content: selected.map(u => u.text).join('\n'), evidence_units: selected});
  }
  return output;
}

module.exports={units,sourcePolicy,sourceInput};
