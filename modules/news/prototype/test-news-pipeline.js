const assert = require('assert');
const pipeline = require('./server');

assert.deepStrictEqual(pipeline.FIXED_NEWS_TAGS, ['宏观级', '行业级', '公司级', '混合级']);
assert.strictEqual(pipeline.DOMESTIC_NEWS_QUERIES.length, 3);
assert.strictEqual(pipeline.INTERNATIONAL_NEWS_QUERIES.length, 6);
assert.strictEqual(pipeline.SUPPLEMENTAL_NEWS_QUERIES.length, 3);
assert.strictEqual(pipeline.NEWS_CANDIDATE_TARGET_PER_DAY, 12);
assert.strictEqual(pipeline.NEWS_CANDIDATE_LIMIT_PER_DAY, 20);
assert.strictEqual(pipeline.NEWS_FINAL_LIMIT_PER_DAY, 10);
assert.strictEqual(pipeline.NEWS_QUALITY_BATCH_SIZE, 12);

assert.strictEqual(pipeline.normalizeNewsCategory('宏观政策'), '宏观级');
assert.strictEqual(pipeline.normalizeNewsCategory('商品与供应链'), '行业级');
assert.strictEqual(pipeline.normalizeNewsCategory('财报业绩'), '公司级');
assert.strictEqual(pipeline.normalizeNewsCategory('公司事件'), '公司级');
assert.strictEqual(pipeline.normalizeNewsCategory('行业动态'), '行业级');

const dates = pipeline.recentShanghaiDates(3);
assert.strictEqual(dates.length, 3);
assert.ok(dates.every(date => /^\d{4}-\d{2}-\d{2}$/.test(date)));
assert.strictEqual((Date.parse(`${dates[0]}T00:00:00+08:00`) - Date.parse(`${dates[2]}T00:00:00+08:00`)) / 86400000, 2);

const identityA = pipeline.newsUniqueId({
  title: '同一新闻', source: '来源甲', published_at: '2026-09-28',
  url: 'https://example.com/news/1?utm_source=test&from=feed#part'
});
const identityB = pipeline.newsUniqueId({
  title: '改写标题', source: '来源乙', published_at: '2026-09-27',
  url: 'https://EXAMPLE.com/news/1'
});
assert.strictEqual(identityA, identityB);

const passingQuality = pipeline.normalizeCachedQuality({
  content_type: '事实新闻', quality_score: 70, a_share_relevance: 4, factuality: 4, materiality: 3,
  category: '混合级', reject_reason: '', core_event: '原油供应中断', subjects: ['主体甲'],
  event_date: '2026-09-28', impact_targets: ['原油', '航运']
});
assert.strictEqual(pipeline.qualityPassed(passingQuality), true);
assert.strictEqual(pipeline.qualityPassed({ ...passingQuality, quality_score: 69 }), false);
const opinionReport = {
  title: '宏观周报：利率主导市场定价',
  summary: '我们认为市场短期焦点仍是美债利率，建议关注相关配置机会。',
  full_text: '本周数据回顾后给出市场展望。'
};
assert.ok(pipeline.deterministicQualityRejectReason(opinionReport));
assert.strictEqual(pipeline.qualityPassed(passingQuality, opinionReport), false);

function eventItem(overrides = {}) {
  return {
    id: overrides.id || 'news-a',
    title: overrides.title || '权威机构公布原油供应中断进展',
    summary: overrides.summary || '权威机构确认供应中断，原油与航运成本可能受影响。',
    full_text: overrides.full_text || '正文包含事件主体、日期与供应变化。',
    source: overrides.source || '普通媒体',
    source_authority: overrides.source_authority || 'other',
    published_at: overrides.published_at || '2026-09-28',
    published_precision: 'date',
    url: overrides.url || 'https://example.com/a',
    category: '混合级', tags: ['混合级'],
    sources: [{ title: overrides.title || '报道', publisher: overrides.source || '普通媒体', published_at: '2026-09-28', url: overrides.url || 'https://example.com/a' }],
    deepseek_quality: {
      ...passingQuality,
      core_event: overrides.core_event || '原油供应中断进展',
      subjects: overrides.subjects || ['主体甲'],
      impact_targets: overrides.impact_targets || ['原油', '航运']
    }
  };
}

