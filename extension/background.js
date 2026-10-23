// Lyra browser extension. It never sends page content anywhere itself: it opens Lyra Labs with
// the text in the URL fragment (after #), which browsers don't send to any server. Nothing goes
// to an AI until you press Run on the Lyra page, and then only to the AI you chose there.
const LABS = 'https://lyraauth.com/labs/';
const MAX = 12000;

function openLabs(fields) {
  const p = new URLSearchParams({ app: 'translate', ...fields });
  chrome.tabs.create({ url: LABS + '#' + p.toString() });
}

async function settings() {
  const s = await chrome.storage.sync.get({ to: '' });
  return { to: s.to || (navigator.language || 'en-GB').split('-')[1] || 'United Kingdom' };
}

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({ id: 'lyra-explain', title: 'Explain with Lyra for my country', contexts: ['selection'] });
  chrome.contextMenus.create({ id: 'lyra-page', title: 'Explain this whole page with Lyra', contexts: ['page'] });
});

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  const { to } = await settings();
  if (info.menuItemId === 'lyra-explain') {
    openLabs({ text: (info.selectionText || '').slice(0, MAX), src: tab && tab.url ? tab.url : '', to });
  } else if (info.menuItemId === 'lyra-page' && tab) {
    const text = await pageText(tab.id);
    openLabs({ text, src: tab.url || '', to });
  }
});

async function pageText(tabId) {
  try {
    const [res] = await chrome.scripting.executeScript({
      target: { tabId },
      func: (max) => {
        const main = document.querySelector('main, article, [role=main]') || document.body;
        return (main.innerText || '').replace(/\n{3,}/g, '\n\n').slice(0, max);
      },
      args: [MAX],
    });
    return res && res.result ? res.result : '';
  } catch (e) {
    return '';
  }
}

chrome.runtime.onMessage.addListener((msg, sender, reply) => {
  if (msg && msg.type === 'explain-page') {
    chrome.tabs.query({ active: true, currentWindow: true }).then(async ([tab]) => {
      const { to } = await settings();
      const text = tab ? await pageText(tab.id) : '';
      openLabs({ text, src: tab ? tab.url : '', to: msg.to || to, from: msg.from || '' });
      reply({ ok: true });
    });
    return true;
  }
});
