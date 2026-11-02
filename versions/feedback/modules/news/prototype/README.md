# 新版运行入口

当前目录的 `server.js` 是反馈修订版后端，调用 `../../analysis/feedback-service.js`。`index-core.html` 对应 `/core`，`index.html` 对应 `/`，两者共用新版接口。

首次配置：复制本目录 `.env.example` 为 `.env`，填写iFinD授权、DeepSeek密钥与模型名；新版默认端口3003。真实配置不提交Git，不进入根目录生成的上传包。

从项目根目录双击 `启动新版.cmd`，或运行 `node tools/launch.cjs feedback`。停止用根目录 `停止新版.cmd`。不需要另装npm依赖，也不能双击本目录HTML作为业务运行入口。

直接启动：`node server.js --port=3003`。测试：在本目录运行 `npm test`。完整双版本说明见[根目录README](../../../../../README.md)。

本目录 `data/` 仅保存本机缓存、导入记录、日志和运行取证，不随项目发布。源码不内置真实密钥。
