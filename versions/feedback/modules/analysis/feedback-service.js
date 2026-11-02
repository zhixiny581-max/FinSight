const fs=require('fs'),path=require('path'),crypto=require('crypto');
const {AsyncLocalStorage}=require('async_hooks');
const context=new AsyncLocalStorage();
const {createAnalysisService:normalizer}=require('./feedback-normalizer');
const {createTools}=require('./evidence_tools');
const {cutoff}=require('./feedback-market');
const evidenceRecords=require('./evidence-records');
const hash=v=>crypto.createHash('sha256').update(typeof v==='string'?v:JSON.stringify(v)).digest('hex');
const prompt=fs.readFileSync(path.join(__dirname,'prompts/feedback.txt'),'utf8');
const codeCommit=(()=>{try{return require('child_process').execFileSync('git',['rev-parse','HEAD'],{cwd:__dirname,encoding:'utf8',windowsHide:true}).trim();}catch{return 'uncommitted';}})();
const DEFAULTS={rounds:2,tools:6,toolMs:15000,evidenceMs:45000,modelMs:45000,totalMs:240000,models:6};
function beginRequest(){context.enterWith({signal:AbortSignal.timeout(DEFAULTS.totalMs),started:Date.now()});}
function timestamp(raw){if(!raw)return NaN;const s=String(raw);return Date.parse(/^\d{4}-\d\d-\d\d$/.test(s)?s+'T23:59:59+08:00':/Z$|[+-]\d\d:?\d\d$/.test(s)?s:s.replace(' ','T')+'+08:00');}
function eligible(item,asOf,tool){const published=timestamp(item.published_at||item.time),updated=timestamp(item.updated_at);if(!Number.isFinite(asOf))return {eligible:false,reason:'as_of_unknown'};if(!Number.isFinite(published))return {eligible:false,reason:'publication_unknown'};if(published>asOf)return {eligible:false,reason:'after_as_of'};if(Number.isFinite(updated)&&updated>asOf)return {eligible:false,reason:'updated_after_as_of'};
 if(tool==='read_webpage' && Date.now()-asOf>86400000 && !item.historical_snapshot)return {eligible:false,reason:'current_page_historical_content_unverified'};
 return {eligible:true,reason:'published_before_as_of'};}
