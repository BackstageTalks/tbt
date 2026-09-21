'use strict';

const fs=require('fs');
const vm=require('vm');
const assert=require('assert');

class ClassList {
  constructor(){this.values=new Set();}
  toggle(name,on){if(on)this.values.add(name);else this.values.delete(name);}
  add(name){this.values.add(name);}
  remove(name){this.values.delete(name);}
  contains(name){return this.values.has(name);}
}
class NodeEl {
  constructor(dataset={}){this.dataset={...dataset};this.hidden=false;this.classList=new ClassList();this.attrs={};this.parentElement=null;this.removed=false;}
  closest(selector){
    if(selector==='[data-match-tab]'&&this.dataset.matchTab)return this;
    return null;
  }
  setAttribute(k,v){this.attrs[k]=String(v);}
  matches(selector){
    if(selector==='[data-player-photo]')return this.dataset.kind==='player';
    if(selector==='[data-flag-image]')return this.dataset.kind==='flag';
    if(selector==='[data-tournament-logo]')return this.dataset.kind==='tournament';
    return false;
  }
  getAttribute(name){return name==='src'?this.src:null;}
  remove(){this.removed=true;}
}
class ImageEl extends NodeEl {}

const overviewBtn=new NodeEl({matchTab:'overview'});overviewBtn.classList.add('active');
const statsBtn=new NodeEl({matchTab:'statistics'});
const overviewPanel=new NodeEl({matchPanel:'overview'});overviewPanel.classList.add('active');
const statsPanel=new NodeEl({matchPanel:'statistics'});statsPanel.hidden=true;
const popButton=new NodeEl({matchPopout:''});
const listeners={};
const document={
  addEventListener(type,fn,capture){listeners[type]=fn;},
  querySelectorAll(selector){
    if(selector==='[data-match-tab]')return [overviewBtn,statsBtn];
    if(selector==='[data-match-panel]')return [overviewPanel,statsPanel];
    if(selector==='[data-match-popout]')return [popButton];
    return [];
  }
};
const context={document,HTMLImageElement:ImageEl,console};context.window=context;
vm.createContext(context);
vm.runInContext(fs.readFileSync('web/match-popout.js','utf8'),context,{filename:'web/match-popout.js'});

assert.strictEqual(popButton.removed,true,'nested popout button is removed');
listeners.click({target:statsBtn});
assert.strictEqual(statsBtn.classList.contains('active'),true);
assert.strictEqual(overviewBtn.classList.contains('active'),false);
assert.strictEqual(statsPanel.hidden,false);
assert.strictEqual(overviewPanel.hidden,true);

const host=new NodeEl();host.classList.add('has-photo');
const img=new ImageEl({kind:'player',fallbackSrc:'/assets/missing_foto_w.webp',fallbackText:'AB'});img.parentElement=host;img.src='/assets/missing.webp';
listeners.error({target:img});
assert.strictEqual(img.src,'/assets/missing_foto_w.webp','first image error applies BlinQ fallback');
listeners.error({target:img});
assert.strictEqual(host.classList.contains('has-photo'),false,'fallback failure drops to initials');
assert.strictEqual(host.textContent,'AB');
console.log('r41 match popout runtime: PASS');
