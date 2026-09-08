'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, 'templates', 'index.html'), 'utf8').match(/<script>([\s\S]*?)<\/script>/)[1];

function fixture(fetch) {
    const nodes = new Map();
    const timers = new Map();
    const navigations = [];
    let nextTimer = 1;
    function node() {
        return {
            value: '', style: {}, listeners: {}, textContent: '', innerHTML: '',
            classList: {add() {}, remove() {}},
            addEventListener(name, callback) { this.listeners[name] = callback; },
            appendChild(child) { this.innerHTML = String(child.text).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'); },
            querySelector() { return null; },
            focus() { this.focused = true; },
            parentElement: {before(...children) { for (const child of children) if (child.id) nodes.set(child.id, child); }}
        };
    }
    for (const id of ['search-btn', 'dashboard-link', 'result', 'answer-content', 'ocs-config']) nodes.set(id, node());
    const context = vm.createContext({
        document: {createElement: node, createTextNode: text => ({text}), getElementById: id => nodes.get(id)},
        window: {location: {host: '127.0.0.1:5000', protocol: 'http:', assign: url => navigations.push(url)}},
        fetch, AbortController, Promise, Error,
        setTimeout(callback) { const id = nextTimer++; timers.set(id, callback); return id; },
        clearTimeout(id) { timers.delete(id); }
    });
    vm.runInContext(source, context);
    return {nodes, timers, navigations, click: () => nodes.get('dashboard-link').listeners.click({preventDefault() {}})};
}

(async () => {
    let request;
    let page = fixture(async (url, options) => { request = {url, options}; return {ok: true, json: async () => ({code: 1})}; });
    page.nodes.get('access-token').value = 'SYNTHETIC_LOCAL_TOKEN';
    await page.click();
    assert.equal(request.url, '/api/session');
    assert.equal(request.options.method, 'POST');
    assert.equal(request.options.credentials, 'same-origin');
    assert.equal(JSON.parse(request.options.body).token, 'SYNTHETIC_LOCAL_TOKEN');
    assert.deepEqual(page.navigations, ['/dashboard']);
    assert.equal(page.timers.size, 0);

    page = fixture(async () => ({ok: false, json: async () => ({code: 0, msg: '<invalid token>'})}));
    await page.click();
    assert.equal(page.navigations.length, 0);
    assert.match(page.nodes.get('answer-content').innerHTML, /&lt;invalid token&gt;/);
    assert.equal(page.nodes.get('access-token').focused, true);
    assert.equal(page.timers.size, 0);

    for (const stallBody of [false, true]) {
        let calls = 0;
        page = fixture(() => { calls++; return stallBody ? Promise.resolve({ok: true, json: () => new Promise(() => {})}) : new Promise(() => {}); });
        const first = page.click();
        await page.click();
        assert.equal(calls, 1);
        await Promise.resolve();
        for (const callback of [...page.timers.values()]) callback();
        await first;
        assert.equal(page.navigations.length, 0);
        assert.equal(page.timers.size, 0);
        assert.match(page.nodes.get('answer-content').innerHTML, /超时/);
    }
    console.log('Browser navigation: session POST, secret-free URL, error escaping, duplicate guard and request/body timeout checks passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });
