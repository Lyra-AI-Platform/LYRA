/**
 * LyraAuth v1.0.0 — Human Intelligence Authenticator
 */
(function (window) {
  'use strict';
  const LYRAAUTH_VERSION = '1.0.0';
  const API_BASE = window.LYRAAUTH_API || '/api/auth';
  const CSS = `
  .lyraauth-widget{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;max-width:400px;border:1.5px solid #e2e8f0;border-radius:16px;padding:0;background:#fff;box-shadow:0 4px 24px rgba(0,0,0,.07);overflow:hidden;transition:all .3s ease}
  .lyraauth-header{display:flex;align-items:center;padding:14px 18px;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff}
  .lyraauth-logo{font-size:22px;margin-right:10px}
  .lyraauth-title{font-size:13px;font-weight:600}
  .lyraauth-subtitle{font-size:10px;opacity:.85;margin-top:1px}
  .lyraauth-body{padding:18px}
  .lyraauth-prompt{font-size:15px;color:#1a202c;line-height:1.5;margin-bottom:16px;font-weight:500}
  .lyraauth-options{display:flex;flex-direction:column;gap:8px}
  .lyraauth-option{padding:10px 14px;border:1.5px solid #e2e8f0;border-radius:10px;cursor:pointer;font-size:14px;color:#2d3748;transition:all .15s ease;background:#f8fafc;text-align:left}
  .lyraauth-option:hover{border-color:#667eea;background:#f0f4ff;color:#667eea;transform:translateX(2px)}
  .lyraauth-option.selected{border-color:#667eea;background:linear-gradient(135deg,#667eea15,#764ba215);color:#5a67d8;font-weight:600}
  .lyraauth-text-input{width:100%;padding:10px 14px;border:1.5px solid #e2e8f0;border-radius:10px;font-size:14px;outline:none;transition:border-color .2s;box-sizing:border-box}
  .lyraauth-submit{width:100%;margin-top:12px;padding:11px;background:linear-gradient(135deg,#667eea,#764ba2);color:#fff;border:none;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;transition:opacity .2s}
  .lyraauth-submit:disabled{opacity:.5;cursor:not-allowed}
  .lyraauth-footer{display:flex;align-items:center;justify-content:space-between;padding:10px 18px;border-top:1px solid #f0f0f0;background:#fafafa}
  .lyraauth-footer-text{font-size:10px;color:#a0aec0}
  .lyraauth-footer-text a{color:#667eea;text-decoration:none}
  .lyraauth-badge{font-size:10px;color:#48bb78;font-weight:600}
  .lyraauth-success{padding:28px 18px;text-align:center}
  .lyraauth-success-icon{font-size:42px;display:block;margin-bottom:10px;animation:lyraauth-pop .4s cubic-bezier(.175,.885,.32,1.275)}
  .lyraauth-success-text{font-size:16px;font-weight:700;color:#276749;margin-bottom:4px}
  .lyraauth-success-sub{font-size:12px;color:#68d391}
  .lyraauth-loading{padding:32px 18px;text-align:center;color:#a0aec0;font-size:14px}
  .lyraauth-spinner{display:inline-block;width:24px;height:24px;border:3px solid #e2e8f0;border-top-color:#667eea;border-radius:50%;animation:lyraauth-spin .7s linear infinite;margin-bottom:10px}
  @keyframes lyraauth-spin{to{transform:rotate(360deg)}}
  @keyframes lyraauth-pop{from{transform:scale(0);opacity:0}to{transform:scale(1);opacity:1}}
  .lyraauth-error{background:#fff5f5;border:1.5px solid #fc8181;border-radius:10px;padding:10px 14px;font-size:13px;color:#c53030;margin-top:10px;display:none}
  .lyraauth-training-note{font-size:10px;color:#a0aec0;margin-top:10px;text-align:center;line-height:1.4}
  .lyraauth-training-note a{color:#667eea;text-decoration:none}
  `;
  class LyraAuth {
    constructor(container, options = {}) {
      this.container = container;
      this.siteKey = options.siteKey || container.getAttribute('data-sitekey') || '';
      this.callback = options.callback || null;
      this.challenge = null;
      this.selectedAnswer = null;
      this.sessionId = 'sess_' + Math.random().toString(36).substring(2, 15);
      this.startTime = 0;
      this.token = null;
      this._injectStyles();
      this._render('loading');
      this._fetchChallenge();
    }
    _injectStyles() {
      if (!document.getElementById('lyraauth-styles')) {
        const s = document.createElement('style');
        s.id = 'lyraauth-styles';
        s.textContent = CSS;
        document.head.appendChild(s);
      }
    }
    async _fetchChallenge() {
      try {
        const res = await fetch(`${API_BASE}/challenge?site_key=${this.siteKey}`);
        if (!res.ok) throw new Error();
        this.challenge = await res.json();
        this.startTime = Date.now();
        this._render('challenge');
      } catch(e) { this._render('error', 'Could not load challenge.'); }
    }
    _render(state, errorMsg = '') {
      this.container.innerHTML = '';
      const widget = document.createElement('div');
      widget.className = 'lyraauth-widget';
      const header = document.createElement('div');
      header.className = 'lyraauth-header';
      header.innerHTML = '<span class="lyraauth-logo">✦</span><div><div class="lyraauth-title">LyraAuth</div><div class="lyraauth-subtitle">Proving you are human, training AI</div></div>';
      widget.appendChild(header);
      if (state === 'loading') {
        const b = document.createElement('div');
        b.className = 'lyraauth-loading';
        b.innerHTML = '<div class="lyraauth-spinner"></div><br>Loading challenge...';
        widget.appendChild(b);
      } else if (state === 'challenge' && this.challenge) {
        widget.appendChild(this._buildBody());
      } else if (state === 'success') {
        const b = document.createElement('div');
        b.className = 'lyraauth-success';
        b.innerHTML = '<span class="lyraauth-success-icon">✅</span><div class="lyraauth-success-text">Verified!</div><div class="lyraauth-success-sub">Your answer helps train Lyra AI ✦</div>';
        widget.appendChild(b);
      } else {
        const b = document.createElement('div');
        b.className = 'lyraauth-loading';
        b.style.color = '#e53e3e';
        b.textContent = errorMsg || 'Something went wrong.';
        widget.appendChild(b);
      }
      if (state !== 'success') {
        const footer = document.createElement('div');
        footer.className = 'lyraauth-footer';
        footer.innerHTML = '<span class="lyraauth-footer-text"><a href="/pages/privacy.html">Privacy</a> · Your answer trains Lyra AI</span><span class="lyraauth-badge">⚡ v' + LYRAAUTH_VERSION + '</span>';
        widget.appendChild(footer);
      }
      this.container.appendChild(widget);
    }
    _buildBody() {
      const body = document.createElement('div');
      body.className = 'lyraauth-body';
      const c = this.challenge;
      const prompt = document.createElement('div');
      prompt.className = 'lyraauth-prompt';
      prompt.innerHTML = c.prompt.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
      body.appendChild(prompt);
      const answersDiv = document.createElement('div');
      answersDiv.className = 'lyraauth-options';
      if (c.options && c.options.length > 0) {
        c.options.forEach(opt => {
          const btn = document.createElement('button');
          btn.className = 'lyraauth-option';
          btn.textContent = opt;
          btn.addEventListener('click', () => {
            this.selectedAnswer = opt;
            body.querySelectorAll('.lyraauth-option').forEach(b => b.classList.remove('selected'));
            btn.classList.add('selected');
          });
          answersDiv.appendChild(btn);
        });
      } else {
        const input = document.createElement('input');
        input.type = 'text';
        input.className = 'lyraauth-text-input';
        input.placeholder = 'Type your answer...';
        input.addEventListener('input', () => { this.selectedAnswer = input.value; });
        answersDiv.appendChild(input);
      }
      body.appendChild(answersDiv);
      const errorDiv = document.createElement('div');
      errorDiv.className = 'lyraauth-error';
      body.appendChild(errorDiv);
      const submitBtn = document.createElement('button');
      submitBtn.className = 'lyraauth-submit';
      submitBtn.textContent = 'Verify →';
      submitBtn.addEventListener('click', () => this._submit(submitBtn, errorDiv));
      body.appendChild(submitBtn);
      const note = document.createElement('div');
      note.className = 'lyraauth-training-note';
      note.innerHTML = 'By answering, you consent to your response being used to train Lyra AI.';
      body.appendChild(note);
      return body;
    }
    async _submit(btn, errorDiv) {
      if (!this.selectedAnswer || !this.selectedAnswer.trim()) {
        errorDiv.style.display = 'block';
        errorDiv.textContent = 'Please select or enter an answer first.';
        return;
      }
      btn.disabled = true;
      btn.textContent = 'Verifying...';
      errorDiv.style.display = 'none';
      const answerTimeMs = Date.now() - this.startTime;
      try {
        const res = await fetch(`${API_BASE}/verify`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({challenge_id: this.challenge.id, session_id: this.sessionId, answer: this.selectedAnswer, answer_time_ms: answerTimeMs, site_key: this.siteKey, user_agent: navigator.userAgent})
        });
        const result = await res.json();
        if (result.success && result.token) {
          this.token = result.token;
          this._render('success');
          const input = document.createElement('input');
          input.type = 'hidden';
          input.name = 'lyraauth_token';
          input.value = result.token;
          this.container.parentNode.insertBefore(input, this.container.nextSibling);
          if (this.callback) this.callback(result.token);
        } else {
          errorDiv.style.display = 'block';
          errorDiv.textContent = "That doesn't look right. Try again!";
          btn.disabled = false;
          btn.textContent = 'Try Again →';
          setTimeout(() => this._fetchChallenge(), 1500);
        }
      } catch(e) {
        errorDiv.style.display = 'block';
        errorDiv.textContent = 'Network error.';
        btn.disabled = false;
        btn.textContent = 'Retry →';
      }
    }
    getToken() { return this.token; }
  }
  function init() {
    document.querySelectorAll('.lyraauth[data-sitekey]').forEach(el => {
      if (!el._lyraauth) el._lyraauth = new LyraAuth(el);
    });
  }
  window.LyraAuth = { render: (c, o) => new LyraAuth(typeof c === 'string' ? document.getElementById(c) : c, o), init, version: LYRAAUTH_VERSION };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})(window);
