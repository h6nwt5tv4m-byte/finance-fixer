import {rankedName} from './auditor-names.mjs?v=20261121-share';

export function auditMarket(institutions, contracts, year, metric) {
  const firms = new Map();
  const other = {name:'개인·기타 공시 명의', value:0, records:[]};
  const seenContracts = new Set();
  const covered = new Set();
  let total = 0;
  let units = 0;

  function add(org, original, value, contract = null) {
    const name = rankedName(original);
    if (name && !firms.has(name)) firms.set(name, {name, value:0, records:[]});
    const firm = name ? firms.get(name) : other;
    firm.records.push({org, original, value, contract});
    firm.value += value;
    covered.add(org.id);
    units++;
    total += value;
  }

  for (const org of institutions) {
    if (metric !== 'amount') {
      const history = org.history?.find(h => h.year === year);
      if (history?.auditor?.trim()) add(org, history.auditor, 1);
      continue;
    }
    for (const id of [org.currentContract, org.latestContract]) {
      const c = contracts[id];
      if (!c || seenContracts.has(id) || c.joint || c.institutionIds?.length !== 1 || c.institutionIds[0] !== org.id) continue;
      if (c.years !== String(year) || !['회계/사업연도 명시','기관 원문 명시'].includes(c.yearBasis)) continue;
      if (!c.party?.trim() || !Number.isSafeInteger(c.total) || c.total <= 0) continue;
      seenContracts.add(id);
      add(org, c.party, c.total, c);
    }
  }
  const ranked = [...firms.values()].sort((a,b) => b.value - a.value || a.name.localeCompare(b.name,'ko'));
  return {ranked, other, total, units, covered:covered.size, scope:institutions.length};
}
