const assert = require('assert');
const { __test } = require('./analysis_service');

const industries = __test.normalizeIndustries([{
  id: 'construction',
  name: '建筑装饰',
  role: '收购方原所属行业',
  direction: '不确定',
  stock_expansion_allowed: false,
  stock_expansion_basis: ''
}]);
assert.strictEqual(industries[0].stock_expansion_allowed, false);

const directImpacts = __test.normalizeDirectImpacts([{
  id: 'acquirer',
  name: '杭州园林',
  entity_type: '上市公司',
  listed_status: '已上市',
  relation: '收购方',
  direction: '多空交织',
  confidence: 72,
  mechanism: '跨界收购改变业务结构，同时存在整合与估值风险。',
  risks: ['交易终止', '整合不及预期']
}]);
assert.strictEqual(directImpacts[0].stock_lookup_allowed, true);

const stocks = __test.normalizeStocks([], [{
  code: '300649.SZ',
  name: '杭州园林',
  industry: '建筑装饰',
  impact_type: 'direct',
  analysis_direct_impact_id: 'acquirer',
  data_source: 'test'
}], industries, directImpacts);

assert.strictEqual(stocks.length, 1);
assert.strictEqual(stocks[0].impact_type, 'direct');
assert.strictEqual(stocks[0].direct_impact_id, 'acquirer');
assert.strictEqual(stocks[0].industry_id, 'construction');
assert.strictEqual(stocks[0].stage, '收购方');
assert.strictEqual(stocks[0].direction, '多空交织');
assert.match(stocks[0].selection_basis, /直接参与方/);

console.log('analysis service tests passed');
