import { $, toast } from './ui.js';

let queue=Promise.resolve();
// Serialize all documents, including reports, and snapshot before entering the queue.
// afterprint acknowledges a closed dialog, never physical delivery.
export function printDocument(html,settings){
  const snapshot={...settings};
  queue=queue.catch(()=>{}).then(()=>new Promise(resolve=>{
    let area=$('#print-area');if(!area){area=document.createElement('div');area.id='print-area';document.body.appendChild(area);}
    area.className='paper-'+snapshot.paper;
    area.style.setProperty('--ticket-width',snapshot.width+'mm');
    area.style.setProperty('--ticket-font',snapshot.font+'px');
    area.innerHTML=html;document.body.classList.add('printing-ticket');
    let finished=false;
    const done=()=>{if(finished)return;finished=true;document.body.classList.remove('printing-ticket');area.innerHTML='';window.removeEventListener('afterprint',done);setTimeout(resolve,300);};
    window.addEventListener('afterprint',done);
    const images=[...area.querySelectorAll('img')].filter(img=>!img.complete).map(img=>new Promise(r=>{img.onload=img.onerror=r;}));
    Promise.race([Promise.all(images),new Promise(r=>setTimeout(r,3000))]).then(()=>setTimeout(()=>{try{if(typeof window.print!=='function')throw Error('Impressão indisponível');window.print();}catch{done();toast('Não consegui abrir a impressão. Tente pelo Chrome ou Edge no Windows.');}},50));
  }));
  return queue;
}
