(() => {
  const search = document.getElementById('search');
  const sort = document.getElementById('sort');
  const count = document.getElementById('count');
  const results = document.getElementById('results');
  const body = document.getElementById('firms');
  const decimal = new Intl.NumberFormat('ko-KR', {minimumFractionDigits: 1, maximumFractionDigits: 1});
  const number = new Intl.NumberFormat('ko-KR', {maximumFractionDigits: 1});
  const names = new Intl.Collator('ko');
  const normalize = text => text.normalize('NFC').replace(/\s+/g, '').toLocaleLowerCase('ko');
  const average = firm => firm.personMonths / firm.months;
  const annualLoss = firm => firm.months === 12 ? firm.lost / average(firm) : null;
  const descending = {
    revenue: firm => firm.revenue,
    average,
    loss: firm => annualLoss(firm) ?? -1
  };
  let firms = [];

  function cell(row, label, value) {
    const td = row.insertCell();
    td.dataset.label = label;
    td.append(value);
    return td;
  }

  function detail(parent, text) {
    const small = document.createElement('small');
    small.textContent = text;
    parent.append(small);
  }

  function firmRow(firm) {
    const row = document.createElement('tr');
    const heading = document.createElement('th');
    heading.scope = 'row';
    const filing = document.createElement('a');
    filing.href = 'https://dart.fss.or.kr/dsaf001/main.do?rcpNo=' + firm.receipt;
    filing.textContent = firm.name;
    filing.setAttribute('aria-label', firm.name + ' DART 사업보고서');
    heading.append(filing);
    row.append(heading);
    const revenue = cell(row, '매출 (억원)', decimal.format(firm.revenue / 100000000));
    detail(revenue, firm.start + ' ~ ' + firm.end);
    cell(row, '평균 가입자', number.format(average(firm)) + '명');
    cell(row, '신규취득', number.format(firm.gained) + '건');
    cell(row, '상실', number.format(firm.lost) + '건');
    const loss = annualLoss(firm);
    const ratio = cell(row, '연간 상실 비율', loss === null ? '미산출' : decimal.format(loss * 100) + '%');
    if (loss === null) detail(ratio, firm.months + '개월 관측');
    return row;
  }

  function render() {
    const query = normalize(search.value);
    const rows = firms.filter(firm => normalize(firm.name).includes(query));
    const metric = descending[sort.value];
    rows.sort((a, b) => (metric && metric(b) - metric(a)) || names.compare(a.name, b.name));
    body.replaceChildren(...rows.map(firmRow));
    count.textContent = rows.length
      ? (query ? '검색 결과 ' + rows.length + '곳 · 전체 ' + firms.length + '곳' : '전체 ' + firms.length + '곳')
      : '검색 결과가 없습니다.';
    results.hidden = !rows.length;
  }

  async function load() {
    search.value = new URLSearchParams(location.search).get('q') || search.value;
    count.textContent = '자료를 불러오는 중입니다.';
    try {
      const response = await fetch('firms.json');
      if (!response.ok) throw new Error('자료 조회 실패');
      firms = await response.json();
      render();
      search.addEventListener('input', render);
      sort.addEventListener('change', render);
    } catch {
      results.hidden = true;
      count.textContent = '표를 불러올 수 없습니다. 전체 엑셀 다운로드에서 자료를 확인해 주세요.';
    }
  }

  load();
})();
