const fs = require('fs');
const path = require('path');

const PROMPT_FILE = path.join(__dirname, 'prompts', 'impact-analysis.txt');
const DIRECTIONS = ['利好', '利空', '多空交织', '不确定'];
const HORIZONS = ['短期', '中期', '长期', '不确定'];
const IMPACT_LEVELS = ['高', '中', '低', '待评估'];
const PRICING_STATES = ['未见明显提前定价', '部分提前定价', '提前定价较充分', '可能过度交易', '无法判断', '不适用'];
const ANALYSIS_SCOPES = ['公司级', '行业级', '宏观级', '混合型'];
const MACRO_NODE_TYPES = ['event', 'direct_shock', 'real_economy', 'policy_expectation', 'market'];
const DIRECT_ENTITY_TYPES = ['上市公司', '非上市公司', '机构', '政府部门', '其他'];
const NON_INDUSTRY_ASSETS = new Set([
  '黄金', '金价', '美元', '美元指数', '人民币', '汇率', '美债', '国债', '债券',
  '利率', '实际利率', '名义利率', '原油', '油价', '铜价', '大宗商品',
  'A股', '全A', '同花顺全A', '美股', '港股', '全球股市', '科技股', '成长股', '价值股'
]);

function text(value, fallback = '') {
  const result = value === undefined || value === null ? '' : String(value).trim();
  return result || fallback;
}

function textList(value, limit = 12) {
  if (!Array.isArray(value)) return [];
  return value.map(item => text(item)).filter(Boolean).slice(0, limit);
}

function clamp(value, min, max, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? Math.min(Math.max(number, min), max) : fallback;
}

function normalizeConfidence(value) {
  const number = clamp(value, 0, 100, 0);
  return number <= 1 && number > 0 ? Math.round(number * 100) : Math.round(number);
}

