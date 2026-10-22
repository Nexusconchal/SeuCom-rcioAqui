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
    let timeout;
    const done=(result={})=>{if(finished)return;finished=true;clearTimeout(timeout);document.body.classList.remove('printing-ticket');area.innerHTML='';window.removeEventListener('afterprint',closed);setTimeout(()=>resolve(result),300);};
    const closed=()=>done({dialogClosed:true});
    window.addEventListener('afterprint',closed);
    timeout=setTimeout(()=>{done({error:true});toast('A impressão ficou sem confirmação do navegador. Confira o papel e o histórico antes de repetir.');},120000);
    const images=[...area.querySelectorAll('img')].filter(img=>!img.complete).map(img=>new Promise(r=>{img.onload=img.onerror=r;}));
    Promise.race([Promise.all(images),new Promise(r=>setTimeout(r,3000))]).then(()=>setTimeout(()=>{try{if(typeof window.print!=='function')throw Error('Impressão indisponível');window.print();}catch{done({error:true});toast('Não consegui abrir a impressão. Tente pelo Chrome ou Edge no Windows.');}},50));
  }));
  return queue;
}
