# 安全说明

这个仓库不保存任何密钥。脚本用的是你本机 `gcloud` 的登录态和 Application Default Credentials，部署坐标在 `~/.hyperframes/cloudrun-state.json`，都留在你自己的电脑上，不要提交进仓库。

渲染桶里的文件 7 天自动删除；HyperFrames 部署的 Cloud Run 服务只允许它自己的服务账号调用。额度用完后的费用会记到结算账户的付款方式上，请设预算提醒，部署时保留 `--max-instances` 上限。

发现安全问题请在 GitHub 上开 issue，不要贴出你的项目 ID、结算账户或密钥。