function withAbort(promise,signal){
 if(signal.aborted)return Promise.reject(signal.reason||new Error('ABORTED'));
 return new Promise((resolve,reject)=>{const abort=()=>reject(signal.reason||new Error('ABORTED'));signal.addEventListener('abort',abort,{once:true});Promise.resolve(promise).then(value=>{signal.removeEventListener('abort',abort);resolve(value);},error=>{signal.removeEventListener('abort',abort);reject(error);});});
}
function createAnalysisService(options){
 const norm=normalizer(options),tools=options.tools||createTools(options),sessions=new WeakMap();const budget={...DEFAULTS,...options.budget};
 function newRun(news){const timing=cutoff(news);return {run_id:crypto.randomUUID(),version:'feedback',code_commit:codeCommit,code_hash:hash(fs.readFileSync(__filename,'utf8')+fs.readFileSync(path.join(__dirname,'evidence-records.js'),'utf8')),started:Date.now(),deadline:(context.getStore()?.started||Date.now())+budget.totalMs,signal:context.getStore()?.signal||AbortSignal.timeout(budget.totalMs),prompt_hash:hash(prompt),model:options.model,input:news,input_hash:hash(news),as_of:timing.normalized_at||'',sources:options.sourceCatalogFromNews(news).map((s,index)=>({...s,content:s.content||s.full_text||(index===0?(news.full_text||news.content||news.summary||''):''),method:'input',retrieved_at:new Date().toISOString(),eligible:true})),sent_unit_ids:new Set(),round:0,toolCalls:0,modelCalls:0,evidenceMs:0,trace:[],model_trace:[],issues:[],budget};}
 function remaining(r){return Math.max(0,r.deadline-Date.now());}
 async function model(r,stage,previous){
 if(r.modelCalls>=budget.models||remaining(r)<1000)throw Error('ANALYSIS_BUDGET_EXHAUSTED');
 const consumed=evidenceRecords.sourceInput(r);
 for(const source of consumed)for(const unit of source.evidence_units)r.sent_unit_ids.add(unit.id);
 const stagePrompt=prompt;
 const input={stage,output_required:['verdict','industries','claims','semantic_review'],news:{title:r.input.title,summary:r.input.summary,full_text:String(r.input.full_text||r.input.content||'').slice(0,18000),published_at:r.input.published_at||r.input.time,source:r.input.source,url:r.input.url,market_context:r.input.market_context},as_of:r.as_of,sources:consumed,excluded_sources:r.sources.filter(s=>!s.eligible).map(s=>({id:s.id,reason:s.eligibility_reason})),previous,analysis_depth:'sector_and_related_companies',candidate_lookup_state:'not_queried_yet',stock_expansion_contract:'stock_expansion_allowed仅决定是否查询行业候选，不代表确认公司受益。初稿没有候选是因为尚未查询，禁止用候选池为空或公司暴露未核实否定行业查询。无经营变量变化的宏观或公司事件仍不扩展。',tool_availability:tools.availability(),tool_results:r.trace.map(t=>({request:t.request,status:t.status,error:t.error,source_ids:(t.items||[]).map(s=>s.id)})),remaining:{rounds:budget.rounds-r.round,tool_calls:budget.tools-r.toolCalls,model_calls:budget.models-r.modelCalls-1,time_ms:remaining(r)},review_instructions:'只分析事件及板块的大致方向、机制、条件、反向路径。不要逐家公司分析业务、财务或方向，不为候选名单查询公司资料。公司名单由后台iFinD取得。板块判断不能写成对全部成分公司的独立结论。'};
 r.modelCalls++;const record={stage,prompt_hash:hash(stagePrompt),input,started_at:new Date().toISOString()};r.model_trace.push(record);
 try{let raw;if(options.modelCall)raw=await options.modelCall(input);else{const key=options.getApiKey();if(!key)throw Error('AI_NOT_CONFIGURED');const res=await fetch(options.baseUrl.replace(/\/+$/,'')+'/chat/completions',{method:'POST',headers:{'Content-Type':'application/json',Authorization:`Bearer ${key}`},body:JSON.stringify({model:options.model,thinking:{type:'disabled'},temperature:0.15,max_tokens:8000,response_format:{type:'json_object'},messages:[{role:'system',content:stagePrompt},{role:'user',content:JSON.stringify(input)}]}),signal:AbortSignal.any([r.signal,AbortSignal.timeout(Math.min(budget.modelMs,remaining(r)))])});record.http_status=res.status;if(!res.ok)throw Error('AI_PROVIDER_ERROR');const body=await res.json();record.finish_reason=body.choices?.[0]?.finish_reason;record.usage=body.usage;const content=body.choices?.[0]?.message?.content||'';record.raw=content;raw=JSON.parse(content.replace(/^```(?:json)?\s*/,'').replace(/\s*```$/,''));}record.output=raw;return raw;}catch(e){record.error=e.name==='TimeoutError'?'AI_TIMEOUT':e.message;if(e instanceof SyntaxError&&!r.jsonRepairUsed&&r.modelCalls<budget.models&&remaining(r)>1000){r.jsonRepairUsed=true;r.issues.push({stage,reason:'bounded_json_repair'});return await model(r,stage+'_json_repair',{invalid_json:record.raw,repair_instruction:'上次JSON语法错误。仅修正JSON语法，保留内容和完整结构，禁止未转义引号。'});}throw e;}finally{record.finished_at=new Date().toISOString();}
 }
 async function retrieve(r,raw){
  if(r.round>=budget.rounds||r.toolCalls>=budget.tools||remaining(r)<1000||process.env.ANALYSIS_RETRIEVAL==='off')return false;
  const requests=Array.isArray(raw.tool_requests)?raw.tool_requests:[];if(!requests.length)return false;
  r.round++;const round=r.round,start=Date.now();let next=0;
  const requestKey=req=>hash({tool:req.tool,arguments:req.arguments||{}});
  async function worker(){
    while(next<requests.length){
      if(r.toolCalls>=budget.tools||r.evidenceMs+Date.now()-start>=budget.evidenceMs||remaining(r)<1000)return;
      const req=requests[next++];
      const duplicate=r.trace.find(t=>requestKey(t.request)===requestKey(req));
      const rec={round,request:req,started_at:new Date().toISOString()};r.trace.push(rec);r.toolCalls++;
      if(req.scope==='company'){rec.status='out_of_scope';rec.finished_at=new Date().toISOString();continue;}
      if(duplicate){rec.status='duplicate';rec.previous_status=duplicate.status;rec.finished_at=new Date().toISOString();continue;}
      if(!tools.availability()[req.tool]){rec.status='unavailable';rec.finished_at=new Date().toISOString();continue;}
      try{
        const timeout=Math.max(1,Math.min(budget.toolMs,budget.evidenceMs-r.evidenceMs-(Date.now()-start),remaining(r)));
        const signal=AbortSignal.any([r.signal,AbortSignal.timeout(timeout)]);
        const result=await withAbort(tools.execute(req,signal),signal);rec.raw=result.raw;rec.status=result.items?.length?'ok':'empty';rec.items=[];
        for(const item of result.items||[]){
          const check=eligible(item,timestamp(r.as_of),req.tool);
          const content=String(item.content||item.full_text||item.summary||'');
          const contentHash=hash(content);
          const existing=r.sources.find(s=>s.url===item.url&&s.title===item.title&&s.content_hash===contentHash);
          const source=existing||{...item,id:'evidence-'+(r.sources.length+1),method:req.tool,retrieved_at:new Date().toISOString(),eligible:check.eligible,eligibility_reason:check.reason,content:content.slice(0,12000),content_hash:contentHash,truncation:content.length>12000,evidence_level:item.evidence_level||(req.tool==='read_webpage'?'page_body':'news_excerpt'),...evidenceRecords.sourcePolicy(item)};
          if(!existing)r.sources.push(source);rec.items.push(source);
        }
      }catch(error){rec.status='failed';rec.error=/abort|timeout/i.test(error.name)?'timeout':error.message;}
      rec.finished_at=new Date().toISOString();
    }
  }
  await Promise.all([worker(),worker()]);r.evidenceMs+=Date.now()-start;return true;
 }
 function inspect(r,raw){const sources=new Map(r.sources.filter(s=>s.eligible&&s.fact_eligible!==false).map(s=>[s.id,s]));const issues=[];for(const c of raw.claims||[]){for(const e of c.evidence||[]){const s=sources.get(e.source_id);const unit=s&&e.unit_id&&evidenceRecords.units(s).find(u=>u.id===e.unit_id&&r.sent_unit_ids.has(u.id));if(!s||!unit&&(!e.excerpt||!String(s.content).includes(e.excerpt)))issues.push({claim:c.id,field:c.field_path,reason:'citation_not_supported',source_id:e.source_id});}if(c.kind==='fact'&&!(c.evidence||[]).length)issues.push({claim:c.id,field:c.field_path,reason:'fact_without_evidence'});}r.issues.push(...issues);return issues;}
 function project(r,raw,candidates=[]){raw=structuredClone(raw);
 for(const c of raw.claims||[]){if(c.kind!=='fact')continue;const supported=(c.evidence||[]).some(e=>r.sources.some(s=>s.id===e.source_id&&s.eligible&&s.fact_eligible!==false&&(e.unit_id&&r.sent_unit_ids.has(e.unit_id)&&evidenceRecords.units(s).some(u=>u.id===e.unit_id)||e.excerpt&&s.content.includes(e.excerpt))));if(supported)continue;
 const parts=String(c.field_path||'').replace(/^analysis\./,'').split('.');if(!['verdict','macro_analysis','direct_impacts','industries'].includes(parts[0])||parts.some(k=>['__proto__','constructor','prototype'].includes(k)))continue;let target=raw;for(const part of parts.slice(0,-1))target=target?.[part];const key=parts.at(-1);if(target&&typeof target[key]==='string'&&c.text&&target[key].includes(c.text)){target[key]=target[key].replace(c.text,'现有资料未能确认'+(c.subject||'该对象')+'的这项事实');r.issues.push({claim:c.id,field:c.field_path,reason:'unsupported_fact_withdrawn'});}}
 const a=norm.normalize(raw,r.input,candidates);a.sources=r.sources.filter(s=>s.eligible).map(({content,...s})=>s);a.news.sources=a.sources;a.analysis_version='feedback';a.evidence_review={issues:r.issues,claim_count:(raw.claims||[]).length};
 // No hardcoded headline or graph clearing: valid independent branches survive.
 const p=a.macro_analysis?.market_pricing;if(p && !(raw.claims||[]).some(c=>c.field_path?.includes('market_pricing')&&(c.evidence||[]).some(e=>r.sources.some(s=>s.id===e.source_id&&s.eligible&&e.excerpt&&s.content.includes(e.excerpt))))){p.state='无法判断';p.confidence=0;p.basis=['现有资料未提供这条事件的事前预期与定价关联证据。'];}
 return norm.validateAnalysis(a,r.input);}
 function save(r,analysis){
  const dir=options.auditDir||path.join(__dirname,'../news/prototype/data/analysis-runs');fs.mkdirSync(dir,{recursive:true});
  analysis.analysis_depth='sector_and_related_companies';
  analysis.analysis_metadata={version:'feedback',analysis_depth:analysis.analysis_depth,company_analysis:false,run_id:r.run_id,model:r.model,prompt_hash:r.prompt_hash,model_calls:r.modelCalls,tool_calls:r.toolCalls,retrieval_rounds:r.round,elapsed_ms:Date.now()-r.started,candidate_count:analysis.stocks.length,sector_count:analysis.industries.length,evidence_snapshot_hash:hash(r.sources),completion_status:r.issues.length||r.trace.some(t=>['failed','unavailable'].includes(t.status))?'partial':'complete'};
  const data={...r,signal:undefined,sent_unit_ids:[...r.sent_unit_ids],finished_at:new Date().toISOString(),elapsed_ms:analysis.analysis_metadata.elapsed_ms,analysis};
  fs.writeFileSync(path.join(dir,r.run_id+'.json'),JSON.stringify(data,null,2));
 }
 function checkDraft(raw,r){if(!raw?.verdict?.conclusion||!Array.isArray(raw.industries))throw Error('AI_INVALID_ANALYSIS');return norm.validateAnalysis(norm.normalize(raw,r.input,[]),r.input);}
 async function requestDeepSeekAnalysis(news){const r=newRun(news);let raw;try{try{raw=await model(r,'initial',null);checkDraft(raw,r);}catch(e){if(!(e instanceof SyntaxError)&&e.message!=='AI_INVALID_ANALYSIS')throw e;r.issues.push({stage:'initial',reason:'bounded_structure_repair'});raw=await model(r,'initial_repair',{error:e.message,previous:raw});checkDraft(raw,r);}while(r.round<budget.rounds&&r.modelCalls<budget.models-1&&await retrieve(r,raw)){try{const revised=await model(r,'revise_after_evidence',raw);checkDraft(revised,r);raw=revised;}catch(error){r.issues.push({stage:'sector_evidence',reason:error.message});break;}}const circular=(raw.industries||[]).filter(i=>i.stock_expansion_allowed===false&&/候选.{0,12}为空|未提供.{0,6}候选|尚无.{0,6}候选|候选股票池为空/.test(i.stock_expansion_basis||''));if(circular.length&&r.modelCalls<budget.models-1){r.issues.push({stage:'industry_query_gate',reason:'circular_candidate_requirement',industry_ids:circular.map(i=>i.id)});const corrected=await model(r,'initial_industry_query_review',{analysis:raw,correction:'尚未查询候选，因此候选为空不是拒绝查询的理由。仅按行业经营变量及适用一组公司判断是否查询，保留具体因果条件，不必确认个股受益。返回完整分析结构。'});try{checkDraft(corrected,r);raw=corrected;}catch(error){r.issues.push({stage:'industry_query_gate',reason:'invalid_correction_kept_previous'});}}inspect(r,raw);const a=project(r,raw);sessions.set(a,{r,raw});return a;}catch(e){save(r,norm.fallbackAnalysisFromNews(news,[],e));throw e;}}
 function applySectorReferences(analysis,candidates){
  const industryById=new Map(analysis.industries.map(i=>[i.id,i]));
  for(const stock of analysis.stocks){
    const industry=industryById.get(stock.industry_id);
    const direct=stock.impact_type==='direct';
    const reference=direct?analysis.verdict:industry;
    stock.direction=reference?.direction||'不确定';
    stock.impact_level=reference?.impact_level||'待评估';
    stock.confidence=Number.isFinite(reference?.confidence)?reference.confidence:0;
    stock.direction_scope=direct?'event_reference':industry?'industry_reference':'unmapped';
    stock.impact_level_scope=stock.direction_scope;
    stock.reference_label=direct?'事件方向参考':industry?'板块方向参考':'板块待匹配';
    stock.impact_type_label=direct?'事件相关':'板块相关';
    stock.role=stock.reason=direct
      ? '新闻中直接涉及的公司。表中方向仅参考事件整体判断。'
      : industry ? 'iFinD返回的'+industry.name+'板块相关公司。表中方向与强度引用该板块判断。'
      : '已取得公司候选，但尚未匹配有效板块。';
    stock.conditions=reference?.conditions||[];stock.risks=[];
    delete stock.review_status;delete stock.review_label;delete stock.business_exposure;delete stock.operating_variable;
  }
  analysis.candidate_stocks=analysis.screened_stocks=analysis.stocks;
  analysis.analysis_depth='sector_and_related_companies';
  analysis.company_listing={direction_basis:'sector_or_event_reference',company_analysis:false,note:'仅列涉及的公司及其板块关联，方向和强度为板块/事件参考，不是逐家公司研究结论。'};
  return analysis;
 }
 function attachCandidates(preliminary,candidates){
  const session=sessions.get(preliminary);
  const analysis=applySectorReferences(norm.attachCandidates(preliminary,candidates),candidates);
  if(session)save(session.r,analysis);
  return analysis;
 }
 function fallbackAnalysisFromNews(news,candidates,error,preliminary=null){return applySectorReferences(norm.fallbackAnalysisFromNews(news,candidates,error,preliminary),candidates);}

 return {requestDeepSeekAnalysis,attachCandidates,fallbackAnalysisFromNews,analysisErrorCode:norm.analysisErrorCode};
}
module.exports={createAnalysisService,beginRequest,context,eligible,DEFAULTS};
