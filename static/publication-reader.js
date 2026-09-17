/* global document, NodeFilter */
/* Progressive presentation only: source content and routes stay unchanged. */
(function () {
  'use strict';
  const main = document.querySelector('main');
  if (!main) return;
  const walker = document.createTreeWalker(main, NodeFilter.SHOW_TEXT);
  const nodes = [];
  while (walker.nextNode()) {
    const node = walker.currentNode;
    if (!node.parentElement.closest('script, style, code, pre, textarea') && /\*\*[^*]+\*\*/.test(node.textContent)) nodes.push(node);
  }
  nodes.forEach(function (node) {
    const fragment = document.createDocumentFragment();
    const text = node.textContent;
    const pattern = /\*\*([^*]+)\*\*/g;
    let start = 0;
    for (const match of text.matchAll(pattern)) {
      fragment.append(document.createTextNode(text.slice(start, match.index)));
      const strong = document.createElement('strong');
      strong.textContent = match[1];
      fragment.append(strong);
      start = match.index + match[0].length;
    }
    fragment.append(document.createTextNode(text.slice(start)));
    node.replaceWith(fragment);
  });
  const input = document.querySelector('[data-publication-search]');
  if (!input) return;
  const cards = Array.from(document.querySelectorAll('.publication-card'));
  const status = document.querySelector('[data-search-status]');
  input.addEventListener('input', function () {
    const query = input.value.trim().toLocaleLowerCase();
    let count = 0;
    cards.forEach(function (card) {
      card.hidden = !card.textContent.toLocaleLowerCase().includes(query);
      if (!card.hidden) count++;
    });
    status.textContent = query ? (count ? count + (count === 1 ? ' result' : ' results') : 'No matches. Try another country or keyword.') : '';
  });
}());
