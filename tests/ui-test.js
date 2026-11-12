// Minimal DOM stub to exercise the mode-selector logic without a browser.
const fs = require('fs');

function el(id, tag = 'div') {
  const node = {
    id, tagName: tag, _text: '', className: '', style: {}, hidden: false,
    disabled: false, placeholder: '', value: '', checked: false, type: '',
    children: [], listeners: {},
    get textContent() { return this._text; },
    set textContent(v) { this._text = String(v); this.children = []; },
    set innerHTML(v) { this._html = v; },
    get innerHTML() { return this._html; },
    append(...kids) { this.children.push(...kids); },
    addEventListener(name, fn) { (this.listeners[name] ||= []).push(fn); },
    fire(name) { (this.listeners[name] || []).forEach(fn => fn({ target: this })); },
    focus() { global.focused = this; },
    scrollIntoView() {},
    querySelector() { return el('q'); },
    setAttribute(k, v) { this[k] = v; },
    getBoundingClientRect() { return { left: 0, right: 0, top: 0, bottom: 0 }; },
    getAttribute(k) { return this[k]; },
  };
  return node;
}

const ids = ['tool-form', 'session', 'status', 'result', 'run', 'info', 'modes', 'paste',
  'about', 'close', 'tutorial-dialog', 'tutorial-video', 'tutorial-title',
  'tutorial-description', 'watch-tutorial', 'watch-animation', 'tab-recording',
  'tab-animation', 'close-tutorial', 'back-to-form'];
const store = Object.fromEntries(ids.map(id => [id, el(id)]));
const radios = ['hide', 'show'].map(v => { const r = el('mode-' + v, 'input'); r.value = v; return r; });

global.document = {
  getElementById: id => store[id] || el(id),
  querySelectorAll: sel => (sel === 'input[name=mode]' ? radios : []),
  createElement: tag => el('created', tag),
};
global.window = global;
global.innerWidth = 1200; global.innerHeight = 800;
const bodies = [];
global.fetch = (url, opts) => {
  if (opts && opts.body) bodies.push(JSON.parse(opts.body));
  return Promise.resolve({ ok: true, json: () => Promise.resolve({ ok: true, hidden: true, confirmed: true, username: 'demo' }) });
};
global.navigator = { clipboard: { readText: () => Promise.resolve('1234567890%3Aabc') } };

const html = fs.readFileSync('index.html', 'utf8');
const src = html.match(/<script>([\s\S]*)<\/script>/)[1];

// Mirror the served markup: both start disabled, button carries the placeholder label.
if (!/id="session"[^>]*\bdisabled\b/.test(html)) throw new Error('markup: textarea not disabled');
if (!/id="run"[^>]*\bdisabled\b/.test(html)) throw new Error('markup: button not disabled');
store.session.disabled = true;
store.run.disabled = true;
store.run.textContent = 'Choose an option first';

new Function(src)();

const input = store.session, runBtn = store.run, status = store.status;
let failures = 0;
function check(label, ok) {
  console.log((ok ? 'PASS  ' : 'FAIL  ') + label);
  if (!ok) failures++;
}
function report(label) {
  console.log('      ' + label, '| input.disabled:', input.disabled,
    '| btn.disabled:', runBtn.disabled, '| btn:', JSON.stringify(runBtn.textContent),
    '| checked:', radios.filter(r => r.checked).map(r => r.value).join(',') || 'none');
}

report('on load');
check('field starts disabled', input.disabled === true);
check('button starts disabled', runBtn.disabled === true);
check('button shows prompt label', runBtn.textContent === 'Choose an option first');

radios[1].checked = true; radios[1].fire('change');
report('after restore');
check('field enabled', input.disabled === false);
check('placeholder restored', input.placeholder.startsWith('1234567890'));
check('restore label', runBtn.textContent.includes('Restore followers'));
check('restore checked', radios[1].checked === true && radios[0].checked === false);

radios[0].checked = true; radios[0].fire('change');
report('after hide');
check('hide label', runBtn.textContent.includes('Hide followers'));
check('selection moved', radios[0].checked === true && radios[1].checked === false);

store['tool-form'].onsubmit({ preventDefault() {} });
report('after empty submit');
check('empty error shown', status.textContent === 'Paste your sessionid first.');

input.value = '1234567890%3Aabc';
store['tool-form'].onsubmit({ preventDefault() {} });

setTimeout(() => {
  report('after submit');
  const head = store.result.children[0];
  console.log('      result head:', JSON.stringify(head && head.textContent));
  check('success head', !!head && head.textContent.includes('Followers hidden'));
  const flip = store.result.children.find(c => c.className === 'flip');
  console.log('      flip button:', JSON.stringify(flip && flip.textContent));
  check('flip button present', !!flip);
  if (flip) {
    flip.onclick();
    report('after flip');
    check('flip switched to restore', radios[1].checked === true);
    check('flip hid the old result', store.result.hidden === true);
  }
  console.log('      request bodies:', JSON.stringify(bodies));
  check('hide request sent hide:true', bodies.filter(b => b.session)[0]?.hide === true);
  // submit again in restore mode
  store['tool-form'].onsubmit({ preventDefault() {} });
  setTimeout(() => {
    console.log('      request bodies:', JSON.stringify(bodies));
    check('restore request sent hide:false', bodies.filter(b => b.session)[1]?.hide === false);
    console.log(failures ? `\n${failures} FAILED` : '\nALL CHECKS PASSED');
    process.exit(failures ? 1 : 0);
  }, 60);
}, 60);
