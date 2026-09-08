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
    console.log('PASS: dashboard token aliases, Unicode transport, request/body timeouts and cleanup');
}
main().catch(error=>{console.error(error);process.exitCode=1;});
