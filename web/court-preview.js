/** Optional BlinQ court preview; the canonical asset stays unchanged. */
(() => {
  'use strict';
  const canvas = document.getElementById('courtCanvas');
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const stage = document.getElementById('stage');
  const originalBtn = document.getElementById('btnOriginal');
  const suggestedBtn = document.getElementById('btnSuggested');
  const viewSelect = document.getElementById('viewSelect');
  const W = 1672, H = 941;
  const base = new Image();
  let showProposed = true, cachedOriginal = null, cachedClean = null;

  function repairedFloor() {
    if (cachedClean) return cachedClean;
    const off = document.createElement('canvas');
    off.width = W; off.height = H;
    const c = off.getContext('2d', {willReadFrequently:true});
    c.putImageData(cachedOriginal,0,0);
    const maskCanvas = document.createElement('canvas');
    maskCanvas.width = W; maskCanvas.height = H;
    const m = maskCanvas.getContext('2d', {willReadFrequently:true});
    const erase = (points, width) => {
      m.beginPath(); m.moveTo(...points[0]);
      for(let i=1;i<points.length;i++) m.lineTo(...points[i]);
      m.lineWidth=width; m.strokeStyle='#fff';
      m.lineCap='round'; m.lineJoin='round'; m.stroke();
    };
    // Only thin erroneous marks on the floor; never cover the scene or the net.
    erase([[190,805],[1130,807]],19);
    erase([[215,814],[1210,939]],20);
    erase([[188,808],[360,838]],17);
    erase([[190,821],[395,793]],15);
    const mask=m.getImageData(0,0,W,H).data;
    const source=cachedOriginal.data;
    const data=c.createImageData(W,H);
    data.data.set(source);
    for(let y=764;y<H;y++){
      for(let x=0;x<W;x++){
        const i=(y*W+x)*4;
        if(mask[i+3]===0) continue;
        const top=(Math.max(678,y-25)*W+x)*4;
        const bottom=(Math.min(H-1,y+25)*W+x)*4;
        const alpha=mask[i+3]/255;
        for(let channel=0;channel<3;channel++){
          const restored=(source[top+channel]+source[bottom+channel])/2;
          data.data[i+channel]=Math.round(source[i+channel]*(1-alpha)+restored*alpha);
        }
      }
    }
    c.putImageData(data,0,0);
    cachedClean=off;
    return cachedClean;
  }
  function drawLine(points,thickness=2.6,opacity=.69){
    ctx.beginPath(); ctx.moveTo(points[0][0],points[0][1]);
    for(let i=1;i<points.length;i++)ctx.lineTo(points[i][0],points[i][1]);
    ctx.lineWidth=thickness;
    ctx.strokeStyle='rgba(227,243,235,'+opacity+')';
    ctx.lineJoin='round'; ctx.lineCap='round'; ctx.stroke();
  }
  function render(){
    if(!cachedOriginal) return;
    ctx.clearRect(0,0,W,H);
    if(!showProposed){ctx.putImageData(cachedOriginal,0,0);return;}
    ctx.drawImage(repairedFloor(),0,0);
    // Regulation proportions: net->baseline 11.885 m, net->service 6.40 m,
    // doubles width 10.97 m, singles width 8.23 m.
    // One side-on projection: left-hand net, play extends towards the right.
    drawLine([[368,672],[1275,705]],3,.67);
    drawLine([[7,830],[1555,873]],3,.77);
    drawLine([[1275,705],[1555,873]],3,.72);
    drawLine([[329,685],[1342,741]],2.5,.64);
    drawLine([[69,800],[1503,845]],2.5,.65);
    drawLine([[837,713],[869,819]],2.4,.73);
    drawLine([[209,751],[852,766]],2.4,.64);
  }
  function update(){
    originalBtn.setAttribute('aria-pressed',String(!showProposed));
    suggestedBtn.setAttribute('aria-pressed',String(showProposed));
    render();
  }
  originalBtn.addEventListener('click',()=>{showProposed=false;update();});
  suggestedBtn.addEventListener('click',()=>{showProposed=true;update();});
  viewSelect.addEventListener('change',()=>{stage.dataset.view=viewSelect.value;});
  base.onload=()=>{
    ctx.drawImage(base,0,0,W,H);
    cachedOriginal=ctx.getImageData(0,0,W,H);
    update();
  };
  base.onerror=()=>{
    document.querySelector('.footnote').textContent='Náhľad sa nepodarilo načítať.';
  };
  base.src='/assets/blinq_page_background.webp';
  window.__BLINQ_COURT_PREVIEW_V2__=true;
})();