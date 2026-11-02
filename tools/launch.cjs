const fs=require('fs'),path=require('path'),http=require('http'),crypto=require('crypto'),{spawn,execFileSync}=require('child_process');
const repo=path.resolve(__dirname,'..');
const mode=process.argv[2];
const fail=(text,code=1)=>{console.error(text);process.exitCode=code;};
function readSettings(file){return Object.fromEntries(fs.readFileSync(file,'utf8').replace(/^\uFEFF/,'').split(/\r?\n/).filter(s=>s.trim()&&!s.trim().startsWith('#')&&s.includes('=')).map(s=>{const i=s.indexOf('=');return [s.slice(0,i).trim(),s.slice(i+1).trim().replace(/^['"]|['"]$/g,'')];}));}
function open(url){if(process.platform==='win32')spawn('cmd.exe',['/d','/c','start','',url],{windowsHide:true,stdio:'ignore'}).unref();else console.log(url);}
function probe(port){return new Promise(resolve=>{const req=http.get({hostname:'127.0.0.1',port,path:'/api/status',agent:false,timeout:1800},res=>{let text='';res.on('data',chunk=>{if(text.length<64000)text+=chunk;});res.on('end',()=>{try{resolve({state:'occupied',status:JSON.parse(text)});}catch{resolve({state:'occupied'});}});res.on('error',()=>resolve({state:'occupied'}));});req.on('timeout',()=>req.destroy());req.on('error',e=>resolve({state:e.code==='ECONNREFUSED'?'stopped':'occupied'}));});}
async function main(){
 if(!['legacy','feedback'].includes(mode))return fail('请使用 legacy（旧版）或 feedback（新版）。');
 if(Number(process.versions.node.split('.')[0])<22)return fail('双版本启动器需要 Node.js 22 或更高版本。');
 const runtime=path.join(repo,mode==='legacy'?'':'versions/feedback','modules/news/prototype');
 const entry=path.join(runtime,'server.js'),envFile=path.join(runtime,'.env');
 if(!fs.existsSync(envFile)){fs.copyFileSync(path.join(runtime,'.env.example'),envFile,fs.constants.COPYFILE_EXCL);console.log('已创建本机配置，请填写 '+envFile+'，保存后重新启动。配置不会加入Git或上传包。');if(process.platform==='win32'&&!process.argv.includes('--check'))spawn('notepad.exe',[envFile],{stdio:'ignore'}).unref();process.exitCode=2;return;}
 const settings=readSettings(envFile),override=process.argv.find(a=>a.startsWith('--port='));
 const port=Number(override?override.slice(7):settings.PORT||(mode==='legacy'?3000:3003));
 if(!Number.isInteger(port)||port<1024||port>65535)return fail('端口须为1024至65535之间的整数。');
 const expected=crypto.createHash('sha256').update(runtime).digest('hex').slice(0,16);
 const isSame=s=>s&&s.app==='finsight-news-prototype'&&s.analysisSchemaVersion===6&&(mode==='feedback'?s.edition==='feedback'&&s.instance_id===expected:s.edition!=='feedback');
 const stateDir=path.join(runtime,'data'),stateFile=path.join(stateDir,'launcher-'+port+'.json');
 const existing=await probe(port);
 if(process.argv.includes('--stop')){
   if(existing.state==='stopped'){console.log('服务已经停止。');return;}
   if(!isSame(existing.status)||!fs.existsSync(stateFile))return fail('无法确认该进程由本启动器启动，未停止任何程序。');
   const state=JSON.parse(fs.readFileSync(stateFile));
   if(process.platform!=='win32')return fail('请在对应服务终端手动停止程序。');
   const info=JSON.parse(execFileSync('powershell.exe',['-NoProfile','-Command',`[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); Get-CimInstance Win32_Process -Filter 'ProcessId = ${Number(state.pid)}' | Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress`],{encoding:'utf8',windowsHide:true}));
   if(!info||info.ProcessId!==state.pid||!info.CommandLine.includes(entry)||!info.CommandLine.includes('--port='+port))return fail('进程信息不匹配，未停止任何程序。');
   process.kill(state.pid);console.log('已停止'+(mode==='legacy'?'旧版':'新版')+'服务。');return;
 }
 if(process.argv.includes('--check')){console.log(JSON.stringify({version:mode,node:process.versions.node,port,env_file:true,deepseek:!!(settings.DEEPSEEK_API_KEY||process.env.DEEPSEEK_API_KEY),ifind_direct:!!(settings.IFIND_MCP_AUTHORIZATION||settings.IFIND_API_KEY||process.env.IFIND_API_KEY),service:isSame(existing.status)?'running':existing.state}));return;}
 if(isSame(existing.status)){console.log('此版本已运行，打开页面。');if(!process.argv.includes('--no-open'))open('http://127.0.0.1:'+port+'/core');return;}
 if(existing.state!=='stopped')return fail('端口'+port+'被其他版本或程序占用。请更改本版本.env中的PORT；不会停止其他程序。');
 if(!(settings.DEEPSEEK_API_KEY||process.env.DEEPSEEK_API_KEY))return fail('请先在本版本.env填写DEEPSEEK_API_KEY。');
 if(!(settings.IFIND_MCP_AUTHORIZATION||settings.IFIND_API_KEY||process.env.IFIND_API_KEY))console.log('未填写直接iFinD授权，运行时将尝试已有Skill配置；建议在.env填写授权。');
 fs.mkdirSync(stateDir,{recursive:true});const stamp=new Date().toISOString().replace(/[:.]/g,'-');const stdout=fs.openSync(path.join(stateDir,'server-'+stamp+'.log'),'a'),stderr=fs.openSync(path.join(stateDir,'server-'+stamp+'-error.log'),'a');
 const child=spawn(process.execPath,[entry,'--port='+port],{cwd:runtime,detached:true,windowsHide:true,stdio:['ignore',stdout,stderr]});
 await new Promise((resolve,reject)=>{child.once('spawn',resolve);child.once('error',reject);});fs.closeSync(stdout);fs.closeSync(stderr);child.unref();
 fs.writeFileSync(stateFile,JSON.stringify({pid:child.pid,version:mode,port,started_at:new Date().toISOString()},null,2));
 for(let i=0;i<30;i++){await new Promise(resolve=>setTimeout(resolve,300));const current=await probe(port);if(isSame(current.status)){const url='http://127.0.0.1:'+port+'/core';console.log('已启动'+(mode==='legacy'?'旧版':'新版')+'：'+url);if(!process.argv.includes('--no-open'))open(url);return;}}
 return fail('启动未就绪，请查看本版本data目录的最新错误日志。');
}
if(require.main===module)main().catch(()=>fail('启动失败，请检查Node版本、端口和本机配置。'));
module.exports={probe,readSettings};
