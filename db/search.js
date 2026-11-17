(() => {
  'use strict';
  const form = document.querySelector('#db-search');
  if (!form) return;
  const input = form.querySelector('input');
  const submit = form.querySelector('button[type="submit"]');
  const status = document.querySelector('#search-status');
  const results = document.querySelector('#search-results');
  const samples = [...document.querySelectorAll('[data-query]')];
  const endpoint = 'https://mcp.finance-fixer.net/public-search';
  let running = false;
  const messages = {
    invalid_query: '질문을 2~200자로 입력해 주세요.',
    invalid_request: '질문을 확인한 뒤 다시 검색해 주세요.',
    minute_limit: '잠시 검색이 몰렸습니다. 1분 뒤 다시 검색해 주세요.',
    daily_limit: '이 접속망의 오늘 체험 횟수를 모두 사용했습니다. 내일 다시 이용하거나 상담을 문의해 주세요.',
    service_limit: '오늘 준비한 검색 체험 횟수가 모두 소진됐습니다. 내일 다시 이용해 주세요.',
    busy: '다른 검색을 처리하고 있습니다. 잠시 뒤 다시 검색해 주세요.',
    unavailable: '지금은 검색을 이용하기 어렵습니다. 잠시 뒤 다시 이용해 주세요.'
  };
  function node(tag, cls, text) {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text) el.textContent = text;
    return el;
  }
  function sourceUrl(raw) {
    try {
      const url = new URL(raw);
      if (url.protocol !== 'https:' || url.username || url.password || url.port) return null;
      return ['www.law.go.kr', 'law.go.kr', 'taxlaw.nts.go.kr', 'www.olta.re.kr'].includes(url.hostname) ? url.href : null;
    } catch (_) { return null; }
  }
  function render(rows) {
    const fragment = document.createDocumentFragment();
    rows.slice(0, 5).forEach(row => {
      if (!row || typeof row.title !== 'string' || typeof row.excerpt !== 'string') return;
      const card = node('article', 'search-result');
      card.append(node('p', 'result-meta', [row.category, row.date].filter(Boolean).join(' · ')));
      card.append(node('h3', '', row.title));
      const preview = row.excerpt.length > 350 ? row.excerpt.slice(0, 350) + '…' : row.excerpt + (row.truncated ? '…' : '');
      card.append(node('p', 'result-excerpt', preview));
      if (row.excerpt.length > 350) {
        const details = node('details', 'result-more');
        details.append(node('summary', '', '검색 문단 더 보기'));
        details.append(node('p', 'result-excerpt', row.excerpt + (row.truncated ? '…' : '')));
        card.append(details);
      }
      const footer = node('div', 'result-source');
      footer.append(node('span', '', row.source));
      const url = sourceUrl(row.url);
      if (url) {
        const link = node('a', '', (row.link_text || '출처 확인') + ' ↗');
        link.href = url; link.target = '_blank'; link.rel = 'noopener noreferrer';
        footer.append(link);
      }
      card.append(footer); fragment.append(card);
    });
    results.replaceChildren(fragment);
  }
  async function search() {
    if (running) return;
    const query = input.value.trim().normalize('NFC');
    if (query.length < 2 || query.length > 200) {
      results.replaceChildren(); status.textContent = messages.invalid_query; input.focus(); return;
    }
    running = true;
    input.disabled = true; submit.disabled = true; samples.forEach(button => { button.disabled = true; });
    form.setAttribute('aria-busy', 'true');
    results.replaceChildren(); status.textContent = '관련 근거를 찾고 있습니다…';
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(endpoint, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query }), credentials: 'omit', cache: 'no-store',
        referrerPolicy: 'no-referrer', signal: controller.signal
      });
      const data = await response.json();
      if (!response.ok) {
        status.textContent = messages[data.error] || '검색을 마치지 못했습니다. 잠시 뒤 다시 검색해 주세요.';
        return;
      }
      if (!Array.isArray(data.results)) throw new Error('invalid response');
      render(data.results);
      const count = results.childElementCount;
      status.textContent = count
        ? `관련 자료 ${count}개를 찾았습니다. 적용시점과 예외는 원문에서 확인해 주세요.`
        : '관련 공개자료를 찾지 못했습니다. 세목·법령명·거래 내용을 바꿔 검색하거나 상담을 문의해 주세요.';
    } catch (error) {
      status.textContent = error.name === 'AbortError'
        ? '검색 응답이 늦어지고 있습니다. 잠시 뒤 다시 이용해 주세요.'
        : '검색에 연결하지 못했습니다. 인터넷 연결을 확인하거나 잠시 뒤 다시 이용해 주세요.';
    } finally {
      clearTimeout(timer); running = false; input.disabled = false; submit.disabled = false;
      samples.forEach(button => { button.disabled = false; });
      form.setAttribute('aria-busy', 'false');
    }
  }
  form.addEventListener('submit', event => { event.preventDefault(); search(); });
  samples.forEach(button => button.addEventListener('click', () => {
    if (running) return;
    input.value = button.dataset.query; search();
  }));
})();
