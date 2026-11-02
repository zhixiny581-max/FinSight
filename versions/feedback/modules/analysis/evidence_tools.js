const http=require('http'),https=require('https'),dns=require('dns').promises,net=require('net');
function publicIp(ip){if(net.isIP(ip)===4){const [a,b]=ip.split('.').map(Number);return !(a===0||a===10||a===127||a>=224||a===169&&b===254||a===172&&b>=16&&b<=31||a===192&&b===168||a===100&&b>=64&&b<=127||a===198&&(b===18||b===19));} return net.isIP(ip)===6 && /^2[0-9a-f]{3}:/i.test(ip);}
async function page(url,signal,redirects=0){
 const u=new URL(url);if(!['https:','http:'].includes(u.protocol)||u.username||u.password||u.port&&!['80','443'].includes(u.port))throw Error('URL_NOT_PUBLIC');
 const host=u.hostname.replace(/^\[|\]$/g,'');const addresses=await dns.lookup(host,{all:true});if(!addresses.length||addresses.some(x=>!publicIp(x.address)))throw Error('URL_NOT_PUBLIC');
 return new Promise((resolve,reject)=>{const req=(u.protocol==='https:'?https:http).get(u,{signal,lookup:(_h,_o,cb)=>_o?.all?cb(null,[addresses[0]]):cb(null,addresses[0].address,addresses[0].family),headers:{'User-Agent':'FinSightEvidence/1.0','Accept':'text/html,text/plain'}},res=>{
 if(res.statusCode>=300&&res.statusCode<400){res.resume();if(redirects>=4)return reject(Error('REDIRECT_LIMIT'));return page(new URL(res.headers.location,u).href,signal,redirects+1).then(resolve,reject);}
 if(res.statusCode!==200||!/text\/html|text\/plain|application\/xhtml/.test(res.headers['content-type']||'')){res.resume();return reject(Error('UNREADABLE_PAGE'));}
 let size=0,chunks=[];res.on('data',chunk=>{size+=chunk.length;if(size>2500000){req.destroy(Error('PAGE_TOO_LARGE'));return;}chunks.push(chunk);});res.on('error',reject);res.on('end',()=>{const charset=(res.headers['content-type']||'').match(/charset=([\w-]+)/i)?.[1]||'utf-8';const html=new TextDecoder(charset).decode(Buffer.concat(chunks)); const meta=n=>html.match(new RegExp('<meta[^>]*(?:property|name)=["\x27]'+n+'["\x27][^>]*content=["\x27]([^"\x27]+)','i'))?.[1]||''; resolve({url:u.href,title:html.match(/<title[^>]*>([\s\S]*?)<\/title>/i)?.[1]||u.hostname,published_at:meta('article:published_time'),updated_at:meta('article:modified_time'),content:html.replace(/<(script|style|nav|footer)\b[^>]*>[\s\S]*?<\/\1>/gi,' ').replace(/<[^>]+>/g,' ').replace(/&nbsp;|&#160;/g,' ').replace(/&amp;/g,'&').replace(/\s+/g,' ').trim()});});
 });req.on('error',reject);});
}
function createTools(options){return {
 availability(){return {ifind_news_search:!!options.ifindAvailable?.(),public_web_search:!!process.env.TAVILY_API_KEY,read_webpage:true};},
 async execute(request,signal){const args=request.arguments||{};
 if(request.tool==='ifind_news_search'){const result=await options.ifindSearch({query:String(args.query||'').slice(0,500),time_start:args.time_start,time_end:args.time_end,size:8},signal);return {raw:result.raw,items:result.items};}
 if(request.tool==='public_web_search'){const response=await fetch('https://api.tavily.com/search',{method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({api_key:process.env.TAVILY_API_KEY,query:String(args.query||'').slice(0,500),max_results:5,include_raw_content:false})});if(!response.ok)throw Error('SEARCH_PROVIDER_ERROR');const raw=await response.json();return {raw,items:(raw.results||[]).map(i=>({...i,published_at:i.published_date||'',content:i.content||'',evidence_level:'search_snippet'}))};}
 if(request.tool==='read_webpage'){const item=await page(args.url,signal);return {raw:item,items:[item]};}throw Error('UNKNOWN_TOOL');
 }
};}
module.exports={createTools,page,publicIp};
