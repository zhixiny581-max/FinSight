#!/usr/bin/env node

const fs = require('fs');

const file = process.argv[2];
if (!file) {
  console.error('用法: node validate-analysis.js analysis.json');
  process.exit(2);
}

let data;
try {
  data = JSON.parse(fs.readFileSync(file, 'utf8'));
} catch (error) {
  console.error(`JSON读取失败: ${error.message}`);
  process.exit(1);
}

const errors = [];
const requiredArrays = ['industries', 'candidate_stocks', 'screened_stocks', 'uncertainties'];
for (const key of requiredArrays) {
  if (!Array.isArray(data[key])) errors.push(`${key} 必须是数组`);
}

if (!data.news || typeof data.news.summary !== 'string') errors.push('news.summary 缺失');
if (!Array.isArray(data.news?.sources)) errors.push('news.sources 必须是数组');
if (!Array.isArray(data.impact_chain) || data.impact_chain.length < 2) {
  errors.push('impact_chain 至少需要2个步骤');
}

for (const [index, source] of (data.news?.sources || []).entries()) {
  if (!source.title || !source.publisher || !source.url) errors.push(`来源${index + 1}缺少标题、来源或链接`);
}

for (const [index, stock] of data.screened_stocks.entries()) {
  if (!stock.code || !stock.name || typeof stock.score !== 'number' || !stock.tier) {
    errors.push(`screened_stocks[${index}] 缺少代码、名称、分数或层级`);
  }
}

if (!data.risk_notice) errors.push('risk_notice 缺失');

if (errors.length) {
  console.error(errors.map((error) => `- ${error}`).join('\n'));
  process.exit(1);
}

console.log('分析结果结构检查通过');
