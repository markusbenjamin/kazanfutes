const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const createContext = require('./dashboard_test_context.cjs');
const html = fs.readFileSync(path.resolve(__dirname, '../../docs/dashboard.html'), 'utf8');
const languageTools = html.match(/<nav id="dashboard-page-tools"[\s\S]*?<\/nav>/)[0];
assert.doesNotMatch(languageTools, /<svg/,'language switch uses text, not flags');
for (const code of ['hu','en']) assert.match(languageTools, new RegExp('id="dashboard-language-' + code + '"[^>]*>' + code + '</a>'));
function page(search) {
    let document;
    class Element {
        constructor(id='') {this.id=id;this.hidden=true;this.children=[];this.attrs={};this.events={};this.isConnected=true;this.textContent='';}
        append(...children) {this.children.push(...children);}
        replaceChildren(...children) {this.children=children;}
        setAttribute(key,value) {this.attrs[key]=value;}
        getAttribute(key) {return this.attrs[key] || null;}
        addEventListener(key,callback) {this.events[key]=callback;}
        contains(node) {return this===node||this.children.some(child=>child.contains?.(node));}
        focus() {document.activeElement=this;}
        click() {this.focus();this.events.click?.({});}
    }
    const ids=['admin-message','admin-message-content','admin-message-close','admin-message-ok',
        'demo-help','demo-help-content','demo-help-launcher','demo-help-close','demo-help-ok',
        'dashboard-page-tools','dashboard-language-hu','dashboard-language-en'];
    const nodes=Object.fromEntries(ids.map(id=>[id,new Element(id)]));
    const labels={'admin-message':'Adminisztrátori üzenet','admin-message-close':'Üzenet bezárása',
        'demo-help':'A dashboard használata','demo-help-close':'Súgó bezárása'};
    Object.entries(labels).forEach(([id,label])=>nodes[id].setAttribute('aria-label',label));
    nodes['admin-message'].append(nodes['admin-message-content'],nodes['admin-message-close'],nodes['admin-message-ok']);
    nodes['demo-help'].append(nodes['demo-help-content'],nodes['demo-help-close'],nodes['demo-help-ok']);
    const link=new Element();
    document={documentElement:{},title:'Kazán-Gólya fűtés: rendszerállapot',activeElement:new Element('body'),
        getElementById:id=>nodes[id],querySelector:()=>link,createElement:()=>new Element(),
        createTextNode:text=>({textContent:text})};
    const context=createContext({URL,URLSearchParams,window:{location:{search,href:'http://localhost/dashboard.html'+search}},document});
    for(const file of ['admin_message','dashboard_help'])
        vm.runInContext(fs.readFileSync(path.resolve(__dirname,'../../docs/'+file+'.js'),'utf8'),context);
    return {context,nodes,document,link,update(value){context.message=value;vm.runInContext('updateAdminMessage(message, true)',context);}};
}
for(const query of ['?lang=en&demo=1','?lang=en&demo=true&ref_source=form']) {
    const {nodes,context,document,update}=page(query);
    assert.equal(nodes['demo-help'].hidden,false,'demo help opens initially');
    assert.equal(nodes['demo-help-launcher'].hidden,false);
    assert.equal(nodes['demo-help-launcher'].attrs['aria-expanded'],'true');
    const helpContent = nodes['demo-help-content'].children.map(node=>node.textContent);
    assert.ok(helpContent[0].includes('Kazán–Gólya'),'project introduction comes before interaction instructions');
    assert.ok(helpContent[1].includes(query.includes('lang=en') ? 'real operating data' : 'valós üzemi adatokon'));
    assert.ok(helpContent[2].includes(query.includes('lang=en') ? 'Using the dashboard' : 'A dashboard használata'));
    update('An actual admin message');
    assert.equal(nodes['admin-message'].hidden,true,'demo always suppresses the real admin message');
    nodes['demo-help-ok'].click();
    assert.equal(nodes['demo-help'].hidden,true);
    update('Changed actual admin message');
    assert.equal(nodes['demo-help'].hidden,true,'polling never reopens help');
    assert.equal(nodes['admin-message'].hidden,true);
    nodes['demo-help-launcher'].click();
    assert.equal(nodes['demo-help'].hidden,false,'help can be reopened');
    nodes['demo-help-close'].click();
    assert.equal(nodes['demo-help'].hidden,true);
    assert.equal(document.activeElement,nodes['demo-help-launcher'],'closing returns focus to help');
    nodes['demo-help-launcher'].click();
    nodes['demo-help'].events.keydown({key:'Escape'});
    assert.equal(nodes['demo-help'].hidden,true);
    assert.equal(vm.runInContext('dismissedAdminMessage',context),'','demo help never acknowledges admin messages');
    if(query.includes('lang=en')) {
        assert.equal(document.documentElement.lang,'en');
        assert.equal(nodes['demo-help-launcher'].textContent,'help');
        assert.ok(nodes['demo-help-content'].children.some(node=>node.textContent.includes('Ctrl+click')));
    } else assert.equal(document.documentElement.lang,'hu');
}
for(const query of ['','?lang=en','?demo=0','?ref_source=form','?demo=1','?lang=hu&demo=1']) {
    const view=page(query);
    const english=query.includes('lang=en');
    assert.equal(view.nodes['demo-help'].hidden,true);
    assert.equal(view.nodes['demo-help-launcher'].hidden,!english,'only English help is currently enabled');
    view.nodes['demo-help-launcher'].click();
    assert.equal(view.nodes['demo-help'].hidden,!english,'Hungarian help cannot be opened while on hold');
    assert.ok(view.nodes['demo-help-content'].children[0].textContent.includes('Kazán–Gólya'));
    assert.equal(view.nodes['demo-help-launcher'].textContent,query.includes('lang=en') ? 'help' : 'mi ez?');
    view.nodes['demo-help-ok'].click();
    assert.equal(view.nodes['demo-help'].hidden,true);
    view.update('Message');
    assert.equal(view.nodes['admin-message'].hidden,query.includes('ref_source=form') || query.includes('demo=1'));
}
for (const query of ['?zoom=0.8&demo=1&lang=en&ref_source=form#plot','?mobile=1&lang=hu']) {
    const {nodes}=page(query);
    for (const language of ['hu','en']) {
        const url=new URL(nodes['dashboard-language-'+language].attrs.href);
        const original=new URL('http://localhost/dashboard.html'+query);
        assert.equal(url.searchParams.get('lang'),language);
        assert.equal(url.hash,original.hash);
        for(const [key,value] of original.searchParams) if(key!=='lang') assert.equal(url.searchParams.get(key),value);
        assert.equal(nodes['dashboard-language-'+language].attrs['aria-current'],String(query.includes('lang='+language)));
        assert.equal(nodes['dashboard-language-'+language].hidden,query.includes('lang='+language),'only the other language is visible');
    }
}
console.log('Dashboard help passed: English help retained, Hungarian help on hold with content preserved, repeatable reopening, Ok/X/Escape, focus restoration, polling isolation and language links preserving URL options.');
