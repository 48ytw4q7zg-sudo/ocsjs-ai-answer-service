const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function loadDashboard(search, fetchImpl) {
    const timers = new Map();
    let timerId = 0;
    const context = vm.createContext({
        console, URL, URLSearchParams, AbortController,
        window: {location: {search, origin:'http://localhost'}, addEventListener() {}},
        document: {hidden:false, addEventListener() {}, getElementById:()=>null},
        $: () => ({ready() {}}),
        fetch: fetchImpl,
        setTimeout: (fn, delay) => {const id=++timerId; timers.set(id,{fn,delay}); return id;},
        clearTimeout: id => timers.delete(id)
    });
    const html=fs.readFileSync(path.join(__dirname,'templates/dashboard.html'),'utf8');
    for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)) {
        if (match[1].trim()) vm.runInContext(match[1],context);
    }
    return {context,timers};
}

async function testDashboardActions() {
    let scenarios = 0;
    const actions = [['clearCache', '/api/cache/clear'], ['reloadConfig', '/api/config/reload']];
    for (const [action, expectedPath] of actions) {
        for (const explicitToken of ['', '\u4e2d\u6587\u4ee4\u724c']) {
            const calls = [], alerts = [];
            let refreshes = 0;
            const page = loadDashboard(explicitToken ? '?access_token=' + encodeURIComponent(explicitToken) : '', async (url, options) => {
                calls.push({url, options});
                return {ok:true, status:200, statusText:'OK', headers:{get:()=> 'application/json'}, text:async()=>'{"success":true,"runtime_ready":true}'};
            });
            page.context.confirm = () => true;
            page.context.alert = message => alerts.push(message);
            page.context.refreshRuntimeStatus = () => refreshes++;
            page.context[action]();
            await new Promise(resolve => setImmediate(resolve));
            assert.equal(calls.length, 1, action);
            assert.equal(new URL(calls[0].url, 'http://localhost').pathname, expectedPath);
            assert.equal(calls[0].options.method, 'POST');
            if (explicitToken) assert.equal(JSON.parse(calls[0].options.body).token, explicitToken);
            assert.equal(alerts.length, 1, action);
            assert.doesNotMatch(alerts[0], /\u5931\u8d25/, action);
            assert.equal(refreshes, 1, action);
            assert.equal(page.timers.size, 0, action);
            scenarios++;
        }

        const cancelledCalls = [];
        const cancelled = loadDashboard('', async (...args) => cancelledCalls.push(args));
        cancelled.context.confirm = () => false;
        cancelled.context.alert = () => {throw new Error('Cancelled action must not alert');};
        cancelled.context[action]();
        await new Promise(resolve => setImmediate(resolve));
        assert.equal(cancelledCalls.length, 0, action);
        assert.equal(cancelled.timers.size, 0, action);
        scenarios++;

        for (const response of [
            {ok:true, status:200, statusText:'OK', headers:{get:()=> 'application/json'}, text:async()=>'{"success":false,"message":"synthetic_failure"}'},
            {ok:false, status:503, statusText:'Service Unavailable', headers:{get:()=> 'application/json'}, text:async()=>'{"error":"synthetic_failure"}'}
        ]) {
            const alerts = [];
            let calls = 0, refreshes = 0;
            const failed = loadDashboard('', async () => {calls++; return response;});
            failed.context.confirm = () => true;
            failed.context.alert = message => alerts.push(message);
            failed.context.refreshRuntimeStatus = () => refreshes++;
            failed.context[action]();
            await new Promise(resolve => setImmediate(resolve));
            assert.equal(calls, 1, action);
            assert.equal(alerts.length, 1, action);
            assert.match(alerts[0], /\u5931\u8d25/, action);
            assert.match(alerts[0], /synthetic_failure/, action);
            assert.equal(refreshes, 1, action);
            assert.equal(failed.timers.size, 0, action);
            if (response.status === 503) {
                await assert.rejects(failed.context.requestJson(expectedPath, {method:'POST'}), error =>
                    error.status === 503 && error.message === 'synthetic_failure');
                assert.equal(failed.timers.size, 0, action);
            }
            scenarios++;
        }
    }
    return scenarios;
}

async function main() {
    const calls=[];
    const ok=async(url,options)=>{calls.push({url,options}); return {ok:true,status:200,headers:{get:()=> 'application/json'},text:async()=>'{"success":true}'};};
    const page=loadDashboard('?access_token='+encodeURIComponent('中文令牌'),ok);
    await page.context.requestJson('/api/config/reload',{method:'POST'});
    assert.equal(JSON.parse(calls[0].options.body).token,'中文令牌');
    assert.equal(calls[0].options.headers['X-Access-Token'],undefined);
    assert.equal(page.timers.size,0);
    await page.context.requestJson('/api/health');
    assert.equal(new URL(calls[1].url).searchParams.get('access_token'),'中文令牌');

    for (const fetchImpl of [() => new Promise(()=>{}), async()=>({ok:true,status:200,text:()=>new Promise(()=>{})})]) {
        const stalled=loadDashboard('',fetchImpl);
        const request=stalled.context.requestJson('/api/health');
        const rejected=assert.rejects(request,/请求超时/);
        await new Promise(resolve=>setImmediate(resolve));
        for(const timer of stalled.timers.values()) if(timer.delay===15000) timer.fn();
        await rejected;
        assert.equal(stalled.timers.size,0);
    }
    const actionScenarios = await testDashboardActions();
    console.log(`PASS: dashboard token aliases, Unicode transport, request/body timeouts, cleanup and ${actionScenarios} action scenarios`);
}
main().catch(error=>{console.error(error);process.exitCode=1;});
