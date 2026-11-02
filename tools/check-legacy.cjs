const fs=require('fs'),path=require('path'),crypto=require('crypto');const root=path.resolve(__dirname,'..');
function check(){const manifest=JSON.parse(fs.readFileSync(path.join(root,'docs/review/legacy-files.json'),'utf8'));return manifest.files.filter(row=>{const file=path.join(root,row.path);return !fs.existsSync(file)||crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex')!==row.hash;}).map(row=>({file:row.path,reason:'legacy_file_modified'}));}
if(require.main===module){const changes=check();console.log(JSON.stringify({old_files_checked:50,changed:changes.length,files:changes}));if(changes.length)process.exitCode=1;}
module.exports={check};