const duplicateResult = pipeline.deduplicateProcessedNews([
  eventItem(),
  eventItem({ id: 'news-b', title: '监管机构通报原油供应中断', source: '国务院', source_authority: 'official', url: 'https://gov.cn/b' })
]);
assert.strictEqual(duplicateResult.items.length, 1);
assert.strictEqual(duplicateResult.duplicate_count, 1);
assert.strictEqual(duplicateResult.items[0].source, '国务院');
assert.strictEqual(duplicateResult.items[0].sources.length, 2);
assert.deepStrictEqual(Object.keys(duplicateResult.items[0].importance_breakdown), ['freshness', 'authority', 'materiality', 'directness', 'evidence', 'coverage']);

const distinctResult = pipeline.deduplicateProcessedNews([
  eventItem(),
  eventItem({ id: 'news-c', core_event: '央行公布新的利率决议', subjects: ['央行'], impact_targets: ['利率', '汇率'], url: 'https://example.com/c' })
]);
assert.strictEqual(distinctResult.items.length, 2);

assert.strictEqual(pipeline.stockMatchesDirectEntity('惠科', { name: '惠科股份' }), true);
assert.strictEqual(pipeline.stockMatchesDirectEntity('惠科', { name: '京东方A' }), false);
assert.strictEqual(pipeline.stockMatchesListedParent('TCL华星', { name: 'TCL科技' }), true);
assert.strictEqual(pipeline.stockMatchesListedParent('TCL华星', { name: '京东方A' }), false);
const verificationTarget = {
  direct_impacts: [{ id: 'direct-hkc', name: '惠科', entity_type: '非上市公司', listed_status: '未上市', stock_lookup_allowed: false }]
};
pipeline.applyDirectListingVerification(verificationTarget, [{
  code: '001399.SZ', name: '惠科股份', analysis_direct_impact_id: 'direct-hkc',
  analysis_direct_entity_name: '惠科', data_source: 'iFinD get_stock_info（事件直接参与方核验）'
}]);
assert.strictEqual(verificationTarget.direct_impacts[0].ticker, '001399.SZ');
assert.strictEqual(verificationTarget.direct_impacts[0].listed_status, '已上市');
assert.strictEqual(verificationTarget.direct_impacts[0].entity_type, '上市公司');
assert.strictEqual(verificationTarget.direct_impacts[0].stock_lookup_allowed, true);

const listedParentTarget = {
  direct_impacts: [{ id: 'direct-tcl', name: 'TCL华星', entity_type: '上市公司', listed_status: '待核验', stock_lookup_allowed: true }]
};
pipeline.applyDirectListingVerification(listedParentTarget, [{
  code: '000100.SZ', name: 'TCL科技', direct_listing_relation: 'listed_parent',
  analysis_direct_impact_id: 'direct-tcl', analysis_direct_entity_name: 'TCL华星',
  data_source: 'iFinD get_stock_info（事件直接参与方核验）'
}]);
assert.strictEqual(listedParentTarget.direct_impacts[0].ticker, '');
assert.strictEqual(listedParentTarget.direct_impacts[0].listed_status, '未独立上市');
assert.strictEqual(listedParentTarget.direct_impacts[0].entity_type, '非上市公司');
assert.strictEqual(listedParentTarget.direct_impacts[0].listed_proxy_name, 'TCL科技');
assert.strictEqual(listedParentTarget.direct_impacts[0].listed_proxy_ticker, '000100.SZ');

console.log('news pipeline tests passed');
