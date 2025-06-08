# 愿石 WishStone

愿石（WishStone）是一个面向寺庙 / 博物馆 / 古迹场景的祈福体验 MVP。该版本聚焦单场馆 demo，覆盖从祈福输入到回听链接与 NFC 绑定的核心链路。

## 已实现（MVP）

- 单场馆配置（默认：良渚文化博物馆）
- 语音录制与上传（浏览器端 `MediaRecorder`）
- ASR 转写（MVP 规则占位：优先使用输入文本）
- 祈福意图识别（规则分类：学业/事业/爱情/健康/财运）
- 内容安全审查（关键词拦截并降级中性祝福）
- 场景化 Prompt 回复生成（良渚守护者语气）
- TTS 音频生成（MVP 占位 `wav`）
- 数据持久化（SQLite）
- 专属回听链接（`/b/{slug}`）
- NFC 绑定接口（`/api/nfc/bind`）

## 项目结构

```text
Wishstone/
  app/
    server.py            # 后端主服务（HTTP + API + DB + 媒体）
    wishstone.db         # SQLite（首次启动自动创建）
    storage/
      user_audio/        # 用户录音
      ai_audio/          # AI 音频
    static/
      index.html         # 祈福装置页（录音/提交）
      blessing.html      # 回听页（播放/NFC 绑定）
      kiosk.js
      blessing.js
      style.css
  README.md
```

## 快速启动

```bash
cd /Users/kk/Personal/Projects/Wishstone
python3 app/server.py
```

打开：

- 装置页：`http://localhost:8080/`
- 回听页：提交后自动返回 `/b/{slug}`
- 后台页：`http://localhost:8080/admin`（需 `X-Admin-Token`）

可选环境变量：

```bash
ADMIN_TOKEN=your-token python3 app/server.py
```

## API 说明

### 1) 创建祈福会话

`POST /api/sessions`

支持：

- `multipart/form-data`：`venue_id` `device_id` `user_text` `audio`
- `application/json`：`venue_id` `device_id` `user_text`

返回：ASR、意图、AI 回复、音频 URL、回听页面 URL。

### 2) 查询会话

`GET /api/sessions/{slug}`

返回指定祈福记录详情，用于回听页渲染。

### 3) NFC 绑定

`POST /api/nfc/bind`

请求示例：

```json
{
  "blessing_session_id": "sess-xxxx",
  "nfc_uid": "04:A1:BC:9F",
  "souvenir_sku": "WS-LZ-001"
}
```

### 4) 管理后台接口

- `GET /api/admin/stats`：会话统计与热门意图
- `GET /api/admin/sessions?limit=30`：最近会话列表
- `POST /api/admin/sessions/{session_id}/review`：更新审核状态（`pending/approved/blocked`）
- `GET /api/admin/prompts/{venue_id}`：读取场馆 Prompt
- `POST /api/admin/prompts/{venue_id}`：更新 Prompt 并自动版本号 +1
- `GET /api/admin/nfc-bindings`：NFC 绑定记录

以上接口需要请求头：`X-Admin-Token: <token>`

## 与需求文档对应关系

- `6.2 ASR 转写模块`：MVP 规则占位（便于后续接入真实 ASR）
- `6.3 祈福意图识别模块`：规则分类 + 情绪判断 + 安全状态
- `6.4 Prompt 编排模块`：按场馆模板读取角色和风格
- `6.5 AI 文本生成模块`：基于意图生成场景化回复
- `6.6 TTS 模块`：占位音频生成，保留真实 TTS 接入点
- `6.7/6.8`：会话存储 + 回听页
- `6.9`：NFC 绑定落表

## 下一步建议

1. 把 `mock_asr_text` 替换成真实 ASR（如 FunASR / 云 ASR）
2. 把 `generate_reply` 替换成 LLM 服务（加输出审核）
3. 把 `synthesize_placeholder_audio` 替换成真实 TTS
4. 增加管理后台（场馆配置、Prompt 版本、内容审核）