function parseJson(content) {
  const cleaned = text(content).replace(/^```json\s*/i, '').replace(/^```\s*/i, '').replace(/\s*```$/, '').trim();
  try {
    return JSON.parse(cleaned);
  } catch {
    const start = cleaned.indexOf('{');
    const end = cleaned.lastIndexOf('}');
    if (start >= 0 && end > start) {
      try { return JSON.parse(cleaned.slice(start, end + 1)); } catch {}
    }
    throw new Error('AI_INVALID_JSON');
  }
}

function chineseBigrams(value) {
  const normalized = text(value).toLowerCase().replace(/[^\p{L}\p{N}]/gu, '');
  const grams = new Set();
  for (let index = 0; index < normalized.length - 1; index += 1) grams.add(normalized.slice(index, index + 2));
  return grams;
}

function overlapRatio(first, second) {
  const a = chineseBigrams(first);
  const b = chineseBigrams(second);
  if (!a.size || !b.size) return 0;
  let overlap = 0;
  for (const item of a) if (b.has(item)) overlap += 1;
  return overlap / Math.min(a.size, b.size);
}

function analysisErrorCode(error) {
  const message = error && error.message ? error.message : '';
  if (message === 'AI_NOT_CONFIGURED') return 'not_configured';
  if (message === 'AI_INVALID_JSON') return 'invalid_json';
  if (message === 'AI_INVALID_ANALYSIS') return 'invalid_analysis';
  if (message === 'AI_TIMEOUT') return 'timeout';
  return 'provider_error';
}

function invalidAnalysis(reason) {
  const error = new Error('AI_INVALID_ANALYSIS');
  error.validationReason = text(reason, '结构化分析未通过核心校验');
  return error;
}

function isIndustryNodeName(value) {
  const name = text(value).replace(/[（(].*?[）)]/g, '').trim();
  if (!name || NON_INDUSTRY_ASSETS.has(name)) return false;
  if (/^(通胀|通缩|经济增长|风险偏好|流动性|货币政策|财政政策|信用条件|避险情绪)$/.test(name)) return false;
  return true;
}

function normalizeIndustries(rawIndustries) {
  const source = (Array.isArray(rawIndustries) ? rawIndustries : [])
    .filter(raw => isIndustryNodeName(typeof raw === 'string' ? raw : raw && (raw.name || raw.industry)));
  const ids = new Set();
  const industries = source.slice(0, 12).map((raw, index) => {
    const item = typeof raw === 'string' ? { name: raw } : (raw || {});
    let id = text(item.id, `industry-${index + 1}`).replace(/[^a-zA-Z0-9_-]/g, '-');
    if (!id || id === 'event' || ids.has(id)) id = `industry-${index + 1}`;
    ids.add(id);
    return {
      id,
      name: text(item.name || item.industry, '待判断行业'),
      parent_id: text(item.parent_id || item.parent, 'event'),
      chain_stage: Math.max(1, Math.min(6, Math.round(Number(item.chain_stage || item.stage || 1) || 1))),
      role: text(item.role || item.reason || item.explanation, '传导作用待进一步验证。'),
      direction: DIRECTIONS.includes(item.direction) ? item.direction : '不确定',
      confidence: normalizeConfidence(item.confidence),
      impact_level: IMPACT_LEVELS.includes(item.impact_level) ? item.impact_level : '待评估',
      stock_expansion_allowed: item.stock_expansion_allowed === true,
      stock_expansion_basis: text(item.stock_expansion_basis),
      driver_node_id: text(item.driver_node_id || item.macro_driver_id),
      reason: text(item.reason || item.explanation || item.role, '资料不足，暂不作确定判断。')
    };
  });

  const known = new Set(industries.map(item => item.id));
  for (const industry of industries) {
    if (industry.chain_stage === 1 || !known.has(industry.parent_id) || industry.parent_id === industry.id) {
      industry.parent_id = 'event';
      industry.chain_stage = 1;
    }
  }
  return industries;
}

function normalizeDirectImpacts(rawDirectImpacts) {
  const source = Array.isArray(rawDirectImpacts) ? rawDirectImpacts : [];
  const ids = new Set();
  return source.slice(0, 16).map((raw, index) => {
    const item = raw && typeof raw === 'object' ? raw : { name: raw };
    let id = text(item.id, `direct-${index + 1}`).replace(/[^a-zA-Z0-9_-]/g, '-');
    if (!id || ids.has(id)) id = `direct-${index + 1}`;
    ids.add(id);
    const entityType = DIRECT_ENTITY_TYPES.includes(item.entity_type) ? item.entity_type : '其他';
    const listedStatus = ['已上市', '未上市', '未独立上市', '待核验'].includes(item.listed_status)
      ? item.listed_status : (entityType === '上市公司' ? '已上市' : '待核验');
    return {
      id,
      name: text(item.name || item.entity || item.company, '直接影响对象待核验'),
      ticker: text(item.ticker || item.code),
      entity_type: entityType,
      listed_status: listedStatus,
      stock_lookup_allowed: item.stock_lookup_allowed !== false && listedStatus !== '未上市'
        && ['上市公司', '其他'].includes(entityType),
      relation: text(item.relation || item.role, '事件直接参与方'),
      direction: DIRECTIONS.includes(item.direction) ? item.direction : '不确定',
      horizon: HORIZONS.includes(item.horizon) ? item.horizon : '不确定',
      confidence: normalizeConfidence(item.confidence),
      impact_level: IMPACT_LEVELS.includes(item.impact_level) ? item.impact_level : '待评估',
      mechanism: text(item.mechanism || item.reason, '事件对该对象的直接影响仍需核验。'),
      conditions: textList(item.conditions, 4),
      risks: textList(item.risks || item.counter_factors, 4),
      evidence: text(item.evidence || item.evidence_text),
      listing_verification_source: text(item.listing_verification_source),
      listing_verified_at: text(item.listing_verified_at),
      listed_proxy_name: text(item.listed_proxy_name),
      listed_proxy_ticker: text(item.listed_proxy_ticker),
      listed_proxy_relation: text(item.listed_proxy_relation),
      evidence_source_ids: textList(item.evidence_source_ids, 4).length
        ? textList(item.evidence_source_ids, 4) : ['news-1']
    };
  }).filter(item => item.name !== '直接影响对象待核验');
}

function normalizeIndustryChain(rawChain, industries, eventLabel, eventDirection) {
  const industryById = new Map(industries.map(item => [item.id, item]));
  const rawEdges = Array.isArray(rawChain && rawChain.edges) ? rawChain.edges : [];
  const edgeByTarget = new Map();
  for (const edge of rawEdges) {
    const target = text(edge && (edge.to || edge.target));
    if (target && industryById.has(target)) edgeByTarget.set(target, edge || {});
  }

  const nodes = [{ id: 'event', type: 'event', label: text(eventLabel, '新闻事件'), direction: eventDirection }]
    .concat(industries.map(industry => ({
      id: industry.id,
      type: 'industry',
      label: industry.name,
      stage: industry.chain_stage,
      role: industry.role,
      direction: industry.direction,
      confidence: industry.confidence,
      impact_level: industry.impact_level,
      driver_node_id: industry.driver_node_id
    })));
  const edges = industries.map(industry => {
    const raw = edgeByTarget.get(industry.id) || {};
    return {
      from: industry.parent_id,
      to: industry.id,
      mechanism: text(raw.mechanism || raw.reason || raw.label, industry.reason),
      direction: DIRECTIONS.includes(raw.direction) ? raw.direction : industry.direction
    };
  });
  return { nodes, edges };
}

function mainScenarioConclusion(value, fallback) {
  let result = text(value, fallback);
  const reverseIndex = result.search(/反向风险|反向情景/);
  if (reverseIndex >= 0) result = result.slice(0, reverseIndex).trim();
  result = result.replace(/[；，、:：\s]+$/, '');
  if (result && !/[。！？]$/.test(result)) result += '。';
  return result;
}

function normalizeVerdict(raw, event, news) {
  const verdict = raw && typeof raw.verdict === 'object' ? raw.verdict : {};
  const conclusion = mainScenarioConclusion(verdict.conclusion || raw.inference_conclusion,
    '现有资料不足以形成独立推演结论，需要继续验证关键变量及行业传导关系。');
  return {
    headline: text(verdict.headline, '条件性影响仍待验证').slice(0, 30),
    conclusion,
    direction: DIRECTIONS.includes(verdict.direction) ? verdict.direction : event.direction,
    horizon: HORIZONS.includes(verdict.horizon) ? verdict.horizon : event.horizon,
    confidence: normalizeConfidence(verdict.confidence ?? event.confidence),
    causal_basis: textList(verdict.causal_basis, 4),
    conditions: textList(verdict.conditions, 4),
    counter_scenarios: textList(verdict.counter_scenarios || verdict.counter_scenario, 4),
    validation_metrics: textList(verdict.validation_metrics, 6),
    source_summary_overlap: Math.round(overlapRatio(conclusion, news && news.summary) * 100) / 100
  };
}

function normalizeMacroAnalysis(rawMacro, event) {
  const raw = rawMacro && typeof rawMacro === 'object' ? rawMacro : {};
  const pricing = raw.market_pricing && typeof raw.market_pricing === 'object' ? raw.market_pricing : {};
  const channels = (Array.isArray(raw.channels) ? raw.channels : []).slice(0, 8).map((item, index) => ({
    id: text(item && item.id, `macro-${index + 1}`),
    name: text(item && (item.name || item.variable), '待判断宏观变量'),
    direction: DIRECTIONS.includes(item && item.direction) ? item.direction : '不确定',
    horizon: HORIZONS.includes(item && item.horizon) ? item.horizon : event.horizon,
    mechanism: text(item && (item.mechanism || item.reason), '传导机制仍需验证。'),
    confidence: normalizeConfidence(item && item.confidence)
  }));
  const marketImpacts = (Array.isArray(raw.market_impacts) ? raw.market_impacts : []).slice(0, 8).map(item => {
    const positiveDrivers = textList(item && (item.positive_drivers || item.upside_drivers), 5);
    const negativeDrivers = textList(item && (item.negative_drivers || item.downside_drivers), 5);
    let direction = DIRECTIONS.includes(item && item.direction) ? item.direction : '不确定';
    if (positiveDrivers.length && negativeDrivers.length && !text(item && item.dominant_condition)) direction = '多空交织';
    return {
      asset: text(item && (item.asset || item.name), '待判断市场'),
      direction,
      horizon: HORIZONS.includes(item && item.horizon) ? item.horizon : event.horizon,
      mechanism: text(item && (item.mechanism || item.reason), '市场影响仍需验证。'),
      positive_drivers: positiveDrivers,
      negative_drivers: negativeDrivers,
      dominant_condition: text(item && item.dominant_condition),
      confidence: normalizeConfidence(item && item.confidence)
    };
  });
  const rawMacroNodes = Array.isArray(raw.macro_chain && raw.macro_chain.nodes) ? raw.macro_chain.nodes : [];
  // 宏观分析必须由模型明确声明 applicable=true。模型仅返回“不适用”的说明文字时，
  // 不能因为 summary 非空就误判成宏观事件并触发整套宏观链校验。
  const applicable = raw.applicable === true;
  const macroChain = normalizeMacroChain(raw.macro_chain, event, channels, marketImpacts, applicable);
  return {
    applicable,
    scope: ['宏观与市场', '行业与产业链', '混合'].includes(raw.scope) ? raw.scope : (applicable ? '混合' : '行业与产业链'),
    summary: text(raw.summary, applicable ? '宏观与市场传导仍需结合事前市场数据验证。' : '本事件暂未识别出显著的全市场宏观传导。'),
    channels,
    market_impacts: marketImpacts,
    macro_chain: macroChain,
    market_pricing: {
      applicable: pricing.applicable !== false && applicable,
      state: PRICING_STATES.includes(pricing.state) ? pricing.state : (applicable ? '无法判断' : '不适用'),
      confidence: normalizeConfidence(pricing.confidence),
      basis: textList(pricing.basis, 5),
      caveat: text(pricing.caveat, '提前定价程度是基于新闻时点以前的市场数据作出的定性判断，不代表精确比例。')
    }
  };
}

function inferMacroNodeType(rawNode) {
  const requested = MACRO_NODE_TYPES.includes(rawNode && rawNode.type) ? rawNode.type : 'real_economy';
  if (requested === 'event') return 'event';
  const content = text(rawNode && `${rawNode.label || rawNode.name || rawNode.variable || ''} ${rawNode.mechanism || rawNode.reason || ''}`);
  if (/风险偏好|估值|折现率|宽基|股市|A股|港股|美股|市场风格|资产价格|成长股|价值股|大类资产/.test(content)) return 'market';
  if (/通胀预期|增长预期|政策预期|政策反应|利率路径|加息预期|降息预期|货币政策|财政政策|金融条件|信用条件|流动性预期/.test(content)) return 'policy_expectation';
  if (/企业成本|投入成本|运输成本|能源成本|原料成本|收入|订单|生产|消费|投资|就业|进出口|CPI|PPI|实际物价|终端价格/.test(content)) return 'real_economy';
  return requested;
}

function macroStage(type) {
  const byType = { event: 0, direct_shock: 1, real_economy: 2, policy_expectation: 3, market: 4 };
  return byType[type] ?? 2;
}

function normalizeMacroChain(rawChain, event, channels, marketImpacts, applicable) {
  if (!applicable) return { nodes: [], edges: [], validation_indicators: [] };
  const chain = rawChain && typeof rawChain === 'object' ? rawChain : {};
  const rawNodes = Array.isArray(chain.nodes) ? chain.nodes : [];
  const ids = new Set(['macro-event']);
  const nodes = [{
    id: 'macro-event', type: 'event', stage: 0,
    label: text(event && event.type, '新闻事件'),
    direction: DIRECTIONS.includes(event && event.direction) ? event.direction : '不确定',
    horizon: HORIZONS.includes(event && event.horizon) ? event.horizon : '不确定',
    impact_level: '待评估', confidence: normalizeConfidence(event && event.confidence),
    mechanism: '宏观传导起点', conditions: [], offsets: []
  }];

  rawNodes.slice(0, 14).forEach((rawNode, index) => {
    if (!rawNode || typeof rawNode !== 'object' || rawNode.type === 'event') return;
    const type = inferMacroNodeType(rawNode);
    let id = text(rawNode.id, `macro-node-${index + 1}`).replace(/[^a-zA-Z0-9_-]/g, '-');
    if (!id || ids.has(id)) id = `macro-node-${index + 1}`;
    ids.add(id);
    nodes.push({
      id, type, stage: macroStage(type),
      label: text(rawNode.label || rawNode.name || rawNode.variable, '待判断变量'),
      direction: DIRECTIONS.includes(rawNode.direction) ? rawNode.direction : '不确定',
      horizon: HORIZONS.includes(rawNode.horizon) ? rawNode.horizon : text(event && event.horizon, '不确定'),
      impact_level: IMPACT_LEVELS.includes(rawNode.impact_level) ? rawNode.impact_level : '待评估',
      confidence: normalizeConfidence(rawNode.confidence),
      mechanism: text(rawNode.mechanism || rawNode.reason, '传导机制仍需验证。'),
      conditions: textList(rawNode.conditions, 4),
      offsets: textList(rawNode.offsets || rawNode.blockers, 4)
    });
  });

  // 兼容旧结果：没有宏观图时，用原有通道和市场影响生成可阅读的基础链条。
  if (nodes.length === 1) {
    channels.slice(0, 6).forEach((item, index) => {
      const id = `macro-channel-${index + 1}`;
      ids.add(id);
      nodes.push({
        id, type: 'real_economy', stage: 2, label: item.name,
        direction: item.direction, horizon: item.horizon, impact_level: '待评估',
        confidence: item.confidence, mechanism: item.mechanism, conditions: [], offsets: []
      });
    });
    marketImpacts.slice(0, 6).forEach((item, index) => {
      const id = `macro-market-${index + 1}`;
      ids.add(id);
      nodes.push({
        id, type: 'market', stage: 4, label: item.asset,
        direction: item.direction, horizon: item.horizon, impact_level: '待评估',
        confidence: item.confidence, mechanism: item.mechanism,
        conditions: item.dominant_condition ? [item.dominant_condition] : [],
        offsets: [...item.positive_drivers, ...item.negative_drivers].slice(0, 4)
      });
    });
  }

  const nodeById = new Map(nodes.map(node => [node.id, node]));
  const rawEdges = Array.isArray(chain.edges) ? chain.edges : [];
  const edges = [];
  const targets = new Set();
  rawEdges.slice(0, 24).forEach(rawEdge => {
    const from = text(rawEdge && rawEdge.from);
    const to = text(rawEdge && rawEdge.to);
    if (!nodeById.has(from) || !nodeById.has(to) || from === to || to === 'macro-event') return;
    if (nodeById.get(from).stage >= nodeById.get(to).stage) return;
    targets.add(to);
    edges.push({
      from, to,
      mechanism: text(rawEdge.mechanism || rawEdge.reason, nodeById.get(to).mechanism),
      direction: DIRECTIONS.includes(rawEdge.direction) ? rawEdge.direction : nodeById.get(to).direction,
      condition: text(rawEdge.condition)
    });
  });
  for (const node of nodes.slice(1)) {
    if (targets.has(node.id)) continue;
    const candidates = nodes.filter(parent => parent.stage < node.stage);
    const parent = candidates.sort((a, b) => b.stage - a.stage)[0] || nodes[0];
    edges.push({ from: parent.id, to: node.id, mechanism: node.mechanism, direction: node.direction, condition: '' });
  }

  const validationIndicators = (Array.isArray(chain.validation_indicators) ? chain.validation_indicators : [])
    .slice(0, 20).map((item, index) => ({
      id: text(item && item.id, `validation-${index + 1}`),
      node_id: nodeById.has(text(item && item.node_id)) ? text(item.node_id) : '',
      indicator: text(item && (item.indicator || item.name), '待补充验证指标'),
      expected_direction: text(item && item.expected_direction, '待判断'),
      observation_window: text(item && item.observation_window, '待确定'),
      purpose: text(item && item.purpose, '用于验证对应传导是否发生。'),
      status: '待验证'
    })).filter(item => item.node_id && item.indicator !== '待补充验证指标');
  return { nodes, edges, validation_indicators: validationIndicators };
}

function normalizeAnalysisScope(rawScope, macroAnalysis, industries) {
  const raw = rawScope && typeof rawScope === 'object' ? rawScope : {};
  const hasMacro = Boolean(macroAnalysis && macroAnalysis.applicable);
  const hasIndustry = Boolean(Array.isArray(industries) && industries.length);
  const inferred = hasMacro && hasIndustry ? '混合型' : hasMacro ? '宏观级' : hasIndustry ? '行业级' : '公司级';
  const level = ANALYSIS_SCOPES.includes(raw.level || raw.scope) ? (raw.level || raw.scope) : inferred;
  return {
    level,
    rationale: text(raw.rationale || raw.reason, level === '宏观级' || level === '混合型'
      ? '事件具有跨行业或全市场传导，需要同时检验宏观变量。'
      : '当前证据主要支持公司或行业层面的经营传导。'),
    direct_objects: textList(raw.direct_objects, 6),
    macro_gate: {
      applicable: raw.macro_gate && typeof raw.macro_gate.applicable === 'boolean'
        ? raw.macro_gate.applicable : hasMacro,
      materiality: text(raw.macro_gate && raw.macro_gate.materiality, hasMacro ? '待评估' : '未达到显著门槛'),
      reasons: textList(raw.macro_gate && raw.macro_gate.reasons, 5)
    }
  };
}

function candidateLookup(candidates) {
  const lookup = new Map();
  for (const candidate of Array.isArray(candidates) ? candidates : []) {
    if (candidate.code) lookup.set(String(candidate.code), candidate);
    if (candidate.name) lookup.set(String(candidate.name), candidate);
    if (candidate.code || candidate.name) lookup.set(`${candidate.code || ''}|${candidate.name || ''}`, candidate);
  }
  return lookup;
}

function normalizeStocks(rawStocks, candidates, industries, directImpacts = []) {
  const rawList = Array.isArray(rawStocks) ? rawStocks : [];
  const rawLookup = new Map();
  for (const stock of rawList) {
    if (!stock || typeof stock !== 'object') continue;
    const code = text(stock.ticker || stock.code);
    const name = text(stock.name || stock.stock_name);
    if (code) rawLookup.set(code, stock);
    if (name) rawLookup.set(name, stock);
    if (code || name) rawLookup.set(`${code}|${name}`, stock);
  }
  const industryById = new Map(industries.map(item => [item.id, item]));
  const industryByName = new Map(industries.map(item => [item.name, item]));
  const directById = new Map(directImpacts.map(item => [item.id, item]));
  const directByName = new Map(directImpacts.map(item => [item.name, item]));
  const seen = new Set();
  const output = [];

  for (const candidate of Array.isArray(candidates) ? candidates : []) {
    const key = `${candidate.code || ''}|${candidate.name || ''}`;
    if (seen.has(key)) continue;
    seen.add(key);
    const raw = rawLookup.get(String(candidate.code)) || rawLookup.get(String(candidate.name)) || rawLookup.get(key) || {};
    const impactType = candidate.impact_type === 'direct' || raw.impact_type === 'direct' ? 'direct' : 'industry';
    const directImpact = impactType === 'direct'
      ? (directById.get(text(candidate.analysis_direct_impact_id || raw.direct_impact_id))
        || directByName.get(text(candidate.analysis_direct_entity_name || raw.direct_entity_name || candidate.name)))
      : null;
    const isListedParent = impactType === 'direct'
      && text(candidate.direct_listing_relation || raw.direct_listing_relation) === 'listed_parent';
    let industry = industryById.get(text(candidate.analysis_industry_id || raw.industry_id));
    if (!industry) industry = industryByName.get(text(candidate.analysis_industry_name || raw.industry_name || candidate.industry));
    if (!industry && impactType === 'industry') industry = industries[0];
    const direction = DIRECTIONS.includes(raw.direction) ? raw.direction
      : directImpact ? directImpact.direction : (industry ? industry.direction : '不确定');
    const confidence = normalizeConfidence(raw.confidence ?? (directImpact && directImpact.confidence) ?? (industry && industry.confidence));
    const score = clamp(raw.screening_score ?? raw.score, 0, 10, 0);
    output.push({
      ticker: text(candidate.code, '代码未提供'),
      code: text(candidate.code, '代码未提供'),
      name: text(candidate.name, '名称未提供'),
      industry: text(candidate.industry || (industry && industry.name), '行业未提供'),
      industry_id: industry ? industry.id : '',
      industry_name: industry ? industry.name : text(candidate.industry, '行业待核验'),
      chain_stage: industry ? industry.chain_stage : 0,
      stage: directImpact ? directImpact.relation : (industry ? industry.name : '直接影响'),
      impact_type: impactType,
      impact_type_label: impactType === 'direct' ? '直接影响' : '产业链传导',
      direct_impact_id: directImpact ? directImpact.id : '',
      direct_entity_name: directImpact ? directImpact.name : '',
      relation: directImpact ? directImpact.relation : '',
      direction,
      confidence,
      impact_level: IMPACT_LEVELS.includes(raw.impact_level) ? raw.impact_level
        : directImpact ? directImpact.impact_level : (industry ? industry.impact_level : '待评估'),
      role: text(raw.role || raw.reason, directImpact
        ? isListedParent
          ? `${candidate.name}是事件直接主体${directImpact.name}的上市母公司；${directImpact.mechanism}`
          : `${directImpact.name}是本次事件的${directImpact.relation}；${directImpact.mechanism}`
        : industry
        ? `iFinD 将该标的归入${industry.name}；本次传导中该行业的作用为：${industry.role}。公司自身业务暴露仍需核验。`
        : '该标的属于相关行业，但具体业务暴露仍需核验。'),
      reason: text(raw.reason || raw.role, directImpact ? directImpact.mechanism
        : industry ? industry.reason : '事件直接相关性仍需核验。'),
      selection_basis: directImpact
        ? isListedParent
          ? `新闻直接主体${directImpact.name}的上市母公司映射：${candidate.name}`
          : `新闻事件直接参与方：${directImpact.relation}`
        : text(industry && industry.stock_expansion_basis, '经营变量通过产业链传导至该行业。'),
      screening_score: score,
      tier: text(raw.tier, '一般观察'),
      screening_reasons: textList(raw.screening_reasons, 5),
      risks: textList(raw.risks || raw.counter_factors, 5).length
        ? textList(raw.risks || raw.counter_factors, 5)
        : (directImpact ? directImpact.risks : []),
      data_source: text(candidate.data_source, 'iFinD'),
      evidence_source_ids: directImpact ? directImpact.evidence_source_ids : ['news-1']
    });
  }
  return output.sort((a, b) => Number(b.impact_type === 'direct') - Number(a.impact_type === 'direct'));
}

function validateAnalysis(analysis, news) {
  const verdict = analysis && analysis.verdict;
  if (!verdict || !verdict.conclusion || verdict.conclusion.length < 20) {
    throw invalidAnalysis('缺少可展示的推演结论');
  }
  if (!analysis.macro_analysis || !analysis.macro_analysis.market_pricing) {
    throw invalidAnalysis('缺少宏观适用性判断');
  }
  const warnings = [];
  if (verdict.conclusion.length < 80 || verdict.conclusion.length > 220) warnings.push('推演结论长度未达到建议范围');
  if (!verdict.conditions.length) warnings.push('未单列成立条件');
  if (!verdict.counter_scenarios.length) warnings.push('未单列反向情景');
  if (verdict.validation_metrics.length < 2) warnings.push('验证指标少于两项');
  if (overlapRatio(verdict.conclusion, news && news.summary) > 0.82) warnings.push('推演结论与新闻摘要重合度偏高');
  if (analysis.macro_analysis.applicable) {
    const macroChain = analysis.macro_analysis.macro_chain;
    if (!macroChain || macroChain.nodes.length < 2 || !macroChain.edges.length || !macroChain.validation_indicators.length) {
      warnings.push('宏观传导链不完整');
    }
    const nodeTypes = new Set((macroChain && macroChain.nodes || []).map(node => node.type));
    if (!nodeTypes.has('direct_shock')) warnings.push('宏观传导缺少直接冲击节点');
    const macroText = [
      analysis.verdict && analysis.verdict.conclusion,
      analysis.macro_analysis.summary,
      ...analysis.macro_analysis.channels.map(item => `${item.name} ${item.mechanism}`),
      ...macroChain.nodes.map(node => `${node.label} ${node.mechanism}`)
    ].map(item => text(item)).join(' ');
    if (/企业成本|投入成本|运输成本|能源成本|原料成本|收入|订单|生产|消费|投资|就业|进出口|CPI|PPI|实际物价|终端价格/.test(macroText)
      && !nodeTypes.has('real_economy')) warnings.push('宏观传导缺少实体经济节点');
    if (/通胀预期|增长预期|政策预期|政策反应|利率路径|加息预期|降息预期|货币政策|财政政策|金融条件|信用条件|流动性预期/.test(macroText)
      && !nodeTypes.has('policy_expectation')) warnings.push('宏观传导缺少政策或预期节点');
    if (analysis.macro_analysis.market_impacts.length
      || /风险偏好|估值|折现率|宽基|股市|A股|港股|美股|市场风格|资产价格|成长股|价值股|大类资产/.test(macroText)) {
      if (!nodeTypes.has('market')) warnings.push('宏观传导缺少市场影响节点');
    }
  }
  const goldImpacts = analysis.macro_analysis.market_impacts.filter(item => /黄金|金价|贵金属/.test(item.asset));
  if (goldImpacts.some(item => !item.positive_drivers.length || !item.negative_drivers.length || !['多空交织', '不确定'].includes(item.direction))) {
    warnings.push('黄金影响未完整呈现双向驱动');
  }
  if (analysis.industries.some(item => !isIndustryNodeName(item.name))) throw invalidAnalysis('行业节点包含非行业对象');
  const hasIndustryPath = Boolean(analysis.industries.length && analysis.industry_chain.edges.length);
  const hasDirectImpact = Boolean(Array.isArray(analysis.direct_impacts) && analysis.direct_impacts.length);
  if (!hasIndustryPath && !hasDirectImpact && !analysis.macro_analysis.applicable) {
    throw invalidAnalysis('没有识别出直接影响对象、行业传导或宏观传导');
  }
  analysis.validation_warnings = warnings;
  return analysis;
}

function createAnalysisService(options = {}) {
  const baseUrl = text(options.baseUrl, 'https://api.deepseek.com').replace(/\/+$/, '');
  const model = text(options.model, 'deepseek-chat');
  const getApiKey = typeof options.getApiKey === 'function' ? options.getApiKey : () => '';
  const sourceCatalog = typeof options.sourceCatalogFromNews === 'function' ? options.sourceCatalogFromNews : () => [];
  const prompt = fs.readFileSync(PROMPT_FILE, 'utf8');

  function normalize(raw, news, candidates) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) throw new Error('AI_INVALID_JSON');
    const rawEvent = raw.event && typeof raw.event === 'object' ? raw.event : {};
    const event = {
      type: text(rawEvent.type || raw.event_type, '待判断'),
      direction: DIRECTIONS.includes(rawEvent.direction) ? rawEvent.direction : '不确定',
      horizon: HORIZONS.includes(rawEvent.horizon || raw.overall_horizon) ? (rawEvent.horizon || raw.overall_horizon) : '不确定',
      confidence: normalizeConfidence(rawEvent.confidence),
      key_variables: textList(rawEvent.key_variables || raw.key_variables, 8)
    };
    const industries = normalizeIndustries(raw.industries);
    const directImpacts = normalizeDirectImpacts(raw.direct_impacts || raw.direct_entities || raw.entity_impacts);
    const verdict = normalizeVerdict(raw, event, news);
    const macroAnalysis = normalizeMacroAnalysis(raw.macro_analysis, event);
    const analysisScope = normalizeAnalysisScope(raw.analysis_scope, macroAnalysis, industries);
    event.direction = verdict.direction;
    event.horizon = verdict.horizon;
    event.confidence = verdict.confidence;
    const industryChain = normalizeIndustryChain(raw.industry_chain, industries, event.type, verdict.direction);
    const stocks = normalizeStocks(raw.candidate_stocks || raw.stocks, candidates, industries, directImpacts);
    const sources = sourceCatalog(news);
    return {
      news: {
        canonical_title: text(news && news.title, '新闻标题未提供'),
        summary: text(news && news.summary, '新闻摘要未提供。'),
        event_time: text(news && (news.time || news.published_at), '时间未提供'),
        sources
      },
      summary: text(news && news.summary, '新闻摘要未提供。'),
      fact_summary: [text(news && news.summary, '新闻摘要未提供。')],
      analysis_scope: analysisScope,
      verdict,
      macro_analysis: macroAnalysis,
      event,
      direct_impacts: directImpacts,
      industries,
      industry_chain: industryChain,
      impact_chain: industryChain.edges.map((edge, index) => ({
        order: index + 1,
        title: industryChain.nodes.find(node => node.id === edge.to)?.label || '行业传导',
        detail: edge.mechanism,
        direction: edge.direction,
        from: edge.from,
        to: edge.to,
        evidence_source_ids: ['news-1']
      })),
      candidate_stocks: stocks,
      screened_stocks: stocks,
      stocks,
      kline: [],
      uncertainties: textList(raw.uncertainties, 8).length ? textList(raw.uncertainties, 8) : ['结论仍需结合后续公告、行业数据和行情验证。'],
      sources,
      risk_notice: text(raw.risk_notice, '本结果用于研究整理，不构成投资建议。'),
      analysis_basis: text(news && (news.full_text || news.content)) ? 'full_text' : 'summary_only'
    };
  }

  async function requestDeepSeekAnalysis(news, candidates, preliminary = null) {
    const apiKey = text(getApiKey());
    if (!apiKey) throw new Error('AI_NOT_CONFIGURED');
    const input = {
      news: {
        title: text(news && news.title),
        summary: text(news && news.summary).slice(0, 5000),
        full_text: text(news && (news.full_text || news.content)).slice(0, 18000),
        source: text(news && news.source),
        published_at: text(news && (news.time || news.published_at)),
        url: text(news && news.url),
        sources: sourceCatalog(news)
      },
      market_context: news && news.market_context ? news.market_context : null,
      preliminary_industry_analysis: preliminary ? {
        verdict: preliminary.verdict,
        event: preliminary.event,
        industries: preliminary.industries,
        industry_chain: preliminary.industry_chain,
        direct_impacts: preliminary.direct_impacts
      } : null,
      stock_candidates: (Array.isArray(candidates) ? candidates : []).map(candidate => ({
        ticker: text(candidate.code),
        name: text(candidate.name),
        industry: text(candidate.industry),
        analysis_industry_id: text(candidate.analysis_industry_id),
        analysis_industry_name: text(candidate.analysis_industry_name),
        impact_type: text(candidate.impact_type),
        analysis_direct_impact_id: text(candidate.analysis_direct_impact_id)
      }))
    };

    async function callOnce(repairContext = null) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 45000);
      try {
        const response = await fetch(`${baseUrl}/chat/completions`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${apiKey}` },
          body: JSON.stringify({
            model,
            thinking: { type: 'disabled' },
            messages: [
              { role: 'system', content: prompt },
              { role: 'user', content: repairContext
                ? `上一次输出没有通过核心结构校验，失败原因是：${repairContext.reason}。请修正后重新返回完整 JSON，不要省略其他字段。\n待分析输入：\n${JSON.stringify(input, null, 2)}\n上一次输出：\n${repairContext.content}`
                : `请分析下面的 JSON，并严格返回规定结构的 JSON：\n${JSON.stringify(input, null, 2)}` }
            ],
            response_format: { type: 'json_object' },
            temperature: 0.15,
            max_tokens: 7000
          }),
          signal: controller.signal
        });
        if (!response.ok) throw new Error('AI_PROVIDER_ERROR');
        const body = await response.json();
        const content = body && body.choices && body.choices[0] && body.choices[0].message && body.choices[0].message.content;
        try {
          return validateAnalysis(normalize(parseJson(content), news, candidates), news);
        } catch (error) {
          if (['AI_INVALID_JSON', 'AI_INVALID_ANALYSIS'].includes(error && error.message)) {
            error.invalidContent = text(content).slice(0, 18000);
          }
          throw error;
        }
      } catch (error) {
        if (error && error.name === 'AbortError') throw new Error('AI_TIMEOUT');
        throw error;
      } finally {
        clearTimeout(timeout);
      }
    }

    let lastError;
    let repairContext = null;
    for (let attempt = 1; attempt <= 3; attempt += 1) {
      try { return await callOnce(repairContext); } catch (error) {
        lastError = error;
        repairContext = {
          reason: text(error && error.validationReason, analysisErrorCode(error)),
          content: text(error && error.invalidContent)
        };
        if (!['AI_INVALID_JSON', 'AI_INVALID_ANALYSIS'].includes(error && error.message) || attempt === 3) throw error;
      }
    }
    throw lastError;
  }

  function attachCandidates(preliminary, candidates) {
    if (!preliminary || !Array.isArray(preliminary.industries)) throw new Error('AI_INVALID_ANALYSIS');
    const stocks = normalizeStocks([], candidates, preliminary.industries, preliminary.direct_impacts);
    return {
      ...preliminary,
      uncertainties: (Array.isArray(preliminary.uncertainties) ? preliminary.uncertainties : [])
        .filter(item => !/候选股票.*为空|输入候选.*为空|stock_candidates.*为空|无法给出个股/i.test(text(item))),
      candidate_stocks: stocks,
      screened_stocks: stocks,
      stocks,
      kline: []
    };
  }

  function fallbackAnalysisFromNews(news, candidates, error, preliminary = null) {
    const baseIndustries = preliminary && Array.isArray(preliminary.industries) ? preliminary.industries : [];
    const industries = normalizeIndustries(baseIndustries);
    const directImpacts = normalizeDirectImpacts(preliminary && preliminary.direct_impacts);
    const event = preliminary && preliminary.event ? preliminary.event : {
      type: '待判断', direction: '不确定', horizon: '不确定', confidence: 0, key_variables: []
    };
    const macroAnalysis = preliminary && preliminary.macro_analysis ? preliminary.macro_analysis : {
      applicable: false,
      scope: '行业与产业链',
      summary: '当前结构化分析未能形成可验证的宏观与市场判断。',
      channels: [], market_impacts: [], macro_chain: { nodes: [], edges: [], validation_indicators: [] },
      market_pricing: { applicable: false, state: '无法判断', confidence: 0, basis: [], caveat: '缺少有效的事前市场分析结果。' }
    };
    const verdict = preliminary && preliminary.verdict ? preliminary.verdict : {
      headline: '分析暂未完成',
      conclusion: '当前模型没有返回符合限制性结构的推演结论，因此不展示未经校验的方向判断。请稍后重试，并结合后续行业数据验证。',
      direction: '不确定', horizon: '不确定', confidence: 0,
      causal_basis: [], conditions: ['需要获得有效的结构化分析结果'],
      counter_scenarios: ['现有信息不足以排除相反影响'], validation_metrics: ['后续公告', '行业价格或供需数据'],
      source_summary_overlap: 0
    };
    const chain = preliminary && preliminary.industry_chain
      ? preliminary.industry_chain : normalizeIndustryChain(null, industries, event.type, verdict.direction);
    const stocks = normalizeStocks([], candidates, industries, directImpacts);
    const sources = sourceCatalog(news);
    const analysisScope = preliminary && preliminary.analysis_scope
      ? preliminary.analysis_scope : normalizeAnalysisScope(null, macroAnalysis, industries);
    return {
      news: { canonical_title: text(news && news.title, '新闻标题未提供'), summary: text(news && news.summary, '新闻摘要未提供。'), event_time: text(news && (news.time || news.published_at), '时间未提供'), sources },
      summary: text(news && news.summary, '新闻摘要未提供。'),
      fact_summary: [text(news && news.summary, '新闻摘要未提供。')],
      analysis_scope: analysisScope,
      verdict, macro_analysis: macroAnalysis, event, direct_impacts: directImpacts, industries, industry_chain: chain,
      impact_chain: chain.edges || [],
      candidate_stocks: stocks, screened_stocks: stocks, stocks, kline: [],
      uncertainties: [`结构化分析暂时失败（${analysisErrorCode(error)}），当前结果不得作为确定性判断。`],
      sources,
      risk_notice: '当前为受限兜底结果，不构成投资建议。',
      analysis_basis: text(news && (news.full_text || news.content)) ? 'full_text' : 'summary_only',
      fallback: true
    };
  }

  return { requestDeepSeekAnalysis, attachCandidates, fallbackAnalysisFromNews, analysisErrorCode };
}

module.exports = {
  createAnalysisService,
  analysisErrorCode,
  __test: { normalizeIndustries, normalizeDirectImpacts, normalizeStocks }
};
