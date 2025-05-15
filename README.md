# Midjourney API

这是一个封装Discord Midjourney Bot的API服务，允许通过简单的REST API调用来生成和操作图片。

## 设置

1. 复制 `.env.example` 到 `.env` 并填写配置:
   ```
   DISCORD_CHANNEL_ID=你的频道ID
   DISCORD_GUILD_ID=你的服务器ID
   DISCORD_USER_TOKEN=你的Discord用户令牌
   # 或者
   DISCORD_BOT_TOKEN=你的Discord机器人令牌
   CALLBACK_URL=http://localhost:8000/v1/api/trigger/callback
   DRAW_VERSION=1237876415471554623
   API_URL=http://localhost:8000  # 用于bot提交消息到API
   ```

2. 安装依赖:
   ```
   pip install -r requirements.txt
   ```

## 运行服务

1. 启动API服务:
   ```
   uvicorn main:app --reload
   ```

2. 在另一个终端启动Discord监听服务:
   ```
   python bot.py
   ```

## 测试API

使用提供的测试脚本测试API:

```bash
# 基础测试 - 生成图像
python test_api.py --prompt "landscape"

# 设置超时时间
python test_api.py --prompt "landscape" --timeout 600

# 查询特定任务状态
python test_api.py --status "你的任务ID"

# 交互式测试模式
python test_api.py -i

# 放大图像测试
python test_upscale.py 消息ID 消息哈希 --index 1
```

## API端点
<details>
<summary>点击展开API端点列表</summary>
### 图像生成

```
POST /v1/api/trigger/imagine
Content-Type: application/json

{
  "prompt": "你的提示词"
}

返回:
{
  "trigger_id": "生成的任务ID",
  "trigger_type": "generate",
  "message": "success"
}
```

### 查询任务状态

```
GET /v1/api/status/{trigger_id}

返回:
{
  "trigger_id": "任务ID",
  "status": "pending|generating|completed|failed",
  "type": "操作类型",
  "created_at": "创建时间",
  "updated_at": "最后更新时间",
  "result": {
    "image_urls": ["图像URL1", "图像URL2"],
    "message_id": "Discord消息ID",
    "hash": "图像哈希",
    ...
  }
}
```

### 放大图像 [WIP]

放大是一个特殊操作，它会创建一个新的Discord消息，而不是修改原有消息。系统会自动关联新消息与原始请求。

```
POST /v1/api/trigger/upscale
Content-Type: application/json

{
  "trigger_id": "自定义任务ID",  // 可选，如不提供会自动生成
  "msg_id": "原始消息ID",       // Discord消息ID
  "msg_hash": "消息哈希",       // 图像哈希值
  "index": 1                  // 要放大的图像索引(1-4)
}

返回:
{
  "trigger_id": "任务ID",
  "trigger_type": "upscale",
  "message": "success"
}
```

### 创建变体 [WIP]

```
POST /v1/api/trigger/variation
Content-Type: application/json

{
  "trigger_id": "任务ID",
  "msg_id": "消息ID",
  "msg_hash": "消息哈希",
  "index": 1                // 要变体的图像索引(1-4)
}
```

### 重置/重新生成 [WIP]

```
POST /v1/api/trigger/reset
Content-Type: application/json

{
  "trigger_id": "任务ID",
  "msg_id": "消息ID",
  "msg_hash": "消息哈希"
}
```

### 扩展图像 [WIP]

```
POST /v1/api/trigger/expand
Content-Type: application/json

{
  "trigger_id": "任务ID",
  "msg_id": "消息ID",
  "msg_hash": "消息哈希",
  "direction": "up|down|left|right" // 扩展方向
}
```

### 放大/缩小 [WIP]

```
POST /v1/api/trigger/zoomout
Content-Type: application/json

{
  "trigger_id": "任务ID", 
  "msg_id": "消息ID",
  "msg_hash": "消息哈希",
  "zoomout": 50           // 缩放比例(50=2x, 75=1.5x)
}
```

### 上传图像

```
POST /v1/api/trigger/upload
Content-Type: multipart/form-data

file: [图像文件]

返回:
{
  "message": "success",
  "upload_filename": "上传文件名",
  "upload_url": "上传URL",
  "trigger_id": "任务ID"
}
```

### ID映射关系查询

查询ID之间的关联关系，对跟踪upscale等操作产生的新消息非常有用。

```
GET /v1/api/id_mapping/{any_id}

返回:
{
  "original_id": "原始ID",
  "query_id": "查询ID",
  "is_original": true|false,
  "related_ids": ["关联ID1", "关联ID2", ...]
}
```
</details>

## 状态码说明

- `pending` - 任务已创建，等待处理
- `generating` - 图像正在生成中 (对于长任务，可能会收到进度更新)
- `completed` - 图像生成完成
- `failed` - 图像生成失败

## 高级功能

### 自定义图像下载目录

可以通过环境变量设置图像下载目录:

```
IMAGE_DOWNLOAD_DIR=/path/to/images
```

### 批量任务处理

使用`_queue.py`中的任务队列，可以同时提交多个任务，系统会根据配置的并发数自动处理:

```python
from _queue import taskqueue
from api import generate

# 添加多个任务到队列
for prompt in prompts:
    trigger_id = str(uuid.uuid4())
    taskqueue.put(trigger_id, generate, prompt, trigger_id)
```

### ID映射系统

为了解决Discord消息ID与API任务ID的映射问题，系统使用了多种策略:

1. 直接映射 - 显式关联ID
2. 哈希映射 - 通过图像哈希关联
3. 启发式关联 - 通过时间和操作类型推断关系

这使得即使Discord生成全新消息，系统也能正确关联到原始请求。

## 常见问题排除

### 任务状态返回404

确保:
1. 触发ID正确
2. API和机器人服务都在运行
3. Discord机器人配置正确且有权限

### Discord连接错误

检查:
1. Discord令牌是否有效
2. 网络连接是否正常
3. 服务器和频道ID是否正确

### Upscale操作不返回图像结果

对于upscale操作，Discord会创建一个全新的消息，而不是修改原始消息。API系统会尝试关联这些消息，但有时需要等待:

1. 使用`test_upscale.py`脚本测试，它会持续监控新消息
2. 检查`/v1/api/id_mapping/{trigger_id}`接口获取关联ID
3. 如果仍然找不到结果，直接在Discord查看最新消息

### 代理配置

如果在网络受限环境中，可以配置代理:

```
PROXY_URL=http://your-proxy:port
```

## 后续开发

扩展关键模块:

- `main.py` - API端点定义
- `api.py` - Discord API交互
- `bot.py` - Discord事件监听
- `id_mapper.py` - ID关联系统
- `_queue.py` - 任务队列管理

在添加新功能时，遵循现有模式并确保正确处理ID映射和回调机制。