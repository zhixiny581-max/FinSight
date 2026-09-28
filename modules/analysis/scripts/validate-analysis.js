#!/usr/bin/env node

const fs = require('fs');

const file = process.argv[2];
if (!file) {
  console.error('用法: node validate-analysis.js analysis.json');
  process.exit(2);
}

const data = JSON.parse(fs.readFileSync(file, 'utf8'));
const errors = [];
const directions = ['利好', '利空', '多空交织', '不确定'];
const scopes = ['公司级', '行业级', '宏观级', '混合型'];
const macroNodeTypes = ['event', 'direct_shock', 'real_economy', 'policy_expectation', 'market'];
const macroStages = { event: 0, direct_shock: 1, real_economy: 2, policy_expectation: 3, market: 4 };

if (!data.news || typeof data.news.summary !== 'string') errors.push('news.summary 缺失');
if (!data.verdict || typeof data.verdict.conclusion !== 'string') errors.push('verdict.conclusion 缺失');
else if (data.verdict.conclusion.length < 80 || data.verdict.conclusion.length > 220) errors.push('verdict.conclusion 必须为80至220个字符');
else if (/(反向风险|反向情景)/.test(data.verdict.conclusion)) errors.push('verdict.conclusion 只能写主情景，反向内容应放入 counter_scenarios');
if (!data.macro_analysis || typeof data.macro_analysis !== 'object') errors.push('macro_analysis 缺失');
if (data.macro_analysis && !data.macro_analysis.market_pricing) errors.push('macro_analysis.market_pricing 缺失');
if (!data.analysis_scope || !scopes.includes(data.analysis_scope.level)) errors.push('analysis_scope.level 无效');
if (data.macro_analysis && data.macro_analysis.applicable) {
  const chain = data.macro_analysis.macro_chain;
  if (!chain || !Array.isArray(chain.nodes) || !Array.isArray(chain.edges) || !Array.isArray(chain.validation_indicators)) errors.push('宏观事件缺少 macro_chain');
  if ((chain && chain.nodes || []).some(node => !macroNodeTypes.includes(node.type))) errors.push('macro_chain.node.type 无效');
  if ((chain && chain.nodes || []).some(node => macroStages[node.type] !== node.stage)) errors.push('macro_chain.node.stage 与节点类型不一致');
  const nodeTypes = new Set((chain && chain.nodes || []).map(node => node.type));
  if (!nodeTypes.has('direct_shock')) errors.push('宏观链条必须包含直接冲击节点');
  const macroText = [
    data.verdict && data.verdict.conclusion,
    data.macro_analysis.summary,
    ...(data.macro_analysis.channels || []).map(item => `${item.name || ''} ${item.mechanism || ''}`),
    ...(chain && chain.nodes || []).map(node => `${node.label || ''} ${node.mechanism || ''}`)
  ].filter(Boolean).join(' ');
  if (/企业成本|投入成本|运输成本|能源成本|原料成本|收入|订单|生产|消费|投资|就业|进出口|CPI|PPI|实际物价|终端价格/.test(macroText) && !nodeTypes.has('real_economy')) errors.push('分析提及实体传导但缺少一阶实体影响节点');
  if (/通胀预期|增长预期|政策预期|政策反应|利率路径|加息预期|降息预期|货币政策|财政政策|金融条件|信用条件|流动性预期/.test(macroText) && !nodeTypes.has('policy_expectation')) errors.push('分析提及政策或预期反馈但缺少二阶节点');
  if (((data.macro_analysis.market_impacts || []).length || /风险偏好|估值|折现率|宽基|股市|A股|港股|美股|市场风格|资产价格|成长股|价值股|大类资产/.test(macroText)) && !nodeTypes.has('market')) errors.push('分析提及市场影响但缺少市场节点');
  const nodeById = new Map((chain && chain.nodes || []).map(node => [node.id, node]));
  if ((chain && chain.edges || []).some(edge => !nodeById.has(edge.from) || !nodeById.has(edge.to) || nodeById.get(edge.from).stage >= nodeById.get(edge.to).stage)) errors.push('macro_chain.edges 必须从较早层级指向较晚层级');
  if ((chain && chain.validation_indicators || []).some(item => item.status !== '待验证')) errors.push('宏观验证指标生成时只能是待验证');
}
if (!directions.includes(data.verdict && data.verdict.direction)) errors.push('verdict.direction 无效');
if (!Array.isArray(data.verdict && data.verdict.conditions) || !data.verdict.conditions.length) errors.push('verdict.conditions 至少一项');
if (!Array.isArray(data.verdict && data.verdict.counter_scenarios) || !data.verdict.counter_scenarios.length) errors.push('verdict.counter_scenarios 至少一项');
if (!Array.isArray(data.verdict && data.verdict.validation_metrics) || data.verdict.validation_metrics.length < 2) errors.push('verdict.validation_metrics 至少两项');
if (!Array.isArray(data.industries)) errors.push('industries 必须是数组');
if (!Array.isArray(data.direct_impacts)) errors.push('direct_impacts 必须是数组');
if (!data.industry_chain || !Array.isArray(data.industry_chain.nodes) || !Array.isArray(data.industry_chain.edges)) errors.push('industry_chain 结构缺失');
if (Array.isArray(data.industries) && !data.industries.length
  && !(data.direct_impacts || []).length
  && !(data.macro_analysis && data.macro_analysis.applicable)) errors.push('无直接对象和行业路径时 macro_analysis.applicable 必须为 true');
if ((data.industry_chain && data.industry_chain.nodes || []).some(node => !['event', 'industry'].includes(node.type))) errors.push('industry_chain 不能包含公司节点');
if ((data.industries || []).some(item => /^(黄金|金价|美元|美元指数|利率|实际利率|原油|油价|债券|美债|国债|A股|全A|全球股市)$/.test(String(item.name || '').trim()))) errors.push('industries 不能包含资产或宏观变量节点');
for (const item of data.macro_analysis && data.macro_analysis.market_impacts || []) {
  if (/黄金|金价|贵金属/.test(String(item.asset || ''))
    && (!Array.isArray(item.positive_drivers) || !item.positive_drivers.length
      || !Array.isArray(item.negative_drivers) || !item.negative_drivers.length
      || !['多空交织', '不确定'].includes(item.direction))) {
    errors.push('黄金影响必须同时列出上行和下行驱动，并标记为多空交织或不确定');
  }
}
if (data.macro_market && data.macro_market.analysis_mode !== 'ex_ante') errors.push('macro_market 必须是 ex_ante');
if (data.macro_market && Array.isArray(data.macro_market.bars) && data.macro_market.market_data_cutoff && data.macro_market.bars.some(bar => bar.date > data.macro_market.market_data_cutoff)) errors.push('macro_market 包含截止日之后的数据');

const industryIds = new Set((data.industries || []).map(item => item.id));
const directImpactIds = new Set((data.direct_impacts || []).map(item => item.id));
for (const stock of data.candidate_stocks || []) {
  if (!stock.code || !stock.name) errors.push('股票缺少代码或名称');
  if (stock.impact_type === 'direct') {
    if (!directImpactIds.has(stock.direct_impact_id)) errors.push(`${stock.code || stock.name} 未关联有效直接影响对象`);
  } else if (!industryIds.has(stock.industry_id)) errors.push(`${stock.code || stock.name} 未关联有效行业节点`);
}

if (errors.length) {
  console.error(errors.map(error => `- ${error}`).join('\n'));
  process.exit(1);
}
console.log('智能分析结果检查通过');

