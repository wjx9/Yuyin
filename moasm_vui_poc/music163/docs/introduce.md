8.8 网易云音乐

- 官方文档
skill：
	https://www.npmjs.com/package/@music163/ncm-cli
	https://github.com/NetEase/skills
	https://github.com/NetEase/skills/blob/master/netease-music-cli/SKILL.md

- 调用说明
	1. 在网易云音乐开放平台（https://music.163.com/st/developer/），通过个人/企业（需完成实名认证）登录，可获得技能调用的鉴权凭证（appid和privateKey）；
	2. 在本地agent中集成skill，并使用个人id和私钥作为身份凭证；
	3. 在agent中通过“我想听方大同的歌”等指令可触发，用户授权流程在skill交互过程中完成，返回二维码或链接进行OAuth登录，核心流程为授权登录-搜歌点歌-播放控制，在线播放目前支持mac和windows，依赖本地的mpv播放器组件；
	4. 个人使用观感，所谓的在线点播依赖本地环境，本地mpv自动安装和唤起流程繁琐，且容易出现失败，对于大众用户使用门槛较高，噱头大于实际体验；

- 接入提示:
  从本质上网易云音乐skill是2个能力的杂合:  1, 告诉(注册skill)到大模型, 当大模型知道自己是可以搜索和播放音乐的; 2, 实际执行搜索,播放音乐;
  对于demo而言, 在pc上将其集成到基于大模型的语音助手 这很容易. 但是对于实际商用client-server架构的语音助手来说, 当前skill不可能注册到client(android/ios). 
  其能力1+2看上去需要分两端步数: part1放在云端,而part2在客户端. part2有两种实现: 1, 跳转网易云音乐, 2,嵌入语音助手客户端. 
  先尝试实现纯pc步数 跑通流程. 然后再看cs架构,跳转网易云音乐app,最后是嵌入我们自己的语音助手客户端. 
  
