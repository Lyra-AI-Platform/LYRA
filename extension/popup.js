chrome.storage.sync.get({ to: '' }).then(({ to }) => { document.getElementById('to').value = to; });
document.getElementById('go').addEventListener('click', async () => {
  const to = document.getElementById('to').value.trim();
  const from = document.getElementById('from').value.trim();
  await chrome.storage.sync.set({ to });
  chrome.runtime.sendMessage({ type: 'explain-page', to, from }, () => window.close());
});
